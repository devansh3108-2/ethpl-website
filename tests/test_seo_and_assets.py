"""Phase 4/5: the SEO and asset invariants that are easy to break silently.

Everything here was a real defect found by auditing the rendered pages rather
than by reading the templates: titles past where Google truncates, descriptions
that ran to 215 characters, breadcrumbs on four pages out of eleven, no favicon
at all, and a social card pointing at a 139x168 portrait logo.
"""

import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app import app
from services import ContentRepository


client = TestClient(app)

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGES = ROOT / "static" / "images"
repo = ContentRepository(content_dir=ROOT / "content")

# Google truncates a desktop result at roughly these lengths. Past them the
# tail is replaced with an ellipsis, so the useful words never get read.
TITLE_LIMIT = 60
DESCRIPTION_LIMIT = 155

PAGES = (
    ["/", "/mice", "/services", "/destinations", "/blog", "/privacy", "/terms"]
    + [f"/destinations/{d['slug']}" for d in repo.all_destinations()]
    + [f"/services/{s['slug']}" for s in repo.all_services()]
    + [f"/who-we-serve/{a['slug']}" for a in repo.all_audiences()]
    + ["/services/visa", "/services/holidays"]
)

# Breadcrumbs need at least two levels to be valid structured data, so the
# homepage and the post-enquiry page correctly have none.
NO_BREADCRUMB_EXPECTED = {"/", "/thank-you"}


def head_of(path):
    html = client.get(path).text
    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    description = re.search(r'<meta name="description" content="(.*?)">', html, re.DOTALL)
    return html, (title.group(1).strip() if title else ""), (description.group(1).strip() if description else "")


# ── titles and descriptions ──────────────────────────────────────────────────

@pytest.mark.parametrize("path", PAGES)
def test_title_fits_a_search_result(path):
    _, title, _ = head_of(path)
    assert title, f"{path} has no title"
    assert len(title) <= TITLE_LIMIT, f"{path} title is {len(title)} chars: {title!r}"


@pytest.mark.parametrize("path", PAGES)
def test_description_fits_a_search_result(path):
    _, _, description = head_of(path)
    assert description, f"{path} has no meta description"
    assert len(description) <= DESCRIPTION_LIMIT, (
        f"{path} description is {len(description)} chars"
    )


def test_every_page_title_is_unique():
    """Duplicate titles compete with each other for the same query."""
    seen = {}
    for path in PAGES:
        _, title, _ = head_of(path)
        assert title not in seen, f"{path} duplicates the title of {seen.get(title)}"
        seen[title] = path


# ── structured data ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [p for p in PAGES if p not in NO_BREADCRUMB_EXPECTED])
def test_page_emits_breadcrumbs(path):
    html, _, _ = head_of(path)
    assert "BreadcrumbList" in html, f"{path} has no BreadcrumbList"


def test_homepage_does_not_emit_a_one_item_breadcrumb():
    """A single-item BreadcrumbList is not valid structured data."""
    html, _, _ = head_of("/")
    assert "BreadcrumbList" not in html


def test_breadcrumb_trail_is_ordered_and_absolute():
    html, _, _ = head_of("/destinations/goa")
    blocks = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.DOTALL)
    crumbs = next(
        json.loads(b) for b in blocks if json.loads(b).get("@type") == "BreadcrumbList"
    )
    items = crumbs["itemListElement"]
    assert [i["name"] for i in items] == ["Home", "Destinations", "Goa"]
    assert [i["position"] for i in items] == [1, 2, 3]
    for item in items:
        assert item["item"].startswith("http"), "breadcrumb URLs must be absolute"


def test_breadcrumbs_are_defined_in_exactly_one_template():
    """They were hand-written in four templates and missing from seven, which
    is what happens when the same JSON-LD is copied around."""
    emitting = [
        path.name
        for path in (ROOT / "templates").rglob("*.html")
        if "BreadcrumbList" in path.read_text(encoding="utf-8")
    ]
    assert emitting == ["base.html"], f"BreadcrumbList also defined in {emitting}"


# ── images ───────────────────────────────────────────────────────────────────

def test_every_png_has_a_webp_sibling():
    """templates/partials/picture.html derives the .webp path by swapping the
    extension. A <picture> source that 404s is NOT retried as the fallback, so
    the pairing has to be guaranteed, not assumed."""
    missing = [
        png.name for png in IMAGES.glob("*.png")
        if not png.with_suffix(".webp").exists()
    ]
    assert not missing, f"PNGs without a .webp sibling: {missing}"


def test_webp_is_actually_smaller():
    """If a .webp were larger than its PNG the <picture> would be a pessimism."""
    worse = []
    for png in IMAGES.glob("*.png"):
        webp = png.with_suffix(".webp")
        if webp.exists() and webp.stat().st_size >= png.stat().st_size:
            worse.append(f"{png.name} ({png.stat().st_size} -> {webp.stat().st_size})")
    assert not worse, f"WebP larger than PNG for: {worse}"


@pytest.mark.parametrize("path", ["/", "/destinations", "/destinations/goa"])
def test_every_image_reserves_its_space(path):
    """Without width and height the browser cannot reserve space, so each
    image shoves the layout down as it loads."""
    html = client.get(path).text
    for tag in re.findall(r"<img\b[^>]*>", html):
        assert "width=" in tag and "height=" in tag, f"{path}: img without dimensions: {tag[:110]}"
        assert "alt=" in tag, f"{path}: img without alt: {tag[:110]}"


def test_photographs_are_served_through_picture_elements():
    html = client.get("/destinations").text
    assert "<picture>" in html
    assert 'type="image/webp"' in html


# ── favicon and social card ──────────────────────────────────────────────────

def test_favicon_exists_and_is_linked():
    """The site shipped with none: a blank page icon in every tab."""
    for name in ("favicon.ico", "favicon.png", "apple-touch-icon.png"):
        assert (IMAGES / name).exists(), f"{name} is missing"
    html = client.get("/").text
    assert 'rel="icon"' in html
    assert 'rel="apple-touch-icon"' in html


def test_social_card_is_the_right_shape():
    """og:image pointed at a 139x168 portrait logo, which every platform crops
    to roughly 1.91:1 and renders unreadable."""
    html = client.get("/").text
    assert "og-image.png" in html
    assert '<meta property="og:image:width" content="1200">' in html
    assert '<meta property="og:image:height" content="630">' in html

    from PIL import Image
    with Image.open(IMAGES / "og-image.png") as image:
        assert image.size == (1200, 630)


def test_theme_colour_matches_the_brand():
    html = client.get("/").text
    assert '<meta name="theme-color" content="#2F5D27">' in html


# ── analytics ────────────────────────────────────────────────────────────────

def test_no_third_party_requests_when_analytics_is_unconfigured():
    """A developer running locally, and a site that has not decided to measure,
    should send nothing to anyone."""
    html = client.get("/").text
    assert "googletagmanager.com" not in html
    assert "clarity.ms" not in html


def test_analytics_loads_only_when_an_id_is_set(monkeypatch):
    import importlib
    import app as app_module

    monkeypatch.setenv("GA4_MEASUREMENT_ID", "G-TESTID123")
    monkeypatch.setenv("CLARITY_PROJECT_ID", "testclarity")
    reloaded = importlib.reload(app_module)
    try:
        html = TestClient(reloaded.app).get("/").text
        assert "googletagmanager.com/gtag/js?id=G-TESTID123" in html
        assert 'clarity.ms/tag/' in html and "testclarity" in html
    finally:
        monkeypatch.undo()
        importlib.reload(app_module)


def test_conversion_events_are_wired():
    """Traffic without conversion events shows visits but not enquiries, which
    is the only number that matters for this site."""
    analytics = (ROOT / "static" / "js" / "analytics.js").read_text(encoding="utf-8")
    for event in ("form_start", "phone_click", "whatsapp_click"):
        assert f"'{event}'" in analytics, f"{event} is not tracked"

    controller = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "generate_lead" in controller, "a successful submission is not tracked"


def test_analytics_never_breaks_the_page_it_measures():
    analytics = (ROOT / "static" / "js" / "analytics.js").read_text(encoding="utf-8")
    assert "try {" in analytics and "catch" in analytics


# ── brand lockup ─────────────────────────────────────────────────────────────

def test_logo_lockup_is_a_single_partial():
    assert (ROOT / "templates" / "partials" / "brand_lockup.html").exists()
    html = client.get("/").text
    # Header and footer both render it.
    assert html.count("brand-lockup") >= 2


def test_lockup_reads_the_brand_from_content():
    """Three different names once sat next to the same mark."""
    lockup = (ROOT / "templates" / "partials" / "brand_lockup.html").read_text(encoding="utf-8")
    assert "brand.name" in lockup
    assert "brand.tagline" in lockup
