#!/usr/bin/env python3
"""Push the repository's JSON content into a Strapi instance.

Run this once, after creating the content types from strapi/schemas/. It is
idempotent: an entry whose slug already exists in Strapi is updated rather than
duplicated, so a failed run can simply be run again.

    export STRAPI_URL=https://your-strapi.example
    export STRAPI_TOKEN=...            # full-access API token
    python scripts/migrate_to_strapi.py --dry-run
    python scripts/migrate_to_strapi.py

Images are NOT uploaded. Strapi's media library needs multipart uploads and a
mapping back onto each entry, and most destination images are placeholders
anyway. Upload them through the Strapi admin UI and attach them to the entries
there.
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"

# Local directory -> (Strapi plural API id, natural key used for idempotency)
COLLECTIONS = [
    ("destinations", "destinations", "slug"),
    ("services", "services", "slug"),
    ("audiences", "audiences", "slug"),
    ("blog", "blog-posts", "slug"),
    ("testimonials", "testimonials", "name"),
    ("clients", "clients", "name"),
]

# Fields Strapi owns or that mean nothing to it. Media fields are skipped
# because this script does not upload files; the leading-underscore keys are
# editor notes that belong in the repo, not the CMS.
SKIP_FIELDS = {"card_image", "hero_image", "gallery", "photo", "logo", "partner_url"}


def request(method, url, token, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:  # nosec B310 - URL built from STRAPI_URL, validated in main()
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"\n  Strapi {exc.code} on {method} {url}\n  {detail}\n") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"\n  Cannot reach Strapi at {url}: {exc.reason}\n") from exc


def clean(record):
    """Strip media, editor notes and Strapi-managed keys."""
    return {
        key: value
        for key, value in record.items()
        if key not in SKIP_FIELDS and not key.startswith("_") and key != "id"
    }


def find_existing(base, plural, key, value, token):
    query = urllib.parse.urlencode({f"filters[{key}][$eq]": value, "pagination[pageSize]": 1})
    found = request("GET", f"{base}/api/{plural}?{query}", token)
    entries = found.get("data") or []
    return entries[0].get("id") if entries else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent and exit.")
    args = parser.parse_args()

    base = (os.getenv("STRAPI_URL") or "").rstrip("/")
    token = os.getenv("STRAPI_TOKEN") or ""
    if not base or not token:
        raise SystemExit("Set STRAPI_URL and STRAPI_TOKEN first. See STRAPI.md.")
    if not base.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise SystemExit("STRAPI_URL must use HTTPS (http is allowed only for localhost).")

    total = 0
    for folder, plural, natural_key in COLLECTIONS:
        directory = CONTENT / folder
        files = sorted(directory.glob("*.json")) if directory.exists() else []
        if not files:
            print(f"  {folder:<14} — nothing to migrate")
            continue

        print(f"  {folder:<14} -> {plural}  ({len(files)} file(s))")
        for path in files:
            record = clean(json.loads(path.read_text(encoding="utf-8")))
            key_value = record.get(natural_key)
            if not key_value:
                print(f"      skipped {path.name}: no '{natural_key}'")
                continue

            if args.dry_run:
                print(f"      would send {key_value} ({len(record)} fields)")
                total += 1
                continue

            existing = find_existing(base, plural, natural_key, key_value, token)
            if existing:
                request("PUT", f"{base}/api/{plural}/{existing}", token, {"data": record})
                print(f"      updated {key_value}")
            else:
                request("POST", f"{base}/api/{plural}", token, {"data": record})
                print(f"      created {key_value}")
            total += 1

    verb = "would migrate" if args.dry_run else "migrated"
    print(f"\n{verb} {total} entries.")
    if not args.dry_run:
        print(
            "\nNext: upload images in the Strapi media library and attach them to\n"
            "each entry, then set STRAPI_URL and STRAPI_TOKEN on the website so it\n"
            "reads from Strapi. The site keeps working from the JSON files until\n"
            "you do, and falls back to them if Strapi is ever unreachable."
        )


if __name__ == "__main__":
    sys.exit(main())
