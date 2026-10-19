# ETHPL Website — Progress & Handoff

The complete **ETHPL corporate travel & events** website (FastAPI + Jinja,
deploys on Vercel). This file is the resumable checklist, so work can be picked
up again anytime.

- **Repo:** `github.com/devansh3108-2/ethpl-website` (branch `main`)
- **Run locally:** `pip install -r requirements-dev.txt` then `uvicorn app:app --reload`
- **Tests:** `python -m pytest -q` — **325 passing**
- After editing anything in `static/`, mirror it: copy `static/` → `public/static/`
  (that mirror is what Vercel serves; the two must stay identical).

---

## Done

### Homepage
- **Two-photo hero** — two overlapping photo cards that gently float and slowly
  zoom (motion comes from the photos, not moving text). Photos come from an
  editable field; until set, a tidy "Your photo here" placeholder shows. All
  motion switches off under reduced-motion.
- **"What we offer in MICE"** — a four-pillar **M · I · C · E** grid with big
  watermark letters and event-type chips; educational tours and the à-la-carte
  desk linked beneath.
- **"Why choose ETHPL"** — a ticked checklist beside a branded forest panel.
- **Top navigation** — all links are one consistent weight, size and alignment.
- **Site-wide cursor** — a small 3D plane (travel theme), on every cursor.

### Admin (behind the signed admin login)
- **`/admin/appearance` — upload / replace the two hero photos** (with alt text
  and a live preview), no coding. Images are stored in the **same database that
  captures enquiries** and served from `/media/<key>`. With no database set, the
  page explains what to configure and the homepage keeps its placeholder.
- Removed a misleading "sample data" badge and a dead reset button; added a
  working **Sign out**.

### Platform (from the original plan — all in code, switch on with env vars)
- SEO: crawlable `robots.txt`, `sitemap.xml`, unique titles/descriptions,
  structured data (TravelAgency, Service, FAQ, TouristDestination, Breadcrumb).
- Speed: WebP images with sized `<picture>`, lazy-loading.
- **Lead capture**: enquiry form → database + email alert, with honest failure
  (never a fake "sent"). Leads inbox + CSV export in the admin.
- Strapi CMS integration (optional, code-complete), analytics hooks, favicons +
  social card, privacy/terms pages, and the destination / service / audience
  pages.

---

## To do (you / your team)

### 1. Go live on Vercel
1. **vercel.com → Add New → Project →** import **`ethpl-website`** → **Deploy**.
2. **Settings → Environment Variables:**

   | Variable | For | Where |
   | --- | --- | --- |
   | `DATABASE_URL` | enquiries **and** hero photos | Vercel → Storage → Postgres |
   | `SALES_EMAIL` + `RESEND_API_KEY` | emailing each enquiry | resend.com (free) |
   | `DEMO_ADMIN_PASSWORD` | admin password | you choose |
   | `ADMIN_SESSION_SECRET` | secures admin login | any long random string |
   | `SITE_BASE_URL` | SEO links | your domain, once pointed at Vercel |
   | `GA4_MEASUREMENT_ID`, `CLARITY_PROJECT_ID` | analytics (optional) | later |

3. **Redeploy** after setting the variables.

### 2. Content
- Upload two real hero photos at **`/admin/login` → Hero photos**.
- Add testimonials (`content/testimonials/`) and client logos
  (`content/clients/`) — only with written permission; never invent them.
- Replace placeholder destination photos with real ones.

### 3. Cleanup
- Delete the leftover branch `feat/hero-rotating-and-mice-sections` on the old
  repo: `github.com/AakashBhat1/ethpl-mice-catalogue/branches`.

---

## Notes
- Content lives in `content/*.json`. Brand colours come only from
  `static/css/theme.css` tokens (leaf green + bark brown, taken from the logo).
- Never put fake testimonials, client logos, statistics or certifications on the
  site — the code deliberately hides those sections until real values exist.
