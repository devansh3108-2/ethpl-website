"""Phase 1b: an enquiry must survive a database outage.

Before this, lead storage was SQLite behind RFP_DATABASE_PATH. On Vercel that
variable is unset and the filesystem is disposable, so the live form told
visitors their request had not been sent. These tests pin the behaviour that
replaced it:

  database reachable            -> stored, and emailed
  database down, email working  -> success anyway, email flagged as the record
  both unavailable              -> honest 503, never a fake success
  nothing configured            -> honest 503

The database and the mail transport are both mocked. No test here opens a
socket, so the suite stays runnable offline and in CI.
"""

import json
import smtplib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import app, rfp_rate_limiter
from services import EmailNotifier, LeadStoreUnavailable, build_lead_repository


client = TestClient(app)


ENQUIRY = {
    "company_name": "Ryan International School",
    "contact_name": "Meera Iyer",
    "contact_info": "meera@example.com",
    "destination": "Jaipur, India",
    "pax_count": 42,
    "organisation_type": "School",
    "event_type": "Educational Tour",
    "travel_window": "second week of December",
    "notes": "Class 8 heritage tour, need female staff on the trip",
}


def post(key, payload=None):
    return client.post(
        "/api/rfp",
        json=payload or ENQUIRY,
        headers={"Idempotency-Key": key},
    )


@pytest.fixture
def sqlite_db(monkeypatch, tmp_path):
    """Local-development storage, standing in for Postgres in these tests."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RFP_DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    return tmp_path / "leads.sqlite3"


@pytest.fixture
def mail_configured(monkeypatch):
    monkeypatch.setenv("SALES_EMAIL", "sales@ethpl.example")
    monkeypatch.setenv("SMTP_HOST", "smtp.ethpl.example")
    monkeypatch.setenv("SMTP_USER", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def clean_lead_env(monkeypatch):
    """Stop a developer's real environment leaking into these assertions."""
    for name in (
        "DATABASE_URL", "RFP_DATABASE_PATH", "SALES_EMAIL",
        "RESEND_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    # The limiter is a module-level singleton keyed by client IP, and every
    # test here shares TestClient's IP. Without a reset, tests late in the file
    # get a 429 from requests made by earlier ones. Rate limiting itself is
    # covered in test_rfp_pipeline.py, which owns that behaviour.
    rfp_rate_limiter.clear()


# ── storage selection ────────────────────────────────────────────────────────

def test_database_url_takes_precedence_over_sqlite_path():
    """Production sets DATABASE_URL; it must win over a stale local path."""
    with patch("services.PostgresLeadRepository") as postgres:
        repository = build_lead_repository(
            {"DATABASE_URL": "postgresql://x/y", "RFP_DATABASE_PATH": "/tmp/ignored.sqlite3"}
        )
    postgres.assert_called_once_with("postgresql://x/y")
    assert repository is postgres.return_value


def test_no_configuration_yields_no_repository():
    assert build_lead_repository({}) is None


# ── the happy path ───────────────────────────────────────────────────────────

def test_enquiry_is_stored_and_emailed(sqlite_db, mail_configured):
    with patch.object(EmailNotifier, "send", return_value=True) as send:
        response = post("stored-and-emailed")

    assert response.status_code == 201
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["reference"].startswith("RFP-")
    assert body["next"] == "/thank-you"

    send.assert_called_once()
    lead, reference, stored = send.call_args.args
    assert stored is True, "a stored lead must not be flagged as email-only"
    assert lead["organisation_type"] == "School"
    assert reference == body["data"]["reference"]


def test_qualifying_answers_reach_the_sales_email(sqlite_db, mail_configured):
    """The alert has to be actionable on a phone without opening a dashboard."""
    sent = {}

    def capture(message):
        sent["subject"] = message["Subject"]
        sent["body"] = message.get_content()

    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value.send_message.side_effect = capture
        response = post("smtp-body-check")

    assert response.status_code == 201
    assert "Ryan International School" in sent["subject"]
    assert "Educational Tour" in sent["subject"]
    assert "42" in sent["subject"]
    for expected in (
        "Ryan International School", "Meera Iyer", "meera@example.com",
        "Jaipur, India", "second week of December", "School",
        "female staff",
    ):
        assert expected in sent["body"], f"email body is missing {expected!r}"
    # A stored lead must not carry the email-only warning.
    assert "WARNING" not in sent["body"]


# ── the outage path: this is the point of the change ─────────────────────────

def test_database_down_but_email_works_still_succeeds(mail_configured, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unreachable/db")

    with patch("services.PostgresLeadRepository", side_effect=LeadStoreUnavailable("down")):
        with patch.object(EmailNotifier, "send", return_value=True) as send:
            response = post("db-down-email-up")

    assert response.status_code == 201, "a reachable sales inbox is enough to accept the lead"
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["reference"].startswith("RFP-")

    _lead, _reference, stored = send.call_args.args
    assert stored is False, "the alert must say the database did not record this"


def test_email_only_alert_warns_that_it_is_the_sole_record():
    subject, body = EmailNotifier.compose(ENQUIRY, "RFP-TEST", stored=False)
    assert "WARNING" in body
    assert "ONLY" in body
    assert "Copy it somewhere safe" in body


def test_both_unavailable_returns_honest_failure(mail_configured, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unreachable/db")

    with patch("services.PostgresLeadRepository", side_effect=LeadStoreUnavailable("down")):
        with patch.object(EmailNotifier, "send", return_value=False):
            response = post("db-down-email-down")

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert "reference" not in json.dumps(body["error"]), (
        "a failed submission must not hand back a reference that records nothing"
    )


def test_nothing_configured_returns_503():
    response = post("unconfigured")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rfp_unavailable"


def test_smtp_failure_does_not_break_a_stored_lead(sqlite_db, mail_configured):
    """A mail outage must not lose a lead that is already in the database."""
    with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("relay refused")):
        response = post("smtp-explodes")

    assert response.status_code == 201
    assert response.json()["ok"] is True


# ── idempotency ──────────────────────────────────────────────────────────────

def test_repeated_submission_is_not_a_second_lead(sqlite_db, mail_configured):
    with patch.object(EmailNotifier, "send", return_value=True) as send:
        first = post("same-key-twice")
        second = post("same-key-twice")

    assert first.status_code == 201
    assert second.status_code == 200, "a retry must not create a second lead"
    assert first.json()["data"]["reference"] == second.json()["data"]["reference"]
    assert send.call_count == 1, "the sales team must not be emailed twice for one enquiry"


# ── notifier configuration ───────────────────────────────────────────────────

def test_notifier_is_disabled_without_a_sales_address():
    assert EmailNotifier.from_env({"SMTP_HOST": "smtp.example"}).enabled is False


def test_notifier_is_disabled_without_a_transport():
    assert EmailNotifier.from_env({"SALES_EMAIL": "a@b.com"}).enabled is False


def test_notifier_prefers_resend_when_both_are_configured():
    notifier = EmailNotifier.from_env({
        "SALES_EMAIL": "sales@ethpl.example",
        "RESEND_API_KEY": "re_test",
        "SMTP_HOST": "smtp.example",
    })
    assert notifier.enabled is True
    with patch.object(notifier, "_send_via_resend", return_value=True) as resend:
        with patch.object(notifier, "_send_via_smtp") as smtp:
            assert notifier.send(ENQUIRY, "RFP-TEST") is True
    resend.assert_called_once()
    smtp.assert_not_called()


def test_disabled_notifier_sends_nothing():
    notifier = EmailNotifier.from_env({})
    with patch.object(notifier, "_send_via_smtp") as smtp:
        assert notifier.send(ENQUIRY, "RFP-TEST") is False
    smtp.assert_not_called()


# ── thank-you page ───────────────────────────────────────────────────────────

def test_thank_you_page_renders_and_is_not_indexable():
    response = client.get("/thank-you")
    assert response.status_code == 200
    assert "Thank you" in response.text
    # A conversion page has no value in search results.
    assert 'name="robots"' in response.text
    assert "noindex" in response.text


def test_thank_you_page_is_absent_from_the_sitemap():
    assert "/thank-you" not in client.get("/sitemap.xml").text


# ── schema drift guard ───────────────────────────────────────────────────────

def test_insert_sql_matches_the_declared_lead_columns():
    """The Postgres INSERT is written out literally for reviewability.

    That means it can silently fall out of step with LEAD_COLUMNS when a field
    is added — the kind of bug that drops a qualifying answer without failing
    anything. This pins the two together.
    """
    from services import LEAD_COLUMNS, PostgresLeadRepository

    sql = PostgresLeadRepository.INSERT_SQL
    for column in LEAD_COLUMNS:
        assert column in sql, f"{column} is declared in LEAD_COLUMNS but absent from INSERT_SQL"
    assert sql.count("%s") == len(LEAD_COLUMNS), (
        f"INSERT_SQL has {sql.count('%s')} placeholders for "
        f"{len(LEAD_COLUMNS)} columns"
    )


def test_sqlite_and_postgres_agree_on_the_public_response():
    """Both stores must hand the route the same shape, or the JSON differs by
    whichever backend happens to be configured."""
    from services import PUBLIC_LEAD_FIELDS, PostgresLeadRepository

    row = ("RFP-X", "Acme", "Goa, India", 30, "2026-01-01T00:00:00+00:00")
    public = PostgresLeadRepository._public(row)
    assert set(public) == set(PUBLIC_LEAD_FIELDS) | {"timestamp"}
    assert public["reference"] == "RFP-X"
    assert public["timestamp"] == "2026-01-01T00:00:00+00:00"
