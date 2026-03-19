@echo off
setlocal

python scripts\run_pipeline.py
if errorlevel 1 exit /b %errorlevel%

echo Done. Open site with: python -m http.server --directory site 4173
