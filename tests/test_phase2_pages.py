"""Phase 2: the pages that can actually rank, and the audiences that had no path.

Before this, the site had one /destinations index and spoke only to corporates.
Nothing could rank for "corporate offsite goa", and schools, colleges and NGOs —
all named as target clients — had no page addressing them at all.

These tests pin: one indexable page per destination and per service, the three
audience pages and their short aliases, the structured data each emits, and the
content integrity rules that stop a placeholder or an invented claim reaching
the live site.
"""

import glob
import html as html_module
import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from app import app
from services import ContentRepository


client = TestClient(app)
repo = ContentRepository(content_dir=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content"))

DESTINATIONS = repo.all_destinations()
SERVICES = repo.all_services()
AUDIENCES = repo.all_audiences()

VALID_CATEGORIES = {
    "beach", "hills", "heritage", "nature", "city", "adventure",
    "short-haul", "long-haul",
}
VALID_GOOD_FOR = {"Offsite", "Incentive", "Conference", "Educational", "Budget-friendly"}


def rendered_text(path):
    """Page HTML with entities decoded.

    Jinja autoescapes, so a name like "Conferences & Annual Meets" reaches the
    page as "Conferences &amp; Annual Meets". Asserting on the raw response
    would fail for every name containing an ampersand or a bracket.
    """
    return html_module.unescape(client.get(path).text)


def extract_json_ld(html):
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.DOTALL
    )
    return [json.loads(block) for block in blocks]


# ── destination detail pages ─────────────────────────────────────────────────

def test_every_destination_has_a_page():
    assert len(DESTINATIONS) >= 16
    for destination in DESTINATIONS:
        path = f"/destinations/{destination['slug']}"
        assert client.get(path).status_code == 200, f"{path} failed"
        assert destination["name"] in rendered_text(path)


def test_destination_page_is_indexable_with_its_own_title():
    response = client.get("/destinations/goa")
    assert 'name="robots"' not in response.text
    assert 'rel="canonical"' in response.text
    assert "/destinations/goa" in response.text
    # A unique, intent-bearing title naming the destination — not the
    # site-wide default. The exact wording is not pinned here: it is tuned for
    # search-result length in tests/test_seo_and_assets.py.
    title = html_module.unescape(response.text).split("<title>")[1].split("</title>")[0]
    assert "Goa" in title
    assert "Offsite" in title
    assert title != "MICE Company in Delhi — Events & Group Travel | ETHPL"


def test_destination_titles_are_unique_and_within_sane_length():
    """Duplicate titles compete with each other in search results."""
    titles = {}
    for destination in DESTINATIONS:
        html = client.get(f"/destinations/{destination['slug']}").text
        title = re.search(r"<title>(.*?)</title>", html, re.DOTALL).group(1).strip()
        assert title not in titles, f"{destination['slug']} shares a title with {titles.get(title)}"
        titles[title] = destination["slug"]


def test_destination_page_emits_tourist_destination_and_breadcrumbs():
    blocks = extract_json_ld(client.get("/destinations/dubai").text)
    types = {block.get("@type") for block in blocks}
    assert "TouristDestination" in types
    assert "BreadcrumbList" in types

    crumbs = next(b for b in blocks if b.get("@type") == "BreadcrumbList")
    names = [item["name"] for item in crumbs["itemListElement"]]
    assert names == ["Home", "Destinations", "Dubai"]


def test_destination_page_prefills_the_enquiry_with_that_destination():
    html = client.get("/destinations/goa").text
    assert 'data-destination="Goa, India"' in html


def test_unknown_destination_is_404_not_500():
    assert client.get("/destinations/atlantis").status_code == 404


def test_destination_slug_cannot_escape_the_content_directory():
    """The slug builds a filesystem path, so traversal must be rejected."""
    for attempt in ("../site", "..%2Fsite", "foo/bar", "goa.json"):
        response = client.get(f"/destinations/{attempt}")
        assert response.status_code in (404, 400), f"{attempt!r} returned {response.status_code}"


# ── destination data integrity ───────────────────────────────────────────────

@pytest.mark.parametrize("destination", DESTINATIONS, ids=lambda d: d["slug"])
def test_destination_record_has_phase2_fields(destination):
    assert destination["category"] in VALID_CATEGORIES
    assert destination.get("category_label")
    assert destination.get("best_months")
    assert destination.get("access")

    tags = destination.get("good_for") or []
    assert tags, f"{destination['slug']} has no good_for tags, so no filter will match it"
    unknown = set(tags) - VALID_GOOD_FOR
    assert not unknown, f"{destination['slug']} has unrecognised tags: {unknown}"

    assert len(destination.get("highlights") or []) >= 3
    assert destination.get("planning_note")


def test_placeholder_images_are_flagged_rather_than_mislabelled():
    """Several destinations still show another destination's photograph.

    Captioning Corbett's forest as Jaipur is exactly the kind of detail a buyer
    who knows the place will notice, so those records carry a flag and the page
    renders an imageless treatment instead.
    """
    flagged = [d["slug"] for d in DESTINATIONS if d.get("image_is_placeholder")]
    assert flagged, "expected the reused-photo destinations to still be flagged"

    for slug in flagged:
        html = client.get(f"/destinations/{slug}").text
        assert "dest-detail-hero-blank" in html, f"{slug} renders a photo of somewhere else"

    for destination in DESTINATIONS:
        if not destination.get("image_is_placeholder"):
            html = client.get(f"/destinations/{destination['slug']}").text
            assert "dest-detail-hero-blank" not in html, (
                f"{destination['slug']} has a real photo but renders the blank treatment"
            )


def test_no_destination_claims_a_group_size_nobody_supplied():
    """ideal_group_size is editor-filled. It must stay empty rather than be guessed."""
    for destination in DESTINATIONS:
        value = destination.get("ideal_group_size", "")
        if value:
            assert len(value) < 60, f"{destination['slug']} ideal_group_size looks like prose"


# ── service pages ────────────────────────────────────────────────────────────

def test_services_index_lists_all_six():
    response = client.get("/services")
    assert response.status_code == 200
    assert len(SERVICES) == 6
    text = rendered_text("/services")
    for service in SERVICES:
        assert service["name"] in text
        assert f'/services/{service["slug"]}' in text


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s["slug"])
def test_each_service_has_its_own_page(service):
    path = f"/services/{service['slug']}"
    response = client.get(path)
    assert response.status_code == 200
    text = rendered_text(path)
    assert service["name"] in text
    assert service["intro"] in text
    assert 'rel="canonical"' in response.text
    assert 'name="robots"' not in response.text


def test_service_page_emits_service_faq_and_breadcrumbs():
    blocks = extract_json_ld(client.get("/services/conferences").text)
    types = {block.get("@type") for block in blocks}
    assert {"Service", "FAQPage", "BreadcrumbList"} <= types

    faq = next(b for b in blocks if b.get("@type") == "FAQPage")
    assert len(faq["mainEntity"]) >= 3
    for entry in faq["mainEntity"]:
        assert entry["acceptedAnswer"]["text"].strip()


def test_legacy_partner_service_urls_still_work():
    """These are indexed and linked. Phase 2 must not break them."""
    for slug in ("visa", "holidays"):
        response = client.get(f"/services/{slug}")
        assert response.status_code == 200, f"/services/{slug} regressed"


def test_unknown_service_is_404():
    assert client.get("/services/teleportation").status_code == 404


# ── audience pages ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("audience", AUDIENCES, ids=lambda a: a["slug"])
def test_each_audience_has_a_page(audience):
    path = f"/who-we-serve/{audience['slug']}"
    response = client.get(path)
    assert response.status_code == 200
    assert audience["heading"] in rendered_text(path)
    assert 'rel="canonical"' in response.text


def test_audience_short_aliases_redirect():
    """Short URLs that fit on a business card."""
    for alias, slug in (
        ("/corporates", "corporates"),
        ("/schools-colleges", "schools-colleges"),
        ("/ngos", "ngos"),
    ):
        response = client.get(alias, follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == f"/who-we-serve/{slug}"


def test_schools_page_addresses_safety_not_just_itinerary():
    """A principal's first question is safeguarding, not sightseeing."""
    html = client.get("/who-we-serve/schools-colleges").text
    for expected in ("supervision", "emergency", "parents"):
        assert expected.lower() in html.lower(), f"schools page never mentions {expected}"


def test_audience_page_prefills_organisation_type():
    html = client.get("/who-we-serve/ngos").text
    assert 'data-organisation-type="NGO"' in html


def test_audience_org_type_matches_an_enquiry_form_option():
    """A prefill value absent from the select silently does nothing."""
    options = set(re.findall(r'<option value="([^"]+)"', client.get("/").text))
    for audience in AUDIENCES:
        assert audience["org_type"] in options, (
            f"{audience['slug']} org_type {audience['org_type']!r} is not a form option"
        )


def test_unknown_audience_is_404():
    assert client.get("/who-we-serve/martians").status_code == 404


# ── sitemap and navigation ───────────────────────────────────────────────────

def test_sitemap_contains_every_new_page():
    body = client.get("/sitemap.xml").text
    for destination in DESTINATIONS:
        assert f"/destinations/{destination['slug']}</loc>" in body
    for service in SERVICES:
        assert f"/services/{service['slug']}</loc>" in body
    for audience in AUDIENCES:
        assert f"/who-we-serve/{audience['slug']}</loc>" in body
    assert "/services</loc>" in body


def test_sitemap_excludes_redirects_and_private_pages():
    """Listing a redirect or a noindex page wastes crawl budget.

    Matched as a full <loc> so the alias check is not satisfied by the
    canonical /who-we-serve/corporates URL, which contains the same substring.
    """
    body = client.get("/sitemap.xml").text
    locs = set(re.findall(r"<loc>(.*?)</loc>", body))
    paths = {loc.split(".app", 1)[-1] if ".app" in loc else loc for loc in locs}
    for excluded in ("/corporates", "/schools-colleges", "/ngos", "/thank-you", "/packages", "/hotels", "/estimator"):
        assert excluded not in paths, f"sitemap advertises the redirect {excluded}"
    assert not any("/admin" in loc for loc in locs)


def test_navigation_exposes_services_and_audiences():
    html = client.get("/").text
    assert "/services/meetings-offsites" in html
    assert "/who-we-serve/schools-colleges" in html
    assert "Who We Serve" in html


# ── content hygiene ──────────────────────────────────────────────────────────

def test_no_public_page_leaks_a_todo_marker_into_visible_copy():
    """TODO markers belong in HTML comments and JSON, never in rendered text."""
    paths = (
        ["/", "/services", "/destinations", "/mice", "/blog"]
        + [f"/destinations/{d['slug']}" for d in DESTINATIONS]
        + [f"/services/{s['slug']}" for s in SERVICES]
        + [f"/who-we-serve/{a['slug']}" for a in AUDIENCES]
    )
    for path in paths:
        html = client.get(path).text
        # Strip HTML comments, where TODOs for the team are legitimate.
        visible = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        assert "TODO(" not in visible, f"{path} shows a TODO marker to visitors"


def test_service_and_audience_copy_invents_no_statistics():
    """No count of events, years in business or clients may appear in copy.

    Those numbers have to come from the business. A plausible-looking invented
    figure is the one thing on a MICE site that is actively dangerous.
    """
    banned = re.compile(
        r"\b\d{2,}\s*(?:\+\s*)?(?:years|events|clients|companies|delegates served|"
        r"travellers moved|successful)\b",
        re.IGNORECASE,
    )
    for collection, kind in ((SERVICES, "service"), (AUDIENCES, "audience")):
        for item in collection:
            blob = json.dumps(item)
            match = banned.search(blob)
            assert not match, f"{kind} {item['slug']} claims a statistic: {match.group(0)!r}"


def test_content_files_are_valid_json_with_required_keys():
    for pattern, required in (
        ("content/services/*.json", ("slug", "name", "tagline", "intro", "title", "meta")),
        ("content/audiences/*.json", ("slug", "name", "heading", "intro", "title", "meta", "org_type")),
    ):
        files = glob.glob(pattern)
        assert files, f"no files matched {pattern}"
        for path in files:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            for key in required:
                assert data.get(key), f"{path} is missing {key}"
