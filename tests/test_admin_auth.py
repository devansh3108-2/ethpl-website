from fastapi.testclient import TestClient

from app import ADMIN_COOKIE_NAME, app


# Phase 3 removed the demo admin screens (pages, blog, catalogue, media,
# settings): each saved its edits to the editor's own browser via localStorage,
# so nothing an editor changed ever reached a visitor. What remains is the
# leads inbox and its CSV export, both backed by the real lead store.
ADMIN_ROUTES = [
    "/admin",
    "/admin/leads",
    "/admin/leads.csv",
]


def configure_admin(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "test-only-password")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-signing-secret-with-sufficient-entropy")


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("DEMO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    with TestClient(app) as client:
        for route in ADMIN_ROUTES:
            response = client.get(route)
            assert response.status_code == 503


def test_all_admin_routes_require_authentication(monkeypatch):
    configure_admin(monkeypatch)
    with TestClient(app, follow_redirects=False) as client:
        for route in ADMIN_ROUTES:
            response = client.get(route)
            assert response.status_code == 303
            assert response.headers["location"].startswith("/admin/login")
            assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_login_session_and_logout(monkeypatch):
    configure_admin(monkeypatch)
    with TestClient(app, follow_redirects=False) as client:
        wrong = client.post("/admin/login", data={"password": "wrong", "next": "/admin"})
        assert wrong.status_code == 401
        assert ADMIN_COOKIE_NAME not in client.cookies

        login = client.post(
            "/admin/login",
            data={"password": "test-only-password", "next": "/admin/leads"},
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/admin/leads"
        assert ADMIN_COOKIE_NAME in client.cookies
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "SameSite=strict" in login.headers["set-cookie"]

        # /admin redirects to the inbox; the inbox renders; the CSV export
        # returns 503 when no lead store is configured, which is the honest
        # answer rather than an empty file presented as a complete export.
        assert client.get("/admin").status_code == 307
        assert client.get("/admin/leads").status_code == 200
        assert client.get("/admin/leads.csv").status_code in (200, 503)

        logout = client.post("/admin/logout")
        assert logout.status_code == 303
        assert ADMIN_COOKIE_NAME not in client.cookies
        assert client.get("/admin").status_code == 303


def test_login_rejects_open_redirect(monkeypatch):
    configure_admin(monkeypatch)
    with TestClient(app, follow_redirects=False) as client:
        response = client.post(
            "/admin/login",
            data={"password": "test-only-password", "next": "https://evil.example/steal"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin"
