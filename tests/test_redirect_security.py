import pytest
from fastapi.testclient import TestClient

from app import app, validated_redirect_base_url


def test_redirect_encodes_values_once_and_cannot_inject_parameters(monkeypatch):
    monkeypatch.setenv("REDIRECT_BASE_URL", "https://www.ethpl.com")
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/redirect", params={"type": "group & vip", "id": "東京?x=1", "ref": "a+b&evil=1"})
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://www.ethpl.com/enquire?")
    assert "type=group+%26+vip" in location
    assert "id=%E6%9D%B1%E4%BA%AC%3Fx%3D1" in location
    assert "ref=a%2Bb%26evil%3D1" in location
    assert location.count("evil=") == 0


def test_redirect_rejects_controls_and_excessive_values(monkeypatch):
    monkeypatch.setenv("REDIRECT_BASE_URL", "https://www.ethpl.com")
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/redirect", params={"type": "bad\nvalue"}).status_code == 422
        assert client.get("/redirect", params={"id": "x" * 121}).status_code == 422


@pytest.mark.parametrize(
    "value",
    [
        "http://www.ethpl.com",
        "https://evil.example",
        "https://www.ethpl.com?next=evil",
        "https://user:pass@www.ethpl.com",
    ],
)
def test_redirect_base_rejects_unsafe_configuration(monkeypatch, value):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError):
        validated_redirect_base_url(value)
