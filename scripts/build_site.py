from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.aggregate_results import aggregate_summary
from scripts.runtime import env_str, load_dotenv


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def compact_raw_result(raw: dict[str, Any]) -> dict[str, Any]:
    rounds = raw.get("rounds", [])
    preview = ""
    if rounds:
        last = rounds[-1]
        preview = str(last.get("response", ""))

    preview = preview.strip()
    if len(preview) > 900:
        preview = preview[:900] + "\n... (truncated)"

    return {
        "status": raw.get("status"),
        "error": raw.get("error"),
        "rounds": len(rounds),
        "started_at": raw.get("started_at"),
        "finished_at": raw.get("finished_at"),
        "preview": preview,
    }


def build_site(
    *,
    config_dir: Path,
    metrics_dir: Path,
    raw_dir: Path,
    site_dir: Path,
    template_dir: Path,
    summary_json_path: Path,
    summary_csv_path: Path,
) -> dict[str, Any]:
    summary = aggregate_summary(
        config_dir=config_dir,
        metrics_dir=metrics_dir,
        summary_json_path=summary_json_path,
        summary_csv_path=summary_csv_path,
    )

    raw_by_slug: dict[str, Any] = {}
    for item in summary.get("experiments", []):
        slug = item.get("slug")
        if not slug:
            continue
        raw_path = raw_dir / f"{slug}.json"
        raw_data = load_json(raw_path)
        if raw_data:
            raw_by_slug[slug] = compact_raw_result(raw_data)

    site_payload = {
        "generated_at": utcnow_iso(),
        "summary": summary,
        "raw_previews": raw_by_slug,
    }

    site_dir.mkdir(parents=True, exist_ok=True)

    for name in ["index.html", "style.css", "app.js"]:
        src = template_dir / name
        dst = site_dir / name
        if not src.exists():
            raise FileNotFoundError(f"Missing template file: {src}")
        shutil.copy2(src, dst)

    with (site_dir / "data.json").open("w", encoding="utf-8") as f:
        json.dump(site_payload, f, indent=2, ensure_ascii=False)

    return site_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static dashboard site from experiment outputs.")
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--metrics-dir", default=None)
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--site-dir", default=None)
    parser.add_argument("--template-dir", default=None)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--summary-csv", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(Path(".env"), override=True)

    config_dir = Path(args.config_dir or env_str("CONFIG_DIR", "experiments"))
    metrics_dir = Path(args.metrics_dir or env_str("METRICS_DIR", "results/metrics"))
    raw_dir = Path(args.raw_dir or env_str("RAW_DIR", "results/raw"))
    site_dir = Path(args.site_dir or env_str("SITE_DIR", "site"))
    template_dir = Path(args.template_dir or env_str("TEMPLATE_DIR", "web/template"))
    summary_json_path = Path(args.summary_json or env_str("SUMMARY_JSON_PATH", "results/metrics/summary.json"))
    summary_csv_path = Path(args.summary_csv or env_str("SUMMARY_CSV_PATH", "results/summary.csv"))

    payload = build_site(
        config_dir=config_dir,
        metrics_dir=metrics_dir,
        raw_dir=raw_dir,
        site_dir=site_dir,
        template_dir=template_dir,
        summary_json_path=summary_json_path,
        summary_csv_path=summary_csv_path,
    )
    totals = payload["summary"]["totals"]
    print(
        "[site] "
        f"generated={payload['generated_at']} "
        f"completed={totals['completed']}/{totals['total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
