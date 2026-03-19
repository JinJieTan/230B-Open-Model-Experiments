from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import traceback
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluators.registry import evaluate_experiment
from runners.browser_context import BrowserSession, browser_snapshot_to_message, resolve_browser_settings
from runners.model_client import OpenAICompatibleClient, load_client_from_env
from scripts.aggregate_results import aggregate_summary
from scripts.runtime import env_bool, env_float, env_int, env_str, load_dotenv, split_task_tokens


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_configs(config_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    for path in sorted(config_dir.glob("*.yaml")):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            if not isinstance(data, dict):
                raise ValueError("config must be a YAML mapping")

            stem = path.stem
            slug = str(data.get("slug", stem)).strip() or stem
            data["slug"] = slug
            data.setdefault("id", slug)
            data.setdefault("title", slug)
            data["_file"] = str(path)
            valid.append(data)
        except Exception as exc:  # noqa: BLE001
            stem = path.stem
            invalid.append(
                {
                    "id": stem,
                    "slug": stem,
                    "title": stem,
                    "_file": str(path),
                    "_load_error": f"{exc}",
                }
            )

    return valid, invalid


def select_messages(
    history: list[dict[str, str]],
    system_prompt: str,
    history_window: int,
) -> list[dict[str, str]]:
    window = max(1, history_window)
    clipped = history[-window:] if history else []

    if clipped and clipped[0]["role"] == "assistant" and len(history) > window:
        clipped = history[-(window + 1) :]

    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.extend(clipped)
    return messages


def to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def chat_with_retry(
    *,
    client: OpenAICompatibleClient,
    model_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    max_api_retries: int,
    retry_backoff_sec: float,
):
    attempts = max(1, max_api_retries + 1)
    last_error: Exception | None = None

    for attempt_idx in range(attempts):
        try:
            return client.chat(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt_idx >= attempts - 1:
                break
            sleep_sec = max(0.0, retry_backoff_sec) * (attempt_idx + 1)
            if sleep_sec > 0:
                time.sleep(sleep_sec)

    assert last_error is not None
    raise last_error


def run_single_experiment(
    config: dict[str, Any],
    *,
    client: OpenAICompatibleClient | None,
    model_name: str,
    dry_run: bool,
    max_api_retries: int,
    retry_backoff_sec: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    slug = str(config.get("slug", "unknown")).strip()
    title = str(config.get("title", slug)).strip()

    started_at = utcnow_iso()
    prompt = str(config.get("prompt", "")).strip()

    run_result: dict[str, Any] = {
        "id": config.get("id", slug),
        "slug": slug,
        "title": title,
        "model": model_name,
        "started_at": started_at,
        "finished_at": None,
        "status": "pending",
        "config_file": config.get("_file"),
        "rounds": [],
        "error": None,
    }

    if not prompt or "TODO_PROMPT" in prompt:
        run_result["status"] = "skipped_missing_prompt"
        run_result["finished_at"] = utcnow_iso()
        metric = evaluate_experiment(config, run_result)
        return run_result, enrich_metric(config, run_result, metric)

    if dry_run:
        run_result["status"] = "dry_run"
        run_result["finished_at"] = utcnow_iso()
        metric = evaluate_experiment(config, run_result)
        return run_result, enrich_metric(config, run_result, metric)

    if client is None:
        run_result["status"] = "failed"
        run_result["error"] = "No model client available."
        run_result["finished_at"] = utcnow_iso()
        metric = evaluate_experiment(config, run_result)
        return run_result, enrich_metric(config, run_result, metric)

    rounds = max(1, to_int(config.get("rounds", 1)))
    history_window = max(1, to_int(config.get("history_window", 8)))
    temperature = float(config.get("temperature", 0.7))
    max_tokens = max(64, to_int(config.get("max_tokens", 1024)))
    system_prompt = str(config.get("system_prompt", "")).strip()
    browser_settings = resolve_browser_settings(config)
    run_result["browser"] = {
        "enabled": browser_settings.enabled,
        "url": browser_settings.url,
        "round_interval": browser_settings.round_interval,
        "required": browser_settings.required,
        "refresh_every_round": browser_settings.refresh_every_round,
    }

    follow_up_template = str(
        config.get(
            "follow_up_prompt_template",
            "Continue round {round}/{total_rounds}. Keep consistency with prior outputs.",
        )
    ).strip()

    history: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    browser_session: BrowserSession | None = BrowserSession(browser_settings) if browser_settings.enabled else None

    try:
        for round_idx in range(rounds):
            browser_snapshot: dict[str, Any] | None = None
            if browser_session is not None:
                try:
                    browser_snapshot = browser_session.snapshot(round_number=round_idx + 1, total_rounds=rounds)
                    if browser_snapshot.get("status") == "ok":
                        history.append({"role": "user", "content": browser_snapshot_to_message(browser_snapshot)})
                except Exception as exc:  # noqa: BLE001
                    browser_snapshot = {
                        "status": "error",
                        "error": str(exc),
                        "round": round_idx + 1,
                        "total_rounds": rounds,
                        "captured_at": utcnow_iso(),
                    }
                    if browser_session.required:
                        raise
                    browser_session.close()
                    browser_session = None
                    history.append(
                        {
                            "role": "user",
                            "content": f"[Browser Snapshot Error]\n{exc}\nContinue without browser context for remaining rounds.",
                        }
                    )

            messages = select_messages(history, system_prompt, history_window)
            t0 = time.perf_counter()

            response = chat_with_retry(
                client=client,
                model_name=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                max_api_retries=max_api_retries,
                retry_backoff_sec=retry_backoff_sec,
            )

            latency = round(time.perf_counter() - t0, 4)
            response_text = response.content.strip()

            run_result["rounds"].append(
                {
                    "round": round_idx + 1,
                    "latency_sec": latency,
                    "finish_reason": response.finish_reason,
                    "usage": response.usage,
                    "response": response_text,
                    "browser": browser_snapshot,
                }
            )
            history.append({"role": "assistant", "content": response_text})

            if round_idx < rounds - 1:
                next_prompt = follow_up_template.format(round=round_idx + 2, total_rounds=rounds)
                history.append({"role": "user", "content": next_prompt})

        run_result["status"] = "completed"
    except Exception as exc:  # noqa: BLE001
        run_result["status"] = "failed"
        run_result["error"] = f"{exc}\n{traceback.format_exc()}"
    finally:
        if browser_session is not None:
            browser_session.close()

    run_result["finished_at"] = utcnow_iso()
    metric = evaluate_experiment(config, run_result)
    return run_result, enrich_metric(config, run_result, metric)


def build_config_error_outputs(config: dict[str, Any], model_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    started_at = utcnow_iso()
    finished_at = utcnow_iso()
    slug = str(config.get("slug", "unknown")).strip()
    title = str(config.get("title", slug)).strip()

    raw_payload = {
        "id": config.get("id", slug),
        "slug": slug,
        "title": title,
        "model": model_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": "config_error",
        "config_file": config.get("_file"),
        "rounds": [],
        "error": config.get("_load_error", "Unknown config parse error"),
    }

    metric_payload = {
        "id": config.get("id", slug),
        "slug": slug,
        "title": title,
        "scoring_profile": "config",
        "status": "config_error",
        "model": model_name,
        "rounds": 0,
        "latency_total_sec": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "started_at": started_at,
        "finished_at": finished_at,
        "final_score": 0.0,
        "keyword_coverage": 0.0,
        "format_score": 0.0,
        "length_score": 0.0,
        "coherence_score": 0.0,
        "notes": "Configuration parsing failed.",
        "updated_at": utcnow_iso(),
    }

    return raw_payload, metric_payload


def enrich_metric(
    config: dict[str, Any],
    run_result: dict[str, Any],
    metric: dict[str, Any],
) -> dict[str, Any]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    latency_total_sec = 0.0

    for row in run_result.get("rounds", []):
        usage = row.get("usage") or {}
        prompt_tokens += to_int(usage.get("prompt_tokens"))
        completion_tokens += to_int(usage.get("completion_tokens"))
        total_tokens += to_int(usage.get("total_tokens"))
        latency_total_sec += float(row.get("latency_sec", 0.0))

    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    payload: dict[str, Any] = {
        "id": run_result.get("id"),
        "slug": run_result.get("slug"),
        "title": run_result.get("title"),
        "scoring_profile": config.get("scoring_profile", "generic"),
        "status": run_result.get("status"),
        "model": run_result.get("model"),
        "rounds": len(run_result.get("rounds", [])),
        "latency_total_sec": round(latency_total_sec, 4),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "started_at": run_result.get("started_at"),
        "finished_at": run_result.get("finished_at"),
    }
    payload.update(metric)
    payload["updated_at"] = utcnow_iso()
    return payload


def read_task_file(path: Path) -> list[str]:
    if not path.exists():
        return []

    tokens: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens.extend(split_task_tokens([line]))
    return tokens


def choose_configs(
    *,
    valid_configs: list[dict[str, Any]],
    invalid_configs: list[dict[str, Any]],
    run_all: bool,
    requested_tokens: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if run_all:
        return valid_configs, invalid_configs, []

    token_set = {token.strip() for token in requested_tokens if token.strip()}
    if not token_set:
        return [], [], []

    selected_valid: list[dict[str, Any]] = []
    selected_invalid: list[dict[str, Any]] = []
    matched: set[str] = set()

    for cfg in valid_configs:
        slug = str(cfg.get("slug", "")).strip()
        cfg_id = str(cfg.get("id", slug)).strip()
        if slug in token_set or cfg_id in token_set:
            selected_valid.append(cfg)
            matched.add(slug)
            matched.add(cfg_id)

    for cfg in invalid_configs:
        slug = str(cfg.get("slug", "")).strip()
        cfg_id = str(cfg.get("id", slug)).strip()
        if slug in token_set or cfg_id in token_set:
            selected_invalid.append(cfg)
            matched.add(slug)
            matched.add(cfg_id)

    unmatched = sorted(token_set - matched)
    return selected_valid, selected_invalid, unmatched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run configured experiments against an OpenAI-compatible endpoint.")
    parser.add_argument("--all", action="store_true", help="Run all experiment configs in experiments/.")
    parser.add_argument(
        "--experiment",
        action="append",
        default=[],
        help="Run selected experiment slug/id. Repeatable; comma-separated values allowed.",
    )
    parser.add_argument(
        "--tasks",
        action="append",
        default=[],
        help="Additional task list, e.g. --tasks exp01,exp02,exp09.",
    )
    parser.add_argument(
        "--task-file",
        action="append",
        default=[],
        help="Path to a text file containing one slug/id per line.",
    )
    parser.add_argument("--config-dir", default=None, help="Experiment config directory.")
    parser.add_argument("--raw-dir", default=None, help="Raw output directory.")
    parser.add_argument("--metrics-dir", default=None, help="Metric output directory.")
    parser.add_argument("--dry-run", action="store_true", help="Skip model calls and emit dry-run files.")
    parser.add_argument("--max-retries", type=int, default=None, help="API retry count for each model request.")
    parser.add_argument("--retry-backoff-sec", type=float, default=None, help="Backoff seconds per retry step.")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop remaining tasks after first failed task.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(Path(".env"), override=True)

    config_dir = Path(args.config_dir or env_str("CONFIG_DIR", "experiments"))
    raw_dir = Path(args.raw_dir or env_str("RAW_DIR", "results/raw"))
    metrics_dir = Path(args.metrics_dir or env_str("METRICS_DIR", "results/metrics"))

    dry_run = args.dry_run or env_bool("RUN_DRY_RUN", False)
    continue_on_error = (not args.stop_on_error) and env_bool("CONTINUE_ON_ERROR", True)
    max_api_retries = args.max_retries if args.max_retries is not None else env_int("MAX_API_RETRIES", 2)
    retry_backoff_sec = (
        args.retry_backoff_sec if args.retry_backoff_sec is not None else env_float("RETRY_BACKOFF_SEC", 2.0)
    )

    valid_configs, invalid_configs = load_configs(config_dir)
    if not valid_configs and not invalid_configs:
        raise SystemExit(f"No experiment configs found in: {config_dir}")

    cli_tokens = split_task_tokens(args.experiment + args.tasks)
    env_tokens = split_task_tokens([env_str("EXPERIMENT_TASKS", "")])

    task_files = [Path(path) for path in args.task_file]
    task_file_from_env = env_str("EXPERIMENT_TASK_FILE", "")
    if task_file_from_env:
        for token in split_task_tokens([task_file_from_env]):
            task_files.append(Path(token))

    file_tokens: list[str] = []
    for task_path in task_files:
        file_tokens.extend(read_task_file(task_path))

    requested_tokens = cli_tokens + env_tokens + file_tokens
    run_all = args.all or env_bool("RUN_ALL", False) or any(token.lower() == "all" for token in requested_tokens)

    selected_valid, selected_invalid, unmatched_tokens = choose_configs(
        valid_configs=valid_configs,
        invalid_configs=invalid_configs,
        run_all=run_all,
        requested_tokens=requested_tokens,
    )

    if unmatched_tokens:
        print(f"[warn] Unknown tasks ignored: {', '.join(unmatched_tokens)}")

    if not selected_valid and not selected_invalid:
        raise SystemExit("No matching experiments selected. Check .env EXPERIMENT_TASKS or CLI --tasks.")

    client: OpenAICompatibleClient | None = None
    model_name = env_str("MODEL_NAME", "not-configured")
    if not dry_run:
        client, model_name = load_client_from_env()

    ensure_dir(raw_dir)
    ensure_dir(metrics_dir)

    stop_requested = False

    for cfg in selected_invalid:
        slug = str(cfg.get("slug", "unknown")).strip()
        raw_payload, metric_payload = build_config_error_outputs(cfg, model_name=model_name)
        write_json(raw_dir / f"{slug}.json", raw_payload)
        write_json(metrics_dir / f"{slug}.json", metric_payload)
        print(f"[config-error] {slug} status=config_error")

        if not continue_on_error:
            print("[stop] Stopping due to config_error and CONTINUE_ON_ERROR disabled.")
            stop_requested = True
            break

    for config in selected_valid:
        if stop_requested:
            break
        slug = str(config.get("slug", "unknown")).strip()
        print(f"[run] {slug}")

        try:
            run_result, metric = run_single_experiment(
                config,
                client=client,
                model_name=model_name,
                dry_run=dry_run,
                max_api_retries=max_api_retries,
                retry_backoff_sec=retry_backoff_sec,
            )
        except Exception as exc:  # noqa: BLE001
            run_result = {
                "id": config.get("id", slug),
                "slug": slug,
                "title": config.get("title", slug),
                "model": model_name,
                "started_at": utcnow_iso(),
                "finished_at": utcnow_iso(),
                "status": "failed",
                "config_file": config.get("_file"),
                "rounds": [],
                "error": f"Unhandled runner exception: {exc}\n{traceback.format_exc()}",
            }
            metric = {
                "status": "failed",
                "final_score": 0.0,
                "keyword_coverage": 0.0,
                "format_score": 0.0,
                "length_score": 0.0,
                "coherence_score": 0.0,
                "notes": "Unhandled runner exception.",
            }
            metric = enrich_metric(config, run_result, metric)

        raw_path = raw_dir / f"{slug}.json"
        metric_path = metrics_dir / f"{slug}.json"
        write_json(raw_path, run_result)
        write_json(metric_path, metric)

        print(
            f"[done] {slug} status={metric.get('status')} score={metric.get('final_score')} "
            f"latency={metric.get('latency_total_sec')}s"
        )

        if metric.get("status") in {"failed", "config_error"} and not continue_on_error:
            print("[stop] Stopping due to failure and CONTINUE_ON_ERROR disabled.")
            stop_requested = True
            break

    summary = aggregate_summary(config_dir=config_dir, metrics_dir=metrics_dir)
    print(
        "[summary] "
        f"completed={summary['totals']['completed']} "
        f"total={summary['totals']['total']} "
        f"avg_score={summary['totals']['average_final_score']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
