import pytest

import app as status_board
from app import check, create_app

SERVICES = [
    {"name": "alpha", "url": "http://alpha.test/healthz"},
    {"name": "beta", "url": "http://beta.test/healthz"},
]


@pytest.fixture
def client():
    up = {"http://alpha.test/healthz"}
    app = create_app(SERVICES, checker=lambda url: url in up)
    return app.test_client()


def test_healthz_reports_ok_and_version(client):
    body = client.get("/healthz").get_json()
    assert body["status"] == "ok"
    assert body["version"]


def test_version_comes_from_environment(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc123")
    body = create_app(SERVICES, checker=lambda url: True).test_client().get("/healthz").get_json()
    assert body["version"] == "abc123"


def test_version_comes_from_stamp_file(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    (tmp_path / "VERSION").write_text("def456\n")
    monkeypatch.setattr(status_board, "HERE", tmp_path)
    assert status_board.read_version() == "def456"


def test_version_falls_back_to_dev(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.setattr(status_board, "HERE", tmp_path)
    assert status_board.read_version() == "dev"


def test_api_status_lists_every_service(client):
    assert client.get("/api/status").get_json() == [
        {"name": "alpha", "up": True},
        {"name": "beta", "up": False},
    ]


def test_index_page_shows_up_and_down(client):
    html = client.get("/").get_data(as_text=True)
    assert "alpha: up" in html
    assert "beta: DOWN" in html


def test_default_services_load_from_config():
    names = [row["name"] for row in status_board.app.test_client().get("/api/status").get_json()]
    assert names == ["status-board", "invoice-check"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.test/", "not a url"])
def test_check_never_opens_non_http_urls(url):
    assert check(url) is False


def test_check_reports_unreachable_service_as_down():
    # Port 1 on localhost is closed: connection refused, no waiting.
    assert check("http://127.0.0.1:1/healthz", timeout=0.5) is False
