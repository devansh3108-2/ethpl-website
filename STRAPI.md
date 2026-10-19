# Strapi admin panel — setup guide

This is the content editor for the ETHPL site. Once it is running, you add and
edit destinations, services, blog posts, testimonials and client logos through
forms in a browser, with no code.

**Nothing here is required for the site to work.** The site reads its content
from JSON files in this repository and will keep doing so indefinitely. Strapi
is an upgrade to how that content is *edited*, not a dependency of the site.

---

## Before you start: what this costs

You chose Strapi over a Git-based CMS. It is the better editor, and it is the
more expensive and more involved option. Worth knowing up front:

| | Cost | Who maintains it |
| --- | --- | --- |
| **Strapi Cloud** | Paid monthly, billed by Strapi | Strapi |
| **Self-hosted** (Railway, Render, a VPS) | Roughly $5–15/month for the server plus a Postgres database | You |

Strapi is a Node.js application with its own database. It cannot run inside
this repository — this site deploys as a single Python serverless function on
Vercel. Strapi has to live somewhere of its own.

You also take on upgrades and security patching if you self-host. Strapi ships
security releases, and an unpatched CMS with an admin login is a real target.

**If that is unwelcome, say so before going further.** The alternative — a
Git-based CMS such as Sveltia or Decap — is free, needs no server, edits the
same JSON files directly, and makes every change a revertible commit. It is a
plainer editor. Switching is cheap now and expensive after the content has
moved.

---

## 1. Run Strapi

Either sign up for Strapi Cloud, or deploy Strapi yourself:

```bash
npx create-strapi-app@latest ethpl-cms --quickstart
```

For anything other than local experimentation, point it at Postgres rather than
the default SQLite — the same reason the website uses Postgres: most hosting
platforms have a disposable filesystem and will silently lose an SQLite file.

Create your admin account at `/admin` on the Strapi instance.

## 2. Create the content types

`strapi/schemas/` in this repository holds a schema file for each collection:

| File | Collection |
| --- | --- |
| `destination.json` | Destinations |
| `service.json` | Services |
| `audience.json` | Audiences (corporates, schools, NGOs) |
| `testimonial.json` | Testimonials |
| `client.json` | Client logos |
| `blog-post.json` | Blog posts |

For a self-hosted Strapi, copy each one into your Strapi project at
`src/api/<name>/content-types/<name>/schema.json` and restart. Strapi picks
them up on boot.

On Strapi Cloud, recreate them in the Content-Type Builder using these files as
the reference. Field names must match **exactly** — a typo means the website
sees a field as missing and quietly falls back to the local JSON for that
collection, which is easy to miss because the site still looks fine.

## 3. Create an API token

In Strapi: **Settings → API Tokens → Create new API Token**.

- Token type: **Read-only** for the website
- Save the token immediately — Strapi shows it once

For the migration script in step 4 you need a **Full access** token. Delete
that one afterwards; the website only ever needs read access.

## 4. Move the existing content in

```bash
export STRAPI_URL=https://your-strapi.example
export STRAPI_TOKEN=<full-access token>

python scripts/migrate_to_strapi.py --dry-run   # check what it will send
python scripts/migrate_to_strapi.py             # actually send it
```

The script is idempotent — it updates an entry whose slug already exists rather
than creating a duplicate — so a failed run can just be run again.

It does **not** upload images. Strapi's media library needs multipart uploads,
and most destination images are placeholders anyway (see `PROGRESS.md`). Upload
real photographs through the Strapi admin and attach them to each entry.

## 5. Point the website at Strapi

Set these on the website's hosting (Vercel → Settings → Environment Variables):

| Variable | Value |
| --- | --- |
| `STRAPI_URL` | `https://your-strapi.example` — no trailing slash |
| `STRAPI_TOKEN` | the **read-only** token |

Redeploy. The site now reads content from Strapi.

Leave both unset and the site reads the JSON files, exactly as it does today.

---

## What happens when Strapi goes down

**The website stays up.** Every read falls back to the JSON files in this
repository, which are a complete copy of the content. The worst case is that
the site serves slightly stale content until Strapi returns.

This is deliberate, and it is why the JSON files are not deleted after
migrating. They are the safety net. Keep them roughly in step with Strapi —
re-exporting them periodically is a sensible habit.

Responses are cached for 60 seconds, so a publish in Strapi appears on the site
within about a minute, and one page render does not make a dozen HTTP calls.

## What Strapi does not do

- **It does not show leads.** Enquiries live in the website's own Postgres
  database and are read at `/admin/leads`, behind the existing password. That
  page also exports CSV.
- **It is not a page builder.** You edit content in defined fields. Layout
  stays in the site's templates, which is what keeps the design consistent.

## Keeping it safe

- Use a **read-only** token for the website. A full-access token in a web
  app's environment is a compromise waiting to happen.
- Delete the full-access migration token once step 4 is done.
- Restrict public permissions in **Settings → Roles → Public** to nothing. The
  site authenticates with its token; the public role needs no access at all.
- Apply Strapi security updates. This is the ongoing cost of self-hosting.
