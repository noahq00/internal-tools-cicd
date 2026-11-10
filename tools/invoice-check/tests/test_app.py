import pytest

import app as invoice_app


@pytest.fixture
def client():
    return invoice_app.create_app().test_client()


def test_healthz_reports_ok_and_version(client):
    body = client.get("/healthz").get_json()
    assert body["status"] == "ok"
    assert body["version"]


def test_version_comes_from_environment(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc123")
    assert invoice_app.read_version() == "abc123"


def test_version_comes_from_stamp_file(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    (tmp_path / "VERSION").write_text("def456\n")
    monkeypatch.setattr(invoice_app, "HERE", tmp_path)
    assert invoice_app.read_version() == "def456"


def test_version_falls_back_to_dev(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.setattr(invoice_app, "HERE", tmp_path)
    assert invoice_app.read_version() == "dev"


def test_check_returns_ok_for_a_correct_invoice(client):
    invoice = {"lines": [{"quantity": 2, "unit_price": "10", "vat_rate": "0.21"}], "total": "24.20"}
    assert client.post("/api/check", json=invoice).get_json() == {"ok": True, "findings": []}


def test_check_returns_findings_for_a_wrong_invoice(client):
    invoice = {"lines": [{"quantity": 2, "unit_price": "10", "vat_rate": "0.21"}], "total": "24.00"}
    body = client.post("/api/check", json=invoice).get_json()
    assert body["ok"] is False
    assert body["findings"] == [
        {"line": 0, "field": "total", "expected": "24.20", "actual": "24.00"}
    ]


def test_check_rejects_invalid_input_with_400(client):
    response = client.post("/api/check", data="not json", content_type="application/json")
    assert response.status_code == 400
    assert "lines" in response.get_json()["error"]
