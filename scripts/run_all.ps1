$ErrorActionPreference = "Stop"

python scripts/run_pipeline.py

Write-Host "Done. Open site with: python -m http.server --directory site 4173"
