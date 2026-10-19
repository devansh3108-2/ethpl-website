"""Phase 3: the leads inbox shows real enquiries.

This page previously rendered a hard-coded table of invented enquiries from
Tata Motors, Infosys, HDFC and Razorpay, with fabricated contact addresses. It
now reads the lead store, and when there is no store it says so instead of
showing something that looks like data.
"""

import csv
import io
import os
import re

import pytest
from fastapi.testclient import TestClient

from app import app, rfp_rate_limiter


ADMIN_PASSWORD = "test-only-password"


@pytest.fixture
def admin(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RFP_DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    rfp_rate_limiter.clear()
    with TestClient(app, follow_redirects=False) as client:
        client.post("/admin/login", data={"password": ADMIN_PASSWORD, "next": "/admin/leads"})
        yield client


@pytest.fixture
def unauthenticated(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    with TestClient(app, follow_redirects=False) as client:
        yield client


def submit(client, company, **overrides):
    payload = {
        "company_name": company,
        "contact_name": "A Person",
        "contact_info": "person@example.com",
        "destination": "Goa, India",
        "pax_count": 40,
        "organisation_type": "Corporate",
        "event_type": "Corporate Offsite",
        "travel_window": "March",
    }
    payload.update(overrides)
    # The header rejects any character below ASCII 33, so a company name with
    # a space in it cannot be used raw as the key.
    key = re.sub(r"[^A-Za-z0-9-]", "-", company)
    response = client.post(
        "/api/rfp", json=payload, headers={"Idempotency-Key": f"key-{key}"}
    )
    # Assert here rather than in each test: a silently failed submission makes
    # the real assertion ("why is the inbox empty?") much harder to read.
    assert response.status_code == 201, (
        f"enquiry submission failed: {response.status_code} {response.text[:300]}"
    )
    return response


# ── authentication ───────────────────────────────────────────────────────────

def test_inbox_and_export_require_a_session(unauthenticated):
    """Leads contain contact details. Both routes must be gated."""
    for route in ("/admin/leads", "/admin/leads.csv"):
        response = unauthenticated.get(route)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/admin/login")


def test_admin_pages_are_never_indexable(admin):
    response = admin.get("/admin/leads")
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["cache-control"] == "no-store"


# ── real data ────────────────────────────────────────────────────────────────

def test_fabricated_sample_leads_are_gone(admin):
    """The old page shipped invented enquiries from named real companies."""
    html = admin.get("/admin/leads").text
    for invented in ("Tata Motors", "Infosys", "HDFC", "Razorpay",
                     "Rohan Singhal", "Priya Menon", "rohan.s@tatamotors.com"):
        assert invented not in html, f"fabricated sample lead {invented!r} still present"


def test_submitted_enquiries_appear_in_the_inbox(admin):
    submit(admin, "Northside School", organisation_type="School",
           event_type="Educational Tour", pax_count=55)
    html = admin.get("/admin/leads").text
    assert "Northside School" in html
    assert "School" in html
    assert "Educational Tour" in html
    assert "55" in html


def test_contact_details_are_actionable(admin):
    """Sales reply from a phone; the contact should be one tap away."""
    submit(admin, "Email Corp", contact_info="buyer@emailcorp.example")
    html = admin.get("/admin/leads").text
    assert 'href="mailto:buyer@emailcorp.example"' in html

    submit(admin, "Phone Corp", contact_info="+91 98100 00000")
    html = admin.get("/admin/leads").text
    assert 'href="tel:+919810000000"' in html


def test_newest_lead_is_listed_first(admin):
    for name in ("First Co", "Second Co", "Third Co"):
        submit(admin, name)
    html = admin.get("/admin/leads").text
    positions = [html.index(name) for name in ("Third Co", "Second Co", "First Co")]
    assert positions == sorted(positions), "inbox must be newest first"


def test_empty_inbox_explains_itself_rather_than_looking_broken(admin):
    html = admin.get("/admin/leads").text
    assert "No enquiries yet" in html
    assert "Export CSV" not in html, "nothing to export, so no export button"


def test_unconfigured_store_tells_the_operator_what_to_set(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RFP_DATABASE_PATH", raising=False)
    with TestClient(app, follow_redirects=False) as client:
        client.post("/admin/login", data={"password": ADMIN_PASSWORD, "next": "/admin/leads"})
        html = client.get("/admin/leads").text
    assert "not configured" in html
    assert "DATABASE_URL" in html


# ── CSV export ───────────────────────────────────────────────────────────────

def test_csv_export_round_trips_through_a_real_parser(admin):
    """Notes are free text and will eventually contain a comma, a quote or a
    newline. A hand-rolled CSV would corrupt on all three."""
    nasty = 'Needs 2 rooms, "quiet" side, and:\nan early check-in'
    submit(admin, "Comma, Quote & Newline Ltd", notes=nasty)

    response = admin.get("/admin/leads.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert ".csv" in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Comma, Quote & Newline Ltd"
    assert rows[0]["notes"] == nasty


def test_csv_header_matches_the_declared_columns(admin):
    from services import LEAD_LIST_COLUMNS
    submit(admin, "Header Check Ltd")
    reader = csv.reader(io.StringIO(admin.get("/admin/leads.csv").text))
    assert next(reader) == list(LEAD_LIST_COLUMNS)


def test_csv_is_503_rather_than_an_empty_file_when_the_store_is_missing(monkeypatch):
    """An empty CSV looks like 'no leads'. A 503 says 'this did not work'."""
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RFP_DATABASE_PATH", raising=False)
    with TestClient(app, follow_redirects=False) as client:
        client.post("/admin/login", data={"password": ADMIN_PASSWORD, "next": "/admin/leads"})
        assert client.get("/admin/leads.csv").status_code == 503


# ── the demo admin is gone ───────────────────────────────────────────────────

@pytest.mark.parametrize("route", [
    "/admin/pages", "/admin/blog", "/admin/catalogue", "/admin/media", "/admin/settings",
])
def test_demo_admin_screens_are_removed(admin, route):
    """Each of these saved edits to the editor's own browser via localStorage,
    so a visitor never saw a change and a second editor never saw the first
    one's work."""
    assert admin.get(route).status_code == 404


def test_admin_root_goes_to_the_inbox(admin):
    response = admin.get("/admin")
    assert response.status_code == 307
    assert response.headers["location"] == "/admin/leads"


def test_strapi_link_appears_only_once_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    monkeypatch.setenv("RFP_DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    with TestClient(app, follow_redirects=False) as client:
        client.post("/admin/login", data={"password": ADMIN_PASSWORD, "next": "/admin/leads"})
        html = client.get("/admin/leads").text
    # STRAPI_URL is read at import time, so an unset value means no dead link.
    if not os.getenv("STRAPI_URL"):
        assert "Edit content" not in html
