"""The admin can replace the two homepage hero photos without code.

Uploaded images are kept in the same database that stores leads (SQLite here,
Postgres in production) and served from /media/<key>; the homepage overlays
them onto the hero. With no database configured the feature degrades honestly:
the admin page says so and the homepage keeps its placeholder, rather than
pretending a photo was saved.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app import app, _invalidate_hero_photo_cache


ADMIN_PASSWORD = "test-only-password"

# A real, minimal 1x1 PNG. Hard-coded so the test needs no image library.
PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f630000000049454e44ae426082"
)


@pytest.fixture
def admin(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RFP_DATABASE_PATH", str(tmp_path / "site.sqlite3"))
    _invalidate_hero_photo_cache()
    with TestClient(app, follow_redirects=False) as client:
        client.post("/admin/login", data={"password": ADMIN_PASSWORD, "next": "/admin/appearance"})
        yield client
    _invalidate_hero_photo_cache()


@pytest.fixture
def no_store(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RFP_DATABASE_PATH", raising=False)
    _invalidate_hero_photo_cache()
    with TestClient(app, follow_redirects=False) as client:
        client.post("/admin/login", data={"password": ADMIN_PASSWORD, "next": "/admin/appearance"})
        yield client
    _invalidate_hero_photo_cache()


# ── authentication ───────────────────────────────────────────────────────────

def test_appearance_requires_login(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-value-at-least-32-bytes-long")
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/admin/appearance")
    assert response.status_code == 303
    assert "/admin/login" in response.headers["location"]


def test_media_route_rejects_unknown_key(admin):
    assert admin.get("/media/not-a-slot").status_code == 404


# ── happy path ───────────────────────────────────────────────────────────────

def test_upload_sets_the_hero_photo_and_serves_it(admin):
    response = admin.post(
        "/admin/appearance",
        files={"photo_1": ("hero.png", PNG_1x1, "image/png")},
        data={"alt_1": "Annual sales conference", "alt_2": ""},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/appearance?saved=1"

    # The image is now served from the media route with the real bytes.
    served = admin.get("/media/hero-1")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert served.content == PNG_1x1
    assert "immutable" in served.headers.get("cache-control", "")

    # The homepage overlays it onto the hero, with the alt text.
    home = admin.get("/")
    assert "/media/hero-1" in home.text
    assert "Annual sales conference" in home.text


def test_only_the_uploaded_slot_changes(admin):
    admin.post(
        "/admin/appearance",
        files={"photo_1": ("hero.png", PNG_1x1, "image/png")},
        data={"alt_1": "One", "alt_2": ""},
    )
    # hero-2 was never uploaded, so it has no media and keeps the placeholder.
    assert admin.get("/media/hero-2").status_code == 404
    home = admin.get("/")
    assert "/media/hero-1" in home.text
    assert "/media/hero-2" not in home.text
    assert "Your photo here" in home.text  # the empty slot's placeholder


def test_alt_text_can_be_updated_without_re_uploading(admin):
    admin.post(
        "/admin/appearance",
        files={"photo_1": ("hero.png", PNG_1x1, "image/png")},
        data={"alt_1": "First caption", "alt_2": ""},
    )
    admin.post("/admin/appearance", data={"alt_1": "Second caption", "alt_2": ""})
    home = admin.get("/")
    assert "Second caption" in home.text
    assert "First caption" not in home.text


# ── validation ───────────────────────────────────────────────────────────────

def test_non_image_upload_is_rejected(admin):
    response = admin.post(
        "/admin/appearance",
        files={"photo_1": ("notes.txt", b"not an image", "text/plain")},
        data={"alt_1": "", "alt_2": ""},
    )
    assert response.status_code == 400
    assert "JPG, PNG or WebP" in response.text
    assert admin.get("/media/hero-1").status_code == 404


def test_oversized_upload_is_rejected(admin, monkeypatch):
    monkeypatch.setattr("app.MAX_IMAGE_BYTES", 8)
    response = admin.post(
        "/admin/appearance",
        files={"photo_1": ("hero.png", PNG_1x1, "image/png")},
        data={"alt_1": "", "alt_2": ""},
    )
    assert response.status_code == 400
    assert "larger than" in response.text


# ── honest degradation with no database ──────────────────────────────────────

def test_appearance_page_explains_when_no_database(no_store):
    page = no_store.get("/admin/appearance")
    assert page.status_code == 200
    assert "No database connected" in page.text


def test_upload_without_a_database_reports_it(no_store):
    response = no_store.post(
        "/admin/appearance",
        files={"photo_1": ("hero.png", PNG_1x1, "image/png")},
        data={"alt_1": "x", "alt_2": ""},
    )
    assert response.status_code == 503
    assert "DATABASE_URL" in response.text


def test_homepage_shows_placeholder_without_a_store(no_store):
    home = no_store.get("/")
    assert "/media/hero-1" not in home.text
    assert "Your photo here" in home.text
