import pytest
from fastapi.testclient import TestClient

from api import main
from src import data


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MARKET_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")
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


def test_52_week_range_does_not_shrink_with_the_series(client):
    short = client.get("/v1/quotes/VNM?days=5").json()
    full = client.get("/v1/quotes/VNM?days=250").json()
    assert len(short["series"]) == 5
    assert (short["high_52w"], short["low_52w"]) == (full["high_52w"], full["low_52w"])


def test_simulated_prices_are_refused_outside_demo_mode(client, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert client.get("/v1/quotes/NOSUCH").status_code == 404
    assert client.get("/v1/signals/NOSUCH").status_code == 404


def test_news_matches_only_items_that_name_the_symbol(client, monkeypatch):
    main.clear_cache()
    items = [
        {"source": "CafeF", "title": "VNM công bố cổ tức", "summary": "", "link": "https://x/1", "published": "t1"},
        {"source": "CafeF", "title": "Thị trường chung", "summary": "FPT tăng", "link": "https://x/2", "published": "t2"},
        {"source": "VnExpress", "title": "Giá vàng", "summary": "", "link": "https://x/3", "published": "t3"},
    ]
    monkeypatch.setattr(main.news, "fetch_news", lambda: items)

    body = client.get("/v1/news?symbols=vnm,FPT,vnm").json()

    assert [(i["symbol"], i["link"]) for i in body["items"]] == [("VNM", "https://x/1"), ("FPT", "https://x/2")]


def test_news_is_cached_and_rejects_bad_symbols(client, monkeypatch):
    main.clear_cache()
    calls = []
    monkeypatch.setattr(main.news, "fetch_news", lambda: calls.append(1) or [])
    client.get("/v1/news?symbols=VNM")
    client.get("/v1/news?symbols=FPT")
    assert len(calls) == 1
    assert client.get("/v1/news?symbols=a-b").status_code == 422
    assert client.get("/v1/news?symbols=,").status_code == 422


def test_brief_is_unavailable_without_an_llm(client, monkeypatch):
    main.clear_cache()
    monkeypatch.setattr(main.llm, "has_key", lambda: False)
    assert client.get("/v1/brief?symbols=VNM").status_code == 503


def test_brief_reshapes_the_model_answer_and_caches_it(client, monkeypatch):
    main.clear_cache()
    calls = []
    monkeypatch.setattr(main.llm, "has_key", lambda: True)
    monkeypatch.setattr(main.news, "fetch_news", lambda: [])
    monkeypatch.setattr(main.news, "fetch_global_snapshot", lambda: [])

    def fake(news_items, world, watch):
        calls.append(watch)
        return {"tong_quan": "Thị trường đi ngang.", "tin_quan_trong": [{"tieu_de": "A", "ma_lien_quan": ["VNM"], "tac_dong": "tich_cuc", "muc_do": "vua", "nhan_xet": "ok"}],
                "luu_y_danh_muc": [{"ma": "VNM", "nhan_xet": "yếu"}], "rui_ro_can_theo_doi": ["lãi suất"], "do_tin_cay_du_lieu": "vua"}

    monkeypatch.setattr(main.llm, "morning_brief", fake)

    first = client.get("/v1/brief?symbols=VNM").json()
    client.get("/v1/brief?symbols=VNM")

    assert first["overview"] == "Thị trường đi ngang."
    assert first["topNews"][0] == {"title": "A", "symbols": ["VNM"], "impact": "tich_cuc", "level": "vua", "comment": "ok"}
    assert first["notes"] == [{"symbol": "VNM", "comment": "yếu"}]
    assert "không phải lời khuyên" in first["disclaimer"]
    assert len(calls) == 1 and calls[0][0]["symbol"] == "VNM"


def test_brief_failure_is_a_502_not_a_leak(client, monkeypatch):
    main.clear_cache()
    monkeypatch.setattr(main.llm, "has_key", lambda: True)
    monkeypatch.setattr(main.news, "fetch_news", lambda: [])
    monkeypatch.setattr(main.news, "fetch_global_snapshot", lambda: [])
    monkeypatch.setattr(main.llm, "morning_brief", lambda *a: (_ for _ in ()).throw(RuntimeError("secret key abc")))
    response = client.get("/v1/brief?symbols=VNM")
    assert response.status_code == 502
    assert "secret" not in response.text


def test_assistant_answers_from_the_context_and_hides_failures(client, monkeypatch):
    monkeypatch.setattr(main.llm, "has_key", lambda: True)
    seen = []
    monkeypatch.setattr(main.llm, "assistant_answer", lambda q, c: seen.append((q, c)) or "Bạn tiêu nhiều nhất vào ăn uống.")
    ok = client.post("/v1/assistant", json={"question": " Tháng này tiêu gì nhiều? ", "context": "Ăn uống: 3.000.000"})
    assert ok.status_code == 200
    assert ok.json()["answer"].startswith("Bạn tiêu")
    assert "không phải lời khuyên" in ok.json()["disclaimer"]
    assert seen == [("Tháng này tiêu gì nhiều?", "Ăn uống: 3.000.000")]

    monkeypatch.setattr(main.llm, "assistant_answer", lambda q, c: (_ for _ in ()).throw(RuntimeError("secret key abc")))
    bad = client.post("/v1/assistant", json={"question": "x", "context": "y"})
    assert bad.status_code == 502 and "secret" not in bad.text


def test_assistant_validates_and_needs_an_llm(client, monkeypatch):
    assert client.post("/v1/assistant", json={"question": "", "context": "y"}).status_code == 422
    assert client.post("/v1/assistant", json={"question": "x", "context": "y" * 6001}).status_code == 422
    monkeypatch.setattr(main.llm, "has_key", lambda: False)
    assert client.post("/v1/assistant", json={"question": "x", "context": "y"}).status_code == 503
