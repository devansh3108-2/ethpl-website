# Deploy the ETHPL demo to Vercel

1. In Vercel, create a project from this repository and set its **Root Directory** to
   `ethpl-mice-catalogue` (or run these commands from that directory).
2. Add these Production and Preview environment variables:
   - `DEMO_ADMIN_PASSWORD`: the private demo password.
   - `ADMIN_SESSION_SECRET`: a unique high-entropy secret (generate at least 32 random bytes).
   - `APP_ENV`: `production`.
   - `REDIRECT_BASE_URL`: `https://www.ethpl.com`.
   - `REDIRECT_ALLOWED_HOSTS`: `www.ethpl.com,ethpl.com`.
3. **Leave `RFP_DATABASE_PATH` unset. Never point it at `/tmp` on Vercel:** function
   storage is disposable, so successful-looking submissions would be lost. With the
   variable unset, the API returns `503` and the browser honestly preserves the form
   and offers the pre-filled email fallback. Persistent online lead capture requires a
   managed database or a host with persistent storage.
4. Install Vercel CLI 48.1.8 or newer, then create a preview:
   `vercel deploy`.
5. Verify `/`, `/destinations`, `/hotels`, `/packages`, `/estimator`, `/blog`, one blog post,
   `/robots.txt`, and `/admin`. Confirm `/static/css/theme.css` loads from Vercel's CDN;
   anonymous `/admin` redirects to login; wrong credentials fail; correct credentials
   open every admin screen; and `/robots.txt` contains `Disallow: /`.
6. After the preview passes, publish the exact tested deployment with
   `vercel promote <preview-url>`. Do not attach a custom ETHPL domain to this demo.

The committed `public/static/` directory is the Vercel CDN copy of `static/`. Before a
future deploy, run the test suite; `tests/test_vercel_deploy.py` fails if the two trees drift.
