from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime import env_str, load_dotenv


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_configs(config_dir: Path) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []

    for path in sorted(config_dir.glob("*.yaml")):
        stem = path.stem
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            if not isinstance(data, dict):
                raise ValueError("config must be a YAML mapping")

            slug = str(data.get("slug", stem)).strip() or stem
            configs.append(
                {
                    "id": data.get("id", slug),
                    "slug": slug,
                    "title": data.get("title", slug),
                    "_file": str(path),
                    "_config_error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            configs.append(
                {
                    "id": stem,
                    "slug": stem,
                    "title": stem,
                    "_file": str(path),
                    "_config_error": f"{exc}",
                }
            )

    return configs


def load_metrics(metrics_dir: Path) -> dict[str, dict[str, Any]]:
    by_slug: dict[str, dict[str, Any]] = {}
    for path in sorted(metrics_dir.glob("*.json")):
        if path.name == "summary.json":
            continue

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:  # noqa: BLE001
            slug = path.stem
            by_slug[slug] = {
                "id": slug,
                "slug": slug,
                "title": slug,
                "status": "metric_parse_error",
                "final_score": 0.0,
                "keyword_coverage": 0.0,
                "format_score": 0.0,
                "length_score": 0.0,
                "coherence_score": 0.0,
                "rounds": 0,
                "latency_total_sec": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "model": None,
                "updated_at": utcnow_iso(),
                "notes": f"Metric parse error: {exc}",
            }
            continue

        slug = str(data.get("slug", "")).strip() or path.stem
        data["slug"] = slug
        by_slug[slug] = data

    return by_slug


def aggregate_summary(
    *,
    config_dir: Path,
    metrics_dir: Path,
    summary_json_path: Path | None = None,
    summary_csv_path: Path | None = None,
) -> dict[str, Any]:
    if summary_json_path is None:
        summary_json_path = metrics_dir / "summary.json"
    if summary_csv_path is None:
        summary_csv_path = metrics_dir.parent / "summary.csv"

    configs = load_configs(config_dir)
    metrics_by_slug = load_metrics(metrics_dir)

    rows: list[dict[str, Any]] = []
    for cfg in configs:
        slug = str(cfg.get("slug", "")).strip()
        metric = metrics_by_slug.get(slug)

        if metric is None and cfg.get("_config_error"):
            row = {
                "id": cfg.get("id"),
                "slug": slug,
                "title": cfg.get("title", slug),
                "status": "config_error",
                "final_score": 0.0,
                "keyword_coverage": 0.0,
                "format_score": 0.0,
                "length_score": 0.0,
                "coherence_score": 0.0,
                "rounds": 0,
                "latency_total_sec": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "model": None,
                "updated_at": utcnow_iso(),
                "notes": f"Config parse error: {cfg.get('_config_error')}",
            }
        elif metric is None:
            row = {
                "id": cfg.get("id"),
                "slug": slug,
                "title": cfg.get("title", slug),
                "status": "not_run",
                "final_score": None,
                "keyword_coverage": None,
                "format_score": None,
                "length_score": None,
                "coherence_score": None,
                "rounds": 0,
                "latency_total_sec": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "model": None,
                "updated_at": None,
                "notes": None,
            }
        else:
            row = {
                "id": metric.get("id", cfg.get("id")),
                "slug": slug,
                "title": metric.get("title", cfg.get("title", slug)),
                "status": metric.get("status", "unknown"),
                "final_score": metric.get("final_score"),
                "keyword_coverage": metric.get("keyword_coverage"),
                "format_score": metric.get("format_score"),
                "length_score": metric.get("length_score"),
                "coherence_score": metric.get("coherence_score"),
                "rounds": metric.get("rounds", 0),
                "latency_total_sec": metric.get("latency_total_sec"),
                "prompt_tokens": metric.get("prompt_tokens"),
                "completion_tokens": metric.get("completion_tokens"),
                "total_tokens": metric.get("total_tokens"),
                "model": metric.get("model"),
                "updated_at": metric.get("updated_at"),
                "notes": metric.get("notes"),
            }
        rows.append(row)

    completed_rows = [r for r in rows if r.get("status") == "completed" and isinstance(r.get("final_score"), (int, float))]
    average_final_score = (
        round(sum(float(r["final_score"]) for r in completed_rows) / len(completed_rows), 4)
        if completed_rows
        else None
    )

    summary = {
        "generated_at": utcnow_iso(),
        "totals": {
            "total": len(rows),
            "completed": len([r for r in rows if r.get("status") == "completed"]),
            "failed": len([r for r in rows if r.get("status") == "failed"]),
            "not_run": len([r for r in rows if r.get("status") in {"not_run", "skipped_missing_prompt", "dry_run"}]),
            "errored": len([r for r in rows if str(r.get("status", "")).endswith("error")]),
            "average_final_score": average_final_score,
        },
        "experiments": rows,
    }

    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    write_summary_csv(rows, summary_csv_path)
    return summary


def write_summary_csv(rows: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "slug",
        "title",
        "status",
        "final_score",
        "keyword_coverage",
        "format_score",
        "length_score",
        "coherence_score",
        "rounds",
        "latency_total_sec",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "model",
        "updated_at",
        "notes",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate experiment metrics into summary files.")
    parser.add_argument("--config-dir", default=None, help="Experiment config directory.")
    parser.add_argument("--metrics-dir", default=None, help="Metric directory.")
    parser.add_argument("--summary-json", default=None, help="Summary JSON output path.")
    parser.add_argument("--summary-csv", default=None, help="Summary CSV output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(Path(".env"), override=True)

    config_dir = Path(args.config_dir or env_str("CONFIG_DIR", "experiments"))
    metrics_dir = Path(args.metrics_dir or env_str("METRICS_DIR", "results/metrics"))
    summary_json = Path(args.summary_json or env_str("SUMMARY_JSON_PATH", "results/metrics/summary.json"))
    summary_csv = Path(args.summary_csv or env_str("SUMMARY_CSV_PATH", "results/summary.csv"))

    summary = aggregate_summary(
        config_dir=config_dir,
        metrics_dir=metrics_dir,
        summary_json_path=summary_json,
        summary_csv_path=summary_csv,
    )

    print(
        "[aggregate] "
        f"total={summary['totals']['total']} "
        f"completed={summary['totals']['completed']} "
        f"avg_score={summary['totals']['average_final_score']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
