import pytest
from fastapi.testclient import TestClient

from api import main
from src import data


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MARKET_API_KEY", raising=False)
    monkeypatch.setattr(data, "get_prices",
                        lambda symbol, days=400: (data.demo_prices(symbol, days), "demo"))
    return TestClient(main.app)


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_quote_shape_and_demo_flag(client):
    r = client.get("/v1/quotes/vnm?days=120")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "VNM" and body["demo"] is True
    assert len(body["series"]) == 120
    assert body["close"] == body["series"][-1]["close"]
    assert body["low_52w"] <= body["close"] <= body["high_52w"]


def test_signal_has_label_and_disclaimer(client):
    r = client.get("/v1/signals/FPT")
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["score"] <= 100
    assert body["label"] in {"Mạnh", "Khá", "Trung tính", "Yếu"}
    assert "không phải lời khuyên" in body["disclaimer"]


@pytest.mark.parametrize("bad", ["a-b", "x" * 11, "VN%20M"])
def test_invalid_symbol_rejected(client, bad):
    assert client.get(f"/v1/quotes/{bad}").status_code == 422


def test_position_size_ok_and_error(client):
    ok = client.post("/v1/risk/position-size",
                     json={"capital": 100_000_000, "entry": 50_000, "stop": 47_000})
    assert ok.status_code == 200
    body = ok.json()
    assert body["shares"] % 100 == 0 and body["max_loss_pct"] <= 0.015 + 1e-9
    bad = client.post("/v1/risk/position-size",
                      json={"capital": 100_000_000, "entry": 50_000, "stop": 51_000})
    assert bad.status_code == 422


def test_api_key_enforced_except_health(client, monkeypatch):
    monkeypatch.setenv("MARKET_API_KEY", "secret")
    assert client.get("/v1/health").status_code == 200
    assert client.get("/v1/quotes/VNM").status_code == 401
    assert client.get("/v1/quotes/VNM", headers={"X-Api-Key": "wrong"}).status_code == 401
    assert client.get("/v1/quotes/VNM", headers={"X-Api-Key": "secret"}).status_code == 200
