import os
import csv
import io
import json
import logging
import re
import base64
import hashlib
import hmac
import html
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from glob import glob
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Depends, Form, Query, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.concurrency import run_in_threadpool
from schemas import RFPPayload
from services import (
    LEAD_LIST_COLUMNS,
    build_content_repository,
    ContentError,
    ContentRepository,
    EmailNotifier,
    FixedWindowRateLimiter,
    LeadStoreUnavailable,
    build_lead_repository,
    new_lead_reference,
    build_site_asset_store,
    AssetStoreUnavailable,
    HERO_PHOTO_KEYS,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
)
from config import AppSettings

logger = logging.getLogger(__name__)

# Base directory for resolution
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
CONTENT_DIR = os.path.join(BASE_DIR, "content")
BLOG_DIR = os.path.join(CONTENT_DIR, "blog")
# Strapi when STRAPI_URL and STRAPI_TOKEN are set, local JSON files otherwise.
# Both are fully supported: a Strapi outage falls back to the files rather than
# taking the public site down.
content_repository = build_content_repository(CONTENT_DIR)
STRAPI_URL = os.getenv("STRAPI_URL", "")
rfp_rate_limiter = FixedWindowRateLimiter()

# Configurable redirection URL for the future primary booking portal
REDIRECT_BASE_URL = os.getenv("REDIRECT_BASE_URL", "https://www.ethpl.com")
ADMIN_COOKIE_NAME = "ethpl_admin_session"
ADMIN_SESSION_TTL_SECONDS = 8 * 60 * 60

# Absolute origin this site is served from. Canonical URLs, Open Graph tags and
# sitemap entries must be absolute, so they cannot be derived from a relative
# path alone. Set SITE_BASE_URL to the real domain once it is pointed at Vercel.
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://ethpl-mice-catalogue.vercel.app").rstrip("/")

# Analytics load only when an ID is configured. Unset means no third-party
# request at all, which is the right default for local development and for a
# site that has not yet decided to measure.
GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID", "")
CLARITY_PROJECT_ID = os.getenv("CLARITY_PROJECT_ID", "")

# Routes retired in Phase 1d. Packages and Venues collapsed into Destinations;
# both keep a permanent redirect so existing links and any indexed URLs survive.
RETIRED_ROUTE_REDIRECTS = {
    "/packages": "/destinations",
    "/hotels": "/destinations",
}


# Where each section sits in the trail. A page passes `breadcrumb_trail` for
# anything deeper than its section landing page.
BREADCRUMB_SECTIONS = {
    "services": ("Services", "/services"),
    "destinations": ("Destinations", "/destinations"),
    "who-we-serve": ("Who we serve", "/who-we-serve"),
    "blog": ("Guides", "/blog"),
    "mice": ("MICE Desk", "/mice"),
    "privacy": ("Privacy Policy", "/privacy"),
    "terms": ("Terms & Conditions", "/terms"),
}


def build_breadcrumbs(active_page: str, trail=None):
    """Home → section → page.

    Returns a single entry for the homepage, which base.html then declines to
    render: a one-item BreadcrumbList is not valid structured data and Google
    ignores it.
    """
    crumbs = [{"name": "Home", "path": "/"}]
    section = BREADCRUMB_SECTIONS.get(active_page)
    if section:
        crumbs.append({"name": section[0], "path": section[1]})
    for name, path in (trail or []):
        crumbs.append({"name": name, "path": path})
    return crumbs


def site_context(active_page: str, **extra) -> dict:
    """Context every public page needs: brand, year, canonical URL, origin.

    Brand strings come from content/site.json so there is one source of truth —
    templates must not hard-code the name or tagline.
    """
    brand = content_repository.brand()
    context = {
        "active_page": active_page,
        "brand": brand,
        "redirect_base_url": REDIRECT_BASE_URL,
        "site_base_url": SITE_BASE_URL,
        "current_year": datetime.now(timezone.utc).year,
        "ga4_id": GA4_MEASUREMENT_ID,
        "clarity_id": CLARITY_PROJECT_ID,
        "breadcrumbs": build_breadcrumbs(active_page, extra.pop("breadcrumb_trail", None)),
        # Footer destination links are driven by the content files so they can
        # never again point at a route that has been removed.
        "footer_destinations": content_repository.featured_destinations()[:5],
        # The enquiry modal lives in base.html on every page, so its destination
        # dropdown is populated here rather than per route.
        "rfp_destinations": content_repository.all_destinations(),
        # Nav menus are built from content, so adding a service or audience file
        # puts it in the menu without a template edit.
        "nav_services": content_repository.all_services(),
        "nav_audiences": content_repository.all_audiences(),
    }
    context.update(extra)
    return context

def validated_redirect_base_url(value: str | None = None) -> str:
    value = value or os.getenv("REDIRECT_BASE_URL", "https://www.ethpl.com")
    parsed = urlsplit(value)
    allowed_hosts = {
        host.strip().lower()
        for host in os.getenv("REDIRECT_ALLOWED_HOSTS", "www.ethpl.com,ethpl.com,www.holidaymyplanet.com,holidaymyplanet.com").split(",")
        if host.strip()
    }
    development = os.getenv("APP_ENV", "development").lower() == "development"
    localhost = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError("REDIRECT_BASE_URL must not include credentials, a query, or a fragment")
    if parsed.scheme != "https" and not (development and localhost and parsed.scheme == "http"):
        raise ValueError("REDIRECT_BASE_URL must use HTTPS")
    if not parsed.hostname or (parsed.hostname.lower() not in allowed_hosts and not (development and localhost)):
        raise ValueError("REDIRECT_BASE_URL host is not allowed")
    return value.rstrip("/")


@asynccontextmanager
async def lifespan(application: FastAPI):
    validated_redirect_base_url()
    yield


app = FastAPI(
    title="ETHPL MICE & Corporate Travel Catalogue",
    description="Interactive Travel Information & Budget Catalogue for MICE Clients",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files for local development. On Vercel the static/ tree is
# excluded from the function bundle (served from the CDN via public/ instead),
# so StaticFiles would raise at import — guard the mount on the dir existing.
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.state.content_repository = content_repository

# Mount Jinja2 templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def asset_url(relative_path: str) -> str:
    """Static URL carrying an mtime cache-buster so edited assets reload during demos."""
    try:
        version = int(os.path.getmtime(os.path.join(STATIC_DIR, relative_path)))
    except OSError:
        version = 0
    return f"/static/{relative_path}?v={version}"


templates.env.globals["asset_url"] = asset_url


@app.middleware("http")
async def protect_admin_indexing(request: Request, call_next):
    if request.url.path == "/api/rfp":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > 16_384:
                    return JSONResponse(
                        status_code=413,
                        content={"ok": False, "error": {"code": "body_too_large", "message": "Request body is too large"}},
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"ok": False, "error": {"code": "invalid_content_length", "message": "Invalid request"}})
    response = await call_next(request)
    if request.url.path == "/admin" or request.url.path.startswith("/admin/"):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    if request.url.path != "/api/rfp":
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    fields = {}
    for error in exc.errors():
        location = error.get("loc", ())
        field = str(location[-1]) if location else "request"
        fields[field] = error.get("msg", "Invalid value")
    return JSONResponse(
        status_code=422,
        content={"ok": False, "error": {"code": "validation_failed", "message": "Validation failed"}, "fields": fields},
    )


# ==========================================
# HELPER UTILITIES
# ==========================================

def render_markdown(text: str) -> str:
    """Render the deliberately small Markdown subset after escaping raw HTML."""
    if not text:
        return ""
    lines = text.split('\n')
    html_lines = []
    in_list = False
    list_type = None

    def inline(value: str) -> str:
        value = html.escape(value, quote=True)
        value = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', value)
        return re.sub(r'\*(.*?)\*', r'<em>\1</em>', value)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
                list_type = None
            continue

        if stripped.startswith('### '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append(f'<h3>{inline(stripped[4:])}</h3>')
        elif stripped.startswith('## '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append(f'<h2>{inline(stripped[3:])}</h2>')
        elif stripped.startswith('# '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
            html_lines.append(f'<h1>{inline(stripped[2:])}</h1>')
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list or list_type != 'ul':
                if in_list:
                    html_lines.append(f'</{list_type}>')
                html_lines.append('<ul>')
                in_list = True
                list_type = 'ul'
            item = inline(stripped[2:])
            html_lines.append(f'<li>{item}</li>')
        elif len(stripped) > 3 and stripped[0].isdigit() and stripped[1:3] == '. ':
            if not in_list or list_type != 'ol':
                if in_list:
                    html_lines.append(f'</{list_type}>')
                html_lines.append('<ol>')
                in_list = True
                list_type = 'ol'
            item = inline(stripped[3:])
            html_lines.append(f'<li>{item}</li>')
        elif stripped.startswith('> '):
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
                list_type = None
            q = inline(stripped[2:])
            html_lines.append(f'<blockquote>{q}</blockquote>')
        else:
            if in_list:
                html_lines.append(f'</{list_type}>')
                in_list = False
                list_type = None
            p = inline(stripped)
            html_lines.append(f'<p>{p}</p>')

    if in_list:
        html_lines.append(f'</{list_type}>')

    return '\n'.join(html_lines)


def load_all_blog_posts(repository=None):
    return (repository or content_repository).all_posts()


def load_blog_post_by_slug(slug: str, repository=None):
    data = (repository or content_repository).by_slug(slug)
    if data:
        data['body_html'] = render_markdown(data.get('body_markdown', ''))
    return data


# ==========================================
# PUBLIC PAGE ROUTES
# ==========================================

def resolved_why_us(repo):
    """Benefit points with live counts substituted in.

    The destination figure is interpolated from the content files rather than
    typed into copy, because the hero, the admin panel and the enquiry dropdown
    previously each carried a different hard-coded number.
    """
    destination_count = len(repo.all_destinations())
    points = []
    for point in repo.why_us():
        resolved = dict(point)
        resolved["description"] = resolved.get("description", "").replace(
            "{destination_count}", str(destination_count)
        )
        points.append(resolved)
    return points


# ── Editable hero photos ────────────────────────────────────────────────────
# The two homepage hero slots can be replaced from /admin/appearance. Uploaded
# photos live in the lead database and are served from /media/<key>. A short
# cache keeps the homepage from making a database call on every single render.
_HERO_PHOTO_CACHE = {"at": 0.0, "meta": {}}
_HERO_PHOTO_CACHE_TTL = 30.0


def _invalidate_hero_photo_cache():
    _HERO_PHOTO_CACHE["at"] = 0.0


def _hero_photo_meta() -> dict:
    now = time.time()
    if now - _HERO_PHOTO_CACHE["at"] < _HERO_PHOTO_CACHE_TTL:
        return _HERO_PHOTO_CACHE["meta"]
    store = build_site_asset_store()
    meta = {}
    if store is not None:
        try:
            meta = store.list_meta()
        except AssetStoreUnavailable:
            # The database is down. The homepage falls back to the content
            # defaults rather than failing over an optional photo.
            meta = {}
    _HERO_PHOTO_CACHE["at"] = now
    _HERO_PHOTO_CACHE["meta"] = meta
    return meta


def _hero_photo_version(updated_at: str) -> str:
    return hashlib.sha1(updated_at.encode()).hexdigest()[:8]


def _home_with_hero_photos(home: dict) -> dict:
    """Overlay admin-uploaded hero photos onto the content.

    Each slot defaults to whatever content/home.json holds (usually empty → a
    branded placeholder). A photo uploaded through the admin overrides its slot
    with a /media/<key> URL. A copy is returned so the content cache is never
    mutated.
    """
    hero = home.get("hero") or {}
    photos = [dict(photo) for photo in (hero.get("photos") or [])][:2]
    while len(photos) < 2:
        photos.append({"src": "", "alt": ""})

    meta = _hero_photo_meta()
    for index, key in enumerate(HERO_PHOTO_KEYS):
        info = meta.get(key)
        if info:
            version = _hero_photo_version(info.get("updated_at", ""))
            photos[index] = {
                "src": f"/media/{key}?v={version}",
                "alt": info.get("alt") or photos[index].get("alt", ""),
            }

    return {**home, "hero": {**hero, "photos": photos}}


@app.get("/media/{key}")
async def media_asset(key: str):
    """Serve an admin-uploaded site image (currently the two hero photos).

    Public and heavily cached: the URL carries a version query string that
    changes whenever the photo is replaced, so a long immutable cache is safe
    and a new upload is still picked up at once.
    """
    if key not in HERO_PHOTO_KEYS:
        raise HTTPException(status_code=404, detail="Not found")
    store = build_site_asset_store()
    if store is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        found = store.get(key)
    except AssetStoreUnavailable:
        raise HTTPException(status_code=503, detail="Image storage is unavailable")
    if not found:
        raise HTTPException(status_code=404, detail="Not found")
    content_type, data = found
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    repo = request.app.state.content_repository
    destinations = repo.all_destinations()

    # Eight tiles per region, so each tab fills a 4-column grid twice over
    # without the page carrying all 21 twice.
    def by_region(region):
        return [d for d in destinations if d.get("region") == region][:8]

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=site_context(
            "home",
            home=_home_with_hero_photos(repo.home()),
            stats=repo.home_stats(destination_count=len(destinations)),
            services=repo.all_services(),
            testimonials=repo.testimonials(),
            clients=repo.clients(),
            home_destinations=by_region("india") + by_region("international"),
            why_us=resolved_why_us(repo),
            featured_destinations=repo.featured_destinations(),
            destination_count=len(destinations),
            canonical_path="/",
        ),
    )


@app.get("/destinations", response_class=HTMLResponse)
async def destinations_page(request: Request):
    repo = request.app.state.content_repository
    destinations = repo.all_destinations()
    featured = repo.featured_destinations()
    return templates.TemplateResponse(
        request=request,
        name="destinations.html",
        context=site_context(
            "destinations",
            destinations=destinations,
            featured_destinations=featured,
            canonical_path="/destinations",
        ),
    )


@app.get("/destinations/{slug}", response_class=HTMLResponse)
async def destination_detail_page(slug: str, request: Request):
    """One indexable page per destination.

    These are the pages that can rank for "corporate offsite goa" and similar,
    which the single /destinations index never could.
    """
    repo = request.app.state.content_repository
    try:
        destination = repo.destination_by_slug(slug)
    except ContentError:
        raise HTTPException(status_code=503, detail="Destination content is temporarily unavailable")
    if not destination:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context=site_context("destinations"),
            status_code=404,
        )
    related = [
        other for other in repo.all_destinations()
        if other.get("slug") != slug and other.get("region") == destination.get("region")
    ][:3]
    return templates.TemplateResponse(
        request=request,
        name="destination_detail.html",
        context=site_context(
            "destinations",
            destination=destination,
            related_destinations=related,
            breadcrumb_trail=[(destination.get("name", slug), f"/destinations/{slug}")],
            canonical_path=f"/destinations/{slug}",
        ),
    )


@app.get("/services", response_class=HTMLResponse)
async def services_index_page(request: Request):
    repo = request.app.state.content_repository
    return templates.TemplateResponse(
        request=request,
        name="services_index.html",
        context=site_context(
            "services",
            services=repo.all_services(),
            canonical_path="/services",
        ),
    )


@app.get("/who-we-serve/{slug}", response_class=HTMLResponse)
async def audience_page(slug: str, request: Request):
    """Corporates, schools and colleges, NGOs.

    Until these existed the entire site spoke only to corporates, so the other
    named target clients had no page that addressed them.
    """
    repo = request.app.state.content_repository
    try:
        audience = repo.audience_by_slug(slug)
    except ContentError:
        raise HTTPException(status_code=503, detail="Content is temporarily unavailable")
    if not audience:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context=site_context("who-we-serve"),
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="audience.html",
        context=site_context(
            "who-we-serve",
            audience=audience,
            services=repo.all_services(),
            breadcrumb_trail=[(audience.get("name", slug), f"/who-we-serve/{slug}")],
            canonical_path=f"/who-we-serve/{slug}",
        ),
    )


# Short, memorable aliases for the audience pages — these are the URLs that go
# on a business card or in an email signature.
AUDIENCE_ALIASES = {"/corporates": "corporates", "/schools-colleges": "schools-colleges", "/ngos": "ngos"}


@app.get("/corporates", include_in_schema=False)
async def corporates_alias():
    return RedirectResponse(url="/who-we-serve/corporates", status_code=301)


@app.get("/schools-colleges", include_in_schema=False)
async def schools_alias():
    return RedirectResponse(url="/who-we-serve/schools-colleges", status_code=301)


@app.get("/ngos", include_in_schema=False)
async def ngos_alias():
    return RedirectResponse(url="/who-we-serve/ngos", status_code=301)


@app.get("/services/{service_id}", response_class=HTMLResponse)
async def service_detail_page(service_id: str, request: Request):
    """Serves both collections behind one URL prefix.

    The six MICE services are checked first. The two legacy partner desks
    (/services/visa, /services/holidays) remain so their indexed URLs and
    inbound links keep working.
    """
    repo = request.app.state.content_repository
    try:
        mice_service = repo.service_by_slug(service_id)
    except ContentError:
        raise HTTPException(status_code=503, detail="Service content is temporarily unavailable")
    if mice_service:
        return templates.TemplateResponse(
            request=request,
            name="service_detail.html",
            context=site_context(
                "services",
                service=mice_service,
                services=repo.all_services(),
                breadcrumb_trail=[(mice_service.get("name", service_id), f"/services/{service_id}")],
                canonical_path=f"/services/{service_id}",
            ),
        )

    service = repo.service_by_id(service_id)
    if not service:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context=site_context("services"),
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="service.html",
        context=site_context(
            "services",
            service=service,
            breadcrumb_trail=[(service.get("name", service_id), f"/services/{service_id}")],
            canonical_path=f"/services/{service.get('slug', service_id)}",
        ),
    )


@app.get("/mice", response_class=HTMLResponse)
async def mice_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="mice.html",
        context=site_context("mice", canonical_path="/mice"),
    )


# Retired in Phase 1d: Packages and Venues collapsed into Destinations. A 301
# keeps link equity and stops existing bookmarks and indexed URLs 404-ing.
@app.get("/hotels", include_in_schema=False)
async def retired_hotels_page():
    return RedirectResponse(url=RETIRED_ROUTE_REDIRECTS["/hotels"], status_code=301)


@app.get("/packages", include_in_schema=False)
async def retired_packages_page():
    return RedirectResponse(url=RETIRED_ROUTE_REDIRECTS["/packages"], status_code=301)


@app.get("/thank-you", response_class=HTMLResponse)
async def thank_you_page(request: Request):
    """Post-submission page.

    Exists so an ad or analytics conversion can fire on a distinct page view.
    Counting conversions off an XHR response is unreliable, and Google Ads
    needs a destination URL to attribute spend against. Deliberately noindex:
    useful to a visitor who just submitted, worthless in search results.
    """
    return templates.TemplateResponse(
        request=request,
        name="thank_you.html",
        context=site_context("thank-you"),
    )


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    repo = request.app.state.content_repository
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context=site_context(
            "privacy",
            page=repo.legal_page("privacy"),
            canonical_path="/privacy",
        ),
    )


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    repo = request.app.state.content_repository
    return templates.TemplateResponse(
        request=request,
        name="legal.html",
        context=site_context(
            "terms",
            page=repo.legal_page("terms"),
            canonical_path="/terms",
        ),
    )


@app.get("/estimator", response_class=HTMLResponse)
async def estimator_page(request: Request):
    return HTMLResponse(
        status_code=410,
        content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>410 Gone | Budget Planner Retired</title>
  <link rel="stylesheet" href="/static/css/theme.css">
  <link rel="stylesheet" href="/static/css/layout.css">
  <link rel="stylesheet" href="/static/css/components.css">
</head>
<body style="display:flex; align-items:center; justify-content:center; min-height:100vh; background:var(--stone-50); font-family:var(--font-body); text-align:center; padding:20px;">
  <div class="panel" style="max-width:520px; padding:32px;">
    <h1 style="color:var(--stone-900); font-size:1.8rem; margin-bottom:12px;">Budget Planner Retired</h1>
    <p style="color:var(--stone-600); margin-bottom:24px; line-height:1.6;">
      The standalone budget estimator has been retired. Please browse our curated destinations or request a tailored corporate proposal from our MICE desk.
    </p>
    <div style="display:flex; gap:12px; justify-content:center;">
      <a href="/destinations" class="btn btn-primary">Browse Destinations</a>
      <a href="/" class="btn btn-outline">Return to Home</a>
    </div>
  </div>
</body>
</html>""",
    )


@app.get("/blog", response_class=HTMLResponse)
async def blog_list_page(request: Request):
    posts = load_all_blog_posts(request.app.state.content_repository)
    return templates.TemplateResponse(
        request=request,
        name="blog_list.html",
        context=site_context("blog", posts=posts, canonical_path="/blog"),
    )


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_detail_page(slug: str, request: Request):
    try:
        post = load_blog_post_by_slug(slug, request.app.state.content_repository)
    except ContentError:
        raise HTTPException(status_code=503, detail="Blog content is temporarily unavailable")
    if not post:
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context=site_context("blog"),
            status_code=404
        )
    return templates.TemplateResponse(
        request=request,
        name="blog_post.html",
        context=site_context(
            "blog",
            post=post,
            breadcrumb_trail=[(post.get("title", slug), f"/blog/{slug}")],
            canonical_path=f"/blog/{slug}",
        ),
    )


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Allow crawlers on the public site; keep them out of admin and the API.

    This previously served a blanket `Disallow: /`, which made the site
    unrankable — nothing else in the SEO plan can work until crawlers are let in.
    """
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /api/\n"
        f"\nSitemap: {SITE_BASE_URL}/sitemap.xml\n"
    )


def _public_sitemap_entries(repo) -> list[tuple[str, str]]:
    """(path, changefreq) for every indexable public URL.

    Retired routes and admin are deliberately absent: a sitemap that lists a
    redirect or a noindex page wastes crawl budget and triggers Search Console
    warnings.
    """
    entries: list[tuple[str, str]] = [
        ("/", "weekly"),
        ("/mice", "monthly"),
        ("/services", "monthly"),
        ("/destinations", "weekly"),
        ("/blog", "weekly"),
        ("/privacy", "yearly"),
        ("/terms", "yearly"),
    ]
    # The six MICE services and the three audience pages. These, plus the
    # destination detail pages below, are the pages that can actually rank for
    # intent-bearing searches; the index pages alone never could.
    for service in repo.all_services():
        if service.get("slug"):
            entries.append((f"/services/{service['slug']}", "monthly"))
    for audience in repo.all_audiences():
        if audience.get("slug"):
            entries.append((f"/who-we-serve/{audience['slug']}", "monthly"))
    for destination in repo.all_destinations():
        if destination.get("slug"):
            entries.append((f"/destinations/{destination['slug']}", "monthly"))
    for service in (repo.site_config().get("external_services") or []):
        slug = service.get("slug") or service.get("id")
        if slug:
            entries.append((f"/services/{slug}", "monthly"))
    for post in repo.all_posts():
        slug = post.get("slug")
        if slug:
            entries.append((f"/blog/{slug}", "monthly"))
    return entries


@app.get("/sitemap.xml")
async def sitemap_xml(request: Request):
    repo = request.app.state.content_repository
    today = datetime.now(timezone.utc).date().isoformat()
    urls = "".join(
        "<url>"
        f"<loc>{html.escape(f'{SITE_BASE_URL}{path}')}</loc>"
        f"<lastmod>{today}</lastmod>"
        f"<changefreq>{changefreq}</changefreq>"
        "</url>"
        for path, changefreq in _public_sitemap_entries(repo)
    )
    return Response(
        content=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{urls}"
            "</urlset>"
        ),
        media_type="application/xml",
    )


# ==========================================
# ADMIN PORTAL ROUTES (F-32 & F-33)
# ==========================================

def _admin_config():
    password = os.getenv("DEMO_ADMIN_PASSWORD")
    signing_secret = os.getenv("ADMIN_SESSION_SECRET")
    if not password or not signing_secret:
        return None
    return password, signing_secret


def _safe_admin_next(value: str | None) -> str:
    if value and value.startswith("/admin") and not value.startswith("//"):
        return value
    return "/admin"


def _sign_admin_session(signing_secret: str) -> str:
    expires_at = str(int(time.time()) + ADMIN_SESSION_TTL_SECONDS)
    nonce = secrets.token_urlsafe(16)
    payload = f"{expires_at}.{nonce}"
    signature = hmac.new(signing_secret.encode(), payload.encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload}.{encoded_signature}"


def _valid_admin_session(value: str | None, signing_secret: str) -> bool:
    if not value:
        return False
    try:
        expires_at, nonce, signature = value.split(".", 2)
        if int(expires_at) < int(time.time()) or not nonce:
            return False
        payload = f"{expires_at}.{nonce}"
        expected = hmac.new(signing_secret.encode(), payload.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        return hmac.compare_digest(expected, supplied)
    except (ValueError, TypeError):
        return False


async def require_admin(request: Request):
    config = _admin_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    _, signing_secret = config
    if not _valid_admin_session(request.cookies.get(ADMIN_COOKIE_NAME), signing_secret):
        next_path = _safe_admin_next(request.url.path)
        return RedirectResponse(url=f"/admin/login?next={next_path}", status_code=303)
    return None


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, next: str = "/admin"):
    if _admin_config() is None:
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={"next_path": _safe_admin_next(next), "error": None},
    )


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...), next: str = Form("/admin")):
    config = _admin_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    expected_password, signing_secret = config
    if not hmac.compare_digest(password.encode(), expected_password.encode()):
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"next_path": _safe_admin_next(next), "error": "Invalid password"},
            status_code=401,
        )
    response = RedirectResponse(url=_safe_admin_next(next), status_code=303)
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        _sign_admin_session(signing_secret),
        max_age=ADMIN_SESSION_TTL_SECONDS,
        httponly=True,
        secure=os.getenv("APP_ENV", "development").lower() == "production",
        samesite="strict",
        path="/admin",
    )
    return response


@app.post("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/admin")
    return response

@app.get("/admin", include_in_schema=False)
async def admin_home(auth_response=Depends(require_admin)):
    """The admin root is the leads inbox.

    The dashboard, pages, blog, catalogue, media and settings screens were
    removed: every one of them saved its edits to the editor's own browser via
    localStorage, so a visitor never saw a change and a second editor never saw
    the first one's work. Content editing moves to Strapi (see STRAPI.md);
    leads stay here, behind this signed session.
    """
    if auth_response:
        return auth_response
    return RedirectResponse(url="/admin/leads", status_code=307)


def _load_leads(limit: int = 200):
    """(leads, error_code). Never raises — the inbox renders an explanation
    rather than a stack trace when the store is unreachable."""
    try:
        repository = build_lead_repository()
    except LeadStoreUnavailable:
        return [], "unreachable"
    if repository is None:
        return [], "unconfigured"
    try:
        return repository.list_leads(limit=limit), None
    except LeadStoreUnavailable:
        return [], "unreachable"


@app.get("/admin/leads", response_class=HTMLResponse)
async def admin_leads(request: Request, auth_response=Depends(require_admin)):
    if auth_response:
        return auth_response
    leads, error = _load_leads()
    return templates.TemplateResponse(
        request=request,
        name="admin/leads.html",
        context={
            "active_tab": "leads",
            "leads": leads,
            "lead_error": error,
            "strapi_url": STRAPI_URL,
            "brand_name": content_repository.brand().get("name", "ETHPL"),
        },
    )


@app.get("/admin/leads.csv")
async def admin_leads_csv(auth_response=Depends(require_admin)):
    """Export for the sales team's own sheet or CRM.

    Written with the csv module rather than by joining strings: a lead's notes
    field is free text and will eventually contain a comma, a quote or a
    newline, any of which would corrupt a hand-rolled CSV.
    """
    if auth_response:
        return auth_response
    leads, error = _load_leads(limit=5000)
    if error:
        raise HTTPException(status_code=503, detail="Lead storage is unavailable")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(LEAD_LIST_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow(lead)

    filename = f"ethpl-leads-{datetime.now(timezone.utc).date().isoformat()}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _hero_photo_form_state():
    """What the appearance form needs to render: the store status and, per
    slot, whether a photo is set and its current alt text."""
    store = build_site_asset_store()
    if store is None:
        return {"store": "unconfigured", "slots": {}}
    try:
        meta = store.list_meta()
    except AssetStoreUnavailable:
        return {"store": "unreachable", "slots": {}}
    slots = {}
    for key in HERO_PHOTO_KEYS:
        info = meta.get(key)
        slots[key] = {
            "has_photo": bool(info),
            "alt": (info or {}).get("alt", ""),
            "version": _hero_photo_version((info or {}).get("updated_at", "")) if info else "",
        }
    return {"store": "ready", "slots": slots}


@app.get("/admin/appearance", response_class=HTMLResponse)
async def admin_appearance(request: Request, saved: int = 0, auth_response=Depends(require_admin)):
    if auth_response:
        return auth_response
    return templates.TemplateResponse(
        request=request,
        name="admin/appearance.html",
        context={
            "active_tab": "appearance",
            "state": _hero_photo_form_state(),
            "hero_keys": HERO_PHOTO_KEYS,
            "allowed_types": sorted(ALLOWED_IMAGE_TYPES),
            "max_mb": MAX_IMAGE_BYTES // (1024 * 1024),
            "saved": bool(saved),
            "error": None,
            "brand_name": content_repository.brand().get("name", "ETHPL"),
        },
    )


@app.post("/admin/appearance", response_class=HTMLResponse)
async def admin_appearance_save(
    request: Request,
    auth_response=Depends(require_admin),
    photo_1: UploadFile | None = File(None),
    photo_2: UploadFile | None = File(None),
    alt_1: str = Form(""),
    alt_2: str = Form(""),
):
    if auth_response:
        return auth_response

    store = build_site_asset_store()

    def render_error(message: str, status: int = 400):
        return templates.TemplateResponse(
            request=request,
            name="admin/appearance.html",
            context={
                "active_tab": "appearance",
                "state": _hero_photo_form_state(),
                "hero_keys": HERO_PHOTO_KEYS,
                "allowed_types": sorted(ALLOWED_IMAGE_TYPES),
                "max_mb": MAX_IMAGE_BYTES // (1024 * 1024),
                "saved": False,
                "error": message,
                "brand_name": content_repository.brand().get("name", "ETHPL"),
            },
            status_code=status,
        )

    if store is None:
        return render_error(
            "No database is connected yet, so there is nowhere to keep an "
            "uploaded photo. Set DATABASE_URL (the same database that stores "
            "your enquiries) and try again.",
            status=503,
        )

    uploads = {"hero-1": (photo_1, alt_1), "hero-2": (photo_2, alt_2)}
    now = datetime.now(timezone.utc).isoformat()
    changed = False

    for key, (upload, alt) in uploads.items():
        alt = (alt or "").strip()[:160]
        has_file = upload is not None and (upload.filename or "").strip() != ""

        if has_file:
            content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
            if content_type not in ALLOWED_IMAGE_TYPES:
                return render_error(
                    f"'{upload.filename}' is a {content_type or 'unknown'} file. "
                    f"Please upload a JPG, PNG or WebP image."
                )
            data = await upload.read()
            if len(data) > MAX_IMAGE_BYTES:
                return render_error(
                    f"'{upload.filename}' is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB. "
                    f"Please upload a smaller image."
                )
            if not data:
                return render_error(f"'{upload.filename}' appears to be empty.")
            try:
                store.put(key, data, content_type, alt, now)
            except AssetStoreUnavailable:
                return render_error(
                    "The photo could not be saved because the database is "
                    "unreachable right now. Please try again in a moment.",
                    status=503,
                )
            changed = True
        elif alt:
            # Alt text changed without a new file — update it in place if a
            # photo already exists for this slot.
            try:
                existing = store.get(key)
                if existing:
                    content_type, data = existing
                    store.put(key, data, content_type, alt, now)
                    changed = True
            except AssetStoreUnavailable:
                return render_error(
                    "Could not reach the database to save your change. "
                    "Please try again in a moment.",
                    status=503,
                )

    if changed:
        _invalidate_hero_photo_cache()

    return RedirectResponse(url="/admin/appearance?saved=1", status_code=303)


# ==========================================
# API & REDIRECTION ROUTES (F-18, F-19)
# ==========================================

@app.post("/api/rfp")
async def submit_rfp(payload: RFPPayload, request: Request):
    """Register an enquiry.

    An enquiry is the product of everything else on this site, so this route
    tries hard not to lose one. The lead is stored if a database is reachable
    and emailed to the sales owner either way; a submission is only reported as
    failed when BOTH have failed, because telling someone their request was
    sent when nothing recorded it is worse than asking them to try again.
    """
    repository = None
    repository_error = None
    try:
        repository = build_lead_repository()
    except LeadStoreUnavailable:
        # The database is configured but unreachable. Fall through to email.
        repository_error = "lead_store_unavailable"

    notifier = EmailNotifier.from_env()

    if repository is None and repository_error is None and not notifier.enabled:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": {"code": "rfp_unavailable", "message": "Online proposal submission is not configured"}},
        )

    client_ip = request.client.host if request.client else "unknown"
    if os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true":
        client_ip = request.headers.get("x-forwarded-for", client_ip).split(",", 1)[0].strip()
    limit = int(os.getenv("RFP_RATE_LIMIT", "5"))
    window = int(os.getenv("RFP_RATE_WINDOW_SECONDS", "60"))
    allowed, retry_after = rfp_rate_limiter.check(client_ip, limit, window)
    if not allowed:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"ok": False, "error": {"code": "rate_limited", "message": "Too many requests; retry later"}},
        )

    idempotency_key = request.headers.get("idempotency-key")
    if not idempotency_key or len(idempotency_key) > 128 or any(ord(character) < 33 for character in idempotency_key):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": {"code": "invalid_idempotency_key", "message": "A valid Idempotency-Key header is required"}},
        )
    lead = payload.model_dump()
    created_at = datetime.now(timezone.utc).isoformat()

    data = None
    created = True
    stored = False
    if repository is not None:
        try:
            data, created = repository.save(lead, idempotency_key, created_at)
            stored = True
        except LeadStoreUnavailable:
            repository_error = "lead_store_unavailable"

    if not stored:
        # Nothing is in the database, so the email IS the record. Fabricate the
        # reference the caller will quote and make the alert say so loudly.
        data = {
            "reference": new_lead_reference(),
            "company_name": lead["company_name"],
            "destination": lead["destination"],
            "pax_count": lead["pax_count"],
            "timestamp": created_at,
        }

    # Blocking network and SMTP calls go to a worker thread; awaiting them on
    # the event loop would stall every other request on this instance.
    notified = False
    if notifier.enabled and created:
        notified = await run_in_threadpool(
            notifier.send, lead, data["reference"], stored
        )

    if not stored and not notified:
        logger.error(
            "Enquiry could not be stored or emailed (db=%s, email_configured=%s)",
            repository_error or "unconfigured",
            notifier.enabled,
        )
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": {"code": repository_error or "rfp_unavailable", "message": "Proposal submission is temporarily unavailable"}},
        )

    if not stored:
        logger.warning("Enquiry %s delivered by email only (database unreachable)", data["reference"])

    return JSONResponse(
        status_code=201 if created else 200,
        content={
            "ok": True,
            "message": "Corporate proposal request registered successfully",
            "data": data,
            # The browser redirects here so ad and analytics conversions fire on
            # a real page view rather than an XHR response.
            "next": "/thank-you",
        },
    )


@app.get("/redirect")
async def handle_redirect(
    type: str = Query("general", min_length=1, max_length=40, pattern=r"^[^\x00-\x1f\x7f]+$"),
    id: str = Query("default", min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$"),
    ref: str = Query("catalogue", min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$"),
):
    parsed = urlsplit(validated_redirect_base_url())
    path = parsed.path.rstrip("/") + "/enquire"
    target = urlunsplit((parsed.scheme, parsed.netloc, path, urlencode({"type": type, "id": id, "ref": ref}), ""))
    return RedirectResponse(url=target, status_code=307)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "ETHPL MICE Catalogue", "version": "1.0.0"}


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create an isolated application instance with injectable content settings."""
    settings = settings or AppSettings(content_dir=Path(CONTENT_DIR))
    application = FastAPI(
        title=app.title,
        description=app.description,
        version=app.version,
        lifespan=lifespan,
    )
    application.router.routes.extend(app.router.routes)
    application.exception_handlers.update(app.exception_handlers)
    application.user_middleware = list(app.user_middleware)
    application.middleware_stack = application.build_middleware_stack()
    application.state.content_repository = build_content_repository(settings.content_dir)
    return application


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
