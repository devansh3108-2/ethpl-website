# ETHPL MICE & Corporate Travel Catalogue

A modern, high-performance information catalogue for **MICE (Meetings, Incentives,
Conferences, Exhibitions)** and corporate group travel. ETHPL curates the corporate
catalogue and handles proposal requests; all retail bookings and payments are
operated by the official travel partner, **Holiday My Planet** (holidaymyplanet.com).

> **Status:** preview build. Not yet attached to a production ETHPL domain.
> Set `SITE_BASE_URL` and the lead-capture variables below before launch.

---

## Stack

- **FastAPI** + **Jinja2** server-rendered templates
- **Vanilla JS** catalogue rendering and CTA routing (no build step)
- **CSS custom-property token system** (primitive → semantic → alias layers)
- Deployed as a single **Vercel** Python serverless function (`api/index.py`)

---

## Quickstart

```powershell
# 1. Create / activate the virtual environment
python -m venv venv
venv\Scripts\Activate.ps1

# 2. Install exact dependencies
python -m pip install -r requirements-dev.txt

# 3. Run the dev server
python -m uvicorn app:app --reload --port 8000
```

Open **http://127.0.0.1:8000**:

| Route            | Page                                             |
| ---------------- | ------------------------------------------------ |
| `/`              | Homepage: services, destinations, why choose us  |
| `/destinations`  | Curated corporate destinations                   |
| `/mice`          | Corporate MICE & events desk                     |
| `/estimator`     | Retired — returns `410 Gone`                     |
| `/packages`, `/hotels` | Retired — `301` to `/destinations`         |
| `/blog`, `/blog/{slug}` | Editorial articles                        |
| `/services/{id}` | Consular / holiday service desks                 |
| `/privacy`, `/terms` | Legal pages (interim text, pending review)   |
| `/thank-you`     | Post-enquiry page for conversion tracking        |
| `/sitemap.xml`, `/robots.txt` | Crawler surfaces                    |
| `/admin`         | Redirects to the leads inbox                     |
| `/admin/leads`   | Enquiries from the lead store (password-gated)   |
| `/admin/leads.csv` | CSV export of enquiries                        |

---

## CTA routing

**Every primary CTA opens the on-site enquiry form.** Destination cards open it
pre-filled with that destination. The outbound `CTA_TARGETS` map that used to
send package and venue buttons to the partner domain was removed — each of
those clicks was a lost lead.

The partner (Holiday My Planet) keeps one footer disclosure and a secondary
"self-serve" link on the two service pages. Those links carry UTM parameters
and a test enforces that no other partner link appears on the homepage or on
destination cards.

---

## Configuration (environment variables)

### Lead capture (set these first — without them enquiries are lost)

| Variable            | Purpose                                                        |
| ------------------- | -------------------------------------------------------------- |
| `DATABASE_URL`      | **Postgres connection string** (Neon / Supabase). This is how leads persist in production. Takes precedence over `RFP_DATABASE_PATH`. |
| `SALES_EMAIL`       | Inbox that receives an alert for every enquiry.                |
| `RESEND_API_KEY`    | Resend API key. Preferred transport when set.                  |
| `SMTP_HOST`         | SMTP server, used when `RESEND_API_KEY` is absent.             |
| `SMTP_PORT`         | SMTP port (default `587`, STARTTLS).                           |
| `SMTP_USER`         | SMTP username, if the server requires auth.                    |
| `SMTP_PASSWORD`     | SMTP password, if the server requires auth.                    |
| `LEAD_FROM_EMAIL`   | From address on alerts (default `enquiries@ethpl.com`).         |
| `RFP_DATABASE_PATH` | SQLite path for **local development only**. Do not set on Vercel — the filesystem there is disposable. |

How `/api/rfp` behaves, by configuration:

| Database | Sales email | Result |
| --- | --- | --- |
| reachable | configured | Lead stored **and** emailed → `201` |
| reachable | not configured | Lead stored → `201`. No alert, so nobody knows it arrived until someone looks |
| **unreachable** | configured | Lead **emailed anyway** → `201`, and the email is clearly marked as the only record |
| unreachable | not configured | `503`. The visitor is told honestly that it failed |
| not configured | not configured | `503` |

A submission is only reported as successful when something actually recorded
it. Do not change that: telling someone their enquiry was sent when nothing
captured it is the worst possible failure for this business.

Email sending never raises — a mail outage cannot lose a lead that is already
in the database. Retries are de-duplicated by the `Idempotency-Key` header, and
a retry does not re-email the sales team.

### Everything else

| Variable                | Purpose                                                        |
| ----------------------- | -------------------------------------------------------------- |
| `SITE_BASE_URL`         | Absolute origin used by canonical tags and `sitemap.xml`. **Set this to the real domain once it is live** (defaults to the vercel.app URL). |
| `STRAPI_URL`            | Strapi instance origin. Unset = content is read from `content/*.json`, which is a fully supported mode. See [`STRAPI.md`](./STRAPI.md). |
| `STRAPI_TOKEN`          | Strapi **read-only** API token. Both this and `STRAPI_URL` must be set for Strapi to be used. |
| `DEMO_ADMIN_PASSWORD`   | Admin password. **Admin returns 503 until this is set.**       |
| `ADMIN_SESSION_SECRET`  | HMAC signing key for admin sessions (32+ random bytes).        |
| `APP_ENV`               | `production` marks the admin cookie `Secure`.                  |
| `REDIRECT_BASE_URL`     | Legacy `/redirect` base host (`https://www.ethpl.com`).        |
| `REDIRECT_ALLOWED_HOSTS`| Allow-list for the legacy redirect.                            |
| `TRUST_PROXY_HEADERS`   | `true` only behind a trusted proxy that rewrites forwarding headers. |
| `GA4_MEASUREMENT_ID`    | Google Analytics 4 ID (`G-XXXXXXXXXX`). Unset = GA4 does not load at all. |
| `CLARITY_PROJECT_ID`    | Microsoft Clarity project ID. Unset = Clarity does not load at all. |
| `RFP_RATE_LIMIT`        | Submissions allowed per IP per window (default `5`).           |
| `RFP_RATE_WINDOW_SECONDS` | Rate-limit window in seconds (default `60`).                 |

Admin is **off** unless both `DEMO_ADMIN_PASSWORD` and `ADMIN_SESSION_SECRET`
are present; otherwise every `/admin*` route returns `503`.

### Content editing

Content is read from `content/*.json` by default. Set `STRAPI_URL` and
`STRAPI_TOKEN` to read from a Strapi CMS instead — the JSON files then act as a
fallback, so a Strapi outage cannot take the site down. Setup steps are in
[`STRAPI.md`](./STRAPI.md).

The localStorage demo admin was removed: its edits saved only to the editor's
own browser and were never visible to a visitor.

---

## Testing & security

```bash
python -m pytest -q                          # full suite
python -m bandit -r app.py api services.py   # static security scan
python -m pip_audit -r requirements.txt      # dependency advisories
```

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.12 and 3.13, plus
Bandit and pip-audit, on every push/PR and weekly.

---

## Deployment

See [`DEPLOY.md`](./DEPLOY.md). In short: import the repo into Vercel, set the
**Root Directory** to `ethpl-mice-catalogue` if it is a subfolder, add the
environment variables above, and deploy. `public/static/` is the CDN mirror of
`static/` — `tests/test_vercel_deploy.py` fails if the two trees drift, so run the
suite before every deploy.

---

## Structure

```
ethpl-mice-catalogue/
├── api/index.py           # Vercel ASGI entry (imports app)
├── app.py                 # FastAPI app: routes, admin auth, RFP API
├── services.py            # Service-desk content/logic
├── schemas.py             # Pydantic models
├── config.py              # Settings
├── content/site.json      # Editable catalogue / copy content
├── templates/             # Jinja2 templates (base, index, hotels, packages, …)
├── static/                # Source CSS / JS / images
├── public/static/         # Byte-identical CDN mirror served by Vercel
├── scripts/               # Maintenance scripts
├── vercel.json            # Vercel function + rewrite config
└── tests/                 # pytest suite
```
