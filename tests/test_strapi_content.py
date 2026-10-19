"""Phase 3: Strapi as the content editor, with the JSON files as a safety net.

The single most important property here is that **a Strapi outage cannot take
the public site down**. Strapi is a separate Node service with its own database
and its own uptime; the website does not control it. Every read therefore falls
back to the JSON files in the repository, which are a complete copy of the
content.

These tests mock the HTTP layer. None of them opens a socket.
"""

import json
import os
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from services import (
    ContentRepository,
    StrapiContentRepository,
    StrapiUnavailable,
    build_content_repository,
)


ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"


@pytest.fixture
def local():
    return ContentRepository(content_dir=CONTENT_DIR)


@pytest.fixture
def strapi(local):
    return StrapiContentRepository(
        base_url="https://cms.example", token="read-only-token", fallback=local
    )


def fake_response(payload, status=200):
    response = MagicMock()
    response.status = status
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *args: False
    return response


# ── repository selection ─────────────────────────────────────────────────────

def test_local_repository_when_strapi_is_not_configured():
    """The normal operating state today, and a fully supported one."""
    repository = build_content_repository(CONTENT_DIR, env={})
    assert isinstance(repository, ContentRepository)


def test_strapi_requires_both_url_and_token():
    """Half-configured must not half-work: a URL with no token would 401 on
    every request and fall back on every page."""
    assert isinstance(build_content_repository(CONTENT_DIR, env={"STRAPI_URL": "https://x"}), ContentRepository)
    assert isinstance(build_content_repository(CONTENT_DIR, env={"STRAPI_TOKEN": "t"}), ContentRepository)
    both = build_content_repository(
        CONTENT_DIR, env={"STRAPI_URL": "https://x", "STRAPI_TOKEN": "t"}
    )
    assert isinstance(both, StrapiContentRepository)


# ── the outage path ──────────────────────────────────────────────────────────

def test_strapi_outage_falls_back_to_local_content(strapi, local):
    """The property the whole design exists for."""
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        destinations = strapi.all_destinations()

    assert destinations, "an outage must not produce an empty site"
    assert len(destinations) == len(local.all_destinations())
    assert {d["slug"] for d in destinations} == {d["slug"] for d in local.all_destinations()}


def test_every_collection_falls_back_independently(strapi, local):
    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert len(strapi.all_services()) == len(local.all_services())
        assert len(strapi.all_audiences()) == len(local.all_audiences())
        assert strapi.all_destinations()
        assert strapi.testimonials() == local.testimonials()
        assert strapi.clients() == local.clients()


def test_a_non_2xx_response_falls_back(strapi, local):
    with patch("urllib.request.urlopen", return_value=fake_response({}, status=500)):
        assert len(strapi.all_destinations()) == len(local.all_destinations())


def test_a_malformed_response_falls_back(strapi, local):
    """A Strapi misconfiguration returning HTML, or a renamed field, must not
    blank the site."""
    with patch("urllib.request.urlopen", return_value=fake_response({"data": "not-a-list"})):
        assert len(strapi.all_destinations()) == len(local.all_destinations())


def test_lookup_by_slug_works_through_the_fallback(strapi):
    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert strapi.destination_by_slug("goa")["name"] == "Goa"
        assert strapi.service_by_slug("conferences")["slug"] == "conferences"
        assert strapi.audience_by_slug("ngos")["org_type"] == "NGO"


def test_unknown_and_unsafe_slugs_are_rejected_not_fetched(strapi):
    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert strapi.destination_by_slug("atlantis") is None
        # Slug validation is shared with the local repository, so a traversal
        # attempt is refused before any lookup happens.
        assert strapi.destination_by_slug("../site") is None
        assert strapi.service_by_slug("a/b") is None


# ── the happy path ───────────────────────────────────────────────────────────

STRAPI_V4 = {"data": [
    {"id": 1, "attributes": {"slug": "cms-goa", "name": "CMS Goa", "region": "india",
                             "country": "India", "tagline": "From Strapi", "sort_order": 1}},
]}
STRAPI_V5 = {"data": [
    {"id": 1, "slug": "cms-goa", "name": "CMS Goa", "region": "india",
     "country": "India", "tagline": "From Strapi", "sort_order": 1},
]}


@pytest.mark.parametrize("payload,label", [(STRAPI_V4, "v4 nested"), (STRAPI_V5, "v5 flat")])
def test_strapi_content_is_used_when_available(strapi, payload, label):
    """Strapi v4 nests fields under `attributes`; v5 does not. Handling both
    means upgrading Strapi cannot silently empty the site."""
    with patch("urllib.request.urlopen", return_value=fake_response(payload)):
        destinations = strapi.all_destinations()
    assert len(destinations) == 1, label
    assert destinations[0]["name"] == "CMS Goa"
    assert destinations[0]["slug"] == "cms-goa"


def test_results_are_cached(strapi):
    """Without caching, one page render would make a separate HTTP call per
    collection, several times over."""
    with patch("urllib.request.urlopen", return_value=fake_response(STRAPI_V5)) as urlopen:
        strapi.all_destinations()
        strapi.all_destinations()
        strapi.featured_destinations()
    assert urlopen.call_count == 1


def test_the_request_is_authenticated_and_scoped(strapi):
    with patch("urllib.request.urlopen", return_value=fake_response(STRAPI_V5)) as urlopen:
        strapi.all_destinations()
    request = urlopen.call_args.args[0]
    assert request.full_url.startswith("https://cms.example/api/destinations?")
    assert request.headers["Authorization"] == "Bearer read-only-token"


def test_plain_http_is_refused_for_a_remote_host(local):
    """A token sent over plain HTTP to a remote host is a leaked token."""
    insecure = StrapiContentRepository(
        base_url="http://cms.example", token="t", fallback=local
    )
    with pytest.raises(StrapiUnavailable):
        insecure._fetch("destinations")
    # And the public behaviour is a fallback, not an error page.
    assert len(insecure.all_destinations()) == len(local.all_destinations())


def test_localhost_over_http_is_allowed_for_development(local):
    dev = StrapiContentRepository(base_url="http://localhost:1337", token="t", fallback=local)
    with patch("urllib.request.urlopen", return_value=fake_response(STRAPI_V5)):
        assert dev.all_destinations()[0]["slug"] == "cms-goa"


def test_anything_strapi_does_not_own_is_delegated(strapi, local):
    """Blog posts, brand, home copy and legal pages stay in the repository."""
    assert strapi.brand()["name"] == local.brand()["name"]
    assert len(strapi.all_posts()) == len(local.all_posts())
    assert strapi.legal_page("privacy")["title"] == "Privacy Policy"
    assert strapi.home()["hero"]["headline"] == local.home()["hero"]["headline"]


# ── schemas and migration tooling ────────────────────────────────────────────

def test_a_schema_exists_for_every_strapi_collection():
    """A missing schema means an editor hand-builds that collection and a typo
    silently sends the site back to local content for it."""
    schema_dir = ROOT / "strapi" / "schemas"
    plurals = set()
    for path in schema_dir.glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["kind"] == "collectionType"
        assert schema["info"]["pluralName"]
        plurals.add(schema["info"]["pluralName"])

    for collection in StrapiContentRepository.COLLECTIONS:
        assert collection in plurals, f"no Strapi schema for {collection}"


def test_schema_fields_cover_what_the_templates_read():
    """A field missing from the schema cannot be edited in Strapi, so it would
    come back empty after migration."""
    schema = json.loads((ROOT / "strapi" / "schemas" / "destination.json").read_text(encoding="utf-8"))
    attributes = schema["attributes"]
    for required in (
        "slug", "name", "region", "country", "category", "tagline",
        "good_for", "best_months", "access", "highlights", "planning_note",
    ):
        assert required in attributes, f"destination schema is missing {required}"


def test_migration_script_refuses_to_run_unconfigured():
    script = (ROOT / "scripts" / "migrate_to_strapi.py").read_text(encoding="utf-8")
    assert "Set STRAPI_URL and STRAPI_TOKEN first" in script
    # Idempotent by natural key, so a failed run can simply be repeated.
    assert "find_existing" in script
    assert '"PUT"' in script and '"POST"' in script
    # Media is explicitly out of scope rather than silently dropped.
    assert "card_image" in script


def test_setup_guide_states_the_cost_and_the_fallback():
    """Strapi was chosen over a free Git-based CMS. The guide has to be honest
    about what that costs and what the alternative was."""
    guide = (ROOT / "STRAPI.md").read_text(encoding="utf-8").lower()
    assert "month" in guide
    assert "read-only" in guide
    assert "falls back" in guide or "fall back" in guide
    assert "sveltia" in guide or "git-based" in guide
