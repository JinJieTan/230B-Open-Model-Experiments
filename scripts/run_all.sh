#!/usr/bin/env bash
set -euo pipefail

python scripts/run_pipeline.py

echo "Done. Open site with: python -m http.server --directory site 4173"
