# 230B Experiment Lab

A reproducible framework for your 10 custom experiments:
- configurable experiment definitions (`experiments/*.yaml`)
- unified runner for OpenAI-compatible model endpoints
- fault-tolerant serial execution (continue on error)
- static dashboard for GitHub Pages / Cloudflare Pages

## Project Structure

```text
experiments/            # 10 experiment YAML configs (fill prompt here)
runners/                # execution engine
evaluators/             # scoring logic
scripts/                # pipeline + aggregate + build site
results/
  raw/                  # per-experiment raw outputs
  metrics/              # per-experiment metrics + summary.json
  summary.csv           # flat summary for quick sharing
web/template/           # static site template
site/                   # generated site artifacts
.github/workflows/      # CI for run/deploy
```

## 1) Setup (macOS / Linux / Windows)

Install Python 3.10+ and dependencies:

```bash
pip install -r requirements.txt
```

If you want browser-grounded runs via Playwright, install browser binaries once:

```bash
python -m playwright install chromium
```

Create env file:

```bash
cp .env.example .env
```

Windows alternatives:
- PowerShell: `Copy-Item .env.example .env`
- CMD: `copy .env.example .env`

Then edit `.env` only. All key runtime settings are there:
- model endpoint and API key
- task selection (`RUN_ALL`, `EXPERIMENT_TASKS`, `EXPERIMENT_TASK_FILE`)
- error strategy (`CONTINUE_ON_ERROR`, retries)
- output paths
- optional browser context (`ENABLE_HEADLESS_BROWSER`, `BROWSER_BASE_URL`, etc.)

## 2) Fill Your 10 Prompts

Edit each file in `experiments/` and replace `TODO_PROMPT`.

## 3) Run (Cross-Platform)

Recommended single command (works on macOS / Linux / Windows):

```bash
python scripts/run_pipeline.py
```

This does:
1. run experiments
2. aggregate metrics
3. build dashboard site

OS helpers:
- macOS/Linux: `bash scripts/run_all.sh`
- PowerShell: `./scripts/run_all.ps1`
- CMD: `scripts\\run_all.bat`

## 4) Run Multiple Tasks Once

Use `.env`:

```bash
RUN_ALL=false
EXPERIMENT_TASKS=silicon_valley_survival,code_archaeology,reverse_turing
```

Or task file (`tasks.txt`, one slug/id per line):

```bash
EXPERIMENT_TASK_FILE=tasks.txt
```

CLI override examples:

```bash
python runners/run_experiments.py --tasks silicon_valley_survival,reverse_turing
python runners/run_experiments.py --task-file tasks.txt
python runners/run_experiments.py --all
```

## 5) Failure Handling

Default behavior is continue-on-error:
- if one experiment fails, later experiments still run
- if one config YAML is broken, it is marked `config_error` and pipeline continues

`.env` knobs:

```bash
CONTINUE_ON_ERROR=true
MAX_API_RETRIES=2
RETRY_BACKOFF_SEC=2
```

If you want strict mode (stop immediately):

```bash
python runners/run_experiments.py --all --stop-on-error
```

## 6) Preview Website Locally

```bash
python -m http.server --directory site 4173
```

Open: `http://localhost:4173`

## Optional Playwright Browser Context

Enable in `.env`:

```bash
ENABLE_HEADLESS_BROWSER=true
BROWSER_BASE_URL=https://news.ycombinator.com
BROWSER_TIMEOUT_SEC=60
BROWSER_MAX_CHARS=3000
BROWSER_MAX_LINKS=8
BROWSER_WAIT_UNTIL=domcontentloaded
BROWSER_HEADLESS=true
BROWSER_REFRESH_EVERY_ROUND=true
BROWSER_ROUND_INTERVAL=1
BROWSER_REQUIRED=false
```

When enabled, each round can include a browser snapshot (title, body excerpt, links) injected into model context.

Per-experiment override in YAML is supported:

```yaml
browser:
  enabled: true
  url: https://example.com
  round_interval: 1
  max_chars: 3000
  max_links: 8
  required: false
```

## 7) Push to GitHub

```bash
git init
git add .
git commit -m "init: 230b experiment lab"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

## 8) GitHub Pages Deployment

This repo includes `.github/workflows/deploy-pages.yml`.

In GitHub:
1. Open repository settings.
2. Go to Pages.
3. Set source to GitHub Actions.
4. Push to `main`, workflow will deploy `site/`.

## 9) Remote Run via GitHub Actions

Workflow: `.github/workflows/run-experiments.yml`

Add repo secrets:
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY` (if required)
- `MODEL_NAME`

Then manually trigger `Run Experiments` in Actions.

## Notes

- Current evaluator is heuristic baseline only.
- For publish-grade benchmark, add task-specific evaluators in `evaluators/`.
