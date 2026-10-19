import json

from fastapi.testclient import TestClient

from app import create_app
from config import AppSettings
from services import ContentRepository


def test_application_factory_accepts_temporary_content_settings(tmp_path, monkeypatch):
    blog_dir = tmp_path / "blog"
    blog_dir.mkdir()
    (blog_dir / "test-post.json").write_text(
        json.dumps({
            "slug": "test-post", "title": "Test", "body_markdown": "# Safe",
            "tags": ["Test"], "author": "ETHPL Editorial Team", "publish_date": "2026-01-01",
            "read_time": "1 min", "hero_image": "/static/images/logo.png", "excerpt": "Test post",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("REDIRECT_BASE_URL", "https://www.ethpl.com")
    test_app = create_app(AppSettings(content_dir=tmp_path))
    with TestClient(test_app) as client:
        response = client.get("/blog/test-post")
    assert response.status_code == 200
    assert "Safe" in response.text


def test_corrupt_content_is_observable_and_deterministic(tmp_path, caplog):
    blog_dir = tmp_path / "blog"
    blog_dir.mkdir()
    (blog_dir / "broken.json").write_text("{not json", encoding="utf-8")
    repository = ContentRepository(blog_dir)
    with caplog.at_level("WARNING"):
        assert repository.all_posts() == []
    assert "broken.json" in caplog.text
    assert "JSONDecodeError" in caplog.text
