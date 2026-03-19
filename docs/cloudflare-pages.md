# Cloudflare Pages Deployment (Optional)

This repo already supports GitHub Pages by default.
If you also want Cloudflare Pages:

1. Create a Pages project in Cloudflare dashboard.
2. Connect this GitHub repository.
3. Set build command to:
   ```bash
   pip install -r requirements.txt && python scripts/run_pipeline.py --skip-run
   ```
4. Set output directory to:
   ```bash
   site
   ```
5. Ensure `results/metrics/*.json` exists in the repository.

For direct CLI deploy:
```bash
npx wrangler pages deploy site --project-name <your-project-name>
```
