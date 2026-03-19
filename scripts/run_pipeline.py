from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime import env_bool, load_dotenv


def run_step(cmd: list[str]) -> int:
    print(f"[step] {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cross-platform runner: execute experiments, aggregate, then build site.")
    parser.add_argument("--skip-run", action="store_true", help="Skip experiment execution.")
    parser.add_argument("--skip-aggregate", action="store_true", help="Skip aggregate step.")
    parser.add_argument("--skip-site", action="store_true", help="Skip static site build step.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(Path(".env"), override=True)

    if env_bool("PIPELINE_SKIP_RUN", False):
        args.skip_run = True
    if env_bool("PIPELINE_SKIP_AGGREGATE", False):
        args.skip_aggregate = True
    if env_bool("PIPELINE_SKIP_SITE", False):
        args.skip_site = True

    if not args.skip_run:
        rc = run_step([sys.executable, "runners/run_experiments.py"])
        if rc != 0:
            return rc

    if not args.skip_aggregate:
        rc = run_step([sys.executable, "scripts/aggregate_results.py"])
        if rc != 0:
            return rc

    if not args.skip_site:
        rc = run_step([sys.executable, "scripts/build_site.py"])
        if rc != 0:
            return rc

    print("[done] Pipeline finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
