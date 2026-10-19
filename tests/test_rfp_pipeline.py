import sqlite3

from fastapi.testclient import TestClient

from app import app, rfp_rate_limiter
from services import FixedWindowRateLimiter


VALID = {
    "company_name": "Acme Global Corp",
    "contact_name": "Sarah Jenkins",
    "contact_info": "sarah@example.com",
    "destination": "Dubai, UAE",
    "pax_count": 120,
    "notes": "Conference venue and flights",
}


def test_unconfigured_sink_never_reports_success(monkeypatch):
    monkeypatch.delenv("RFP_DATABASE_PATH", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/rfp", json=VALID, headers={"Idempotency-Key": "unconfigured"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rfp_unavailable"


def test_submission_is_durable_and_retry_is_idempotent(monkeypatch, tmp_path):
    database = tmp_path / "leads.sqlite3"
    monkeypatch.setenv("RFP_DATABASE_PATH", str(database))
    rfp_rate_limiter.clear()
    headers = {"Idempotency-Key": "retry-key-123"}
    with TestClient(app) as client:
        first = client.post("/api/rfp", json=VALID, headers=headers)
        second = client.post("/api/rfp", json=VALID, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["data"]["reference"] == second.json()["data"]["reference"]
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
    finally:
        connection.close()


def test_schema_boundaries_and_extra_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("RFP_DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    invalid_cases = [
        {**VALID, "company_name": "x"},
        {**VALID, "company_name": "x" * 121},
        {**VALID, "contact_info": "not-a-contact"},
        {**VALID, "pax_count": 9},
        {**VALID, "pax_count": 5001},
        {**VALID, "notes": "x" * 2001},
        {**VALID, "unexpected": "field"},
    ]
    with TestClient(app) as client:
        for index, payload in enumerate(invalid_cases):
            response = client.post("/api/rfp", json=payload, headers={"Idempotency-Key": f"invalid-{index}"})
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "validation_failed"


def test_body_limit_and_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("RFP_DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    monkeypatch.setenv("RFP_RATE_LIMIT", "1")
    monkeypatch.setenv("RFP_RATE_WINDOW_SECONDS", "60")
    rfp_rate_limiter.clear()
    with TestClient(app) as client:
        oversized = client.post(
            "/api/rfp",
            content=b"x" * 16_385,
            headers={"Content-Type": "application/json", "Idempotency-Key": "oversized"},
        )
        assert oversized.status_code == 413
        assert client.post("/api/rfp", json=VALID, headers={"Idempotency-Key": "first"}).status_code == 201
        limited = client.post("/api/rfp", json=VALID, headers={"Idempotency-Key": "second"})
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1


def test_rate_limit_window_resets(monkeypatch):
    clock = iter([100.0, 101.0, 111.0])
    monkeypatch.setattr("services.time.monotonic", lambda: next(clock))
    limiter = FixedWindowRateLimiter()
    assert limiter.check("client", 1, 10)[0] is True
    assert limiter.check("client", 1, 10)[0] is False
    assert limiter.check("client", 1, 10)[0] is True
