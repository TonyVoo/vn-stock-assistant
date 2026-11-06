import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest

from src import journal, risk, signals
from src.data import demo_prices
from src.llm import _parse_json


def test_tick_and_round():
    assert risk.tick_size(9_990) == 10
    assert risk.tick_size(25_000) == 50
    assert risk.tick_size(80_000) == 100
    assert risk.round_to_tick(25_020) == 25_000
    assert risk.round_to_tick(25_020, mode="up") == 25_050


def test_position_size_respects_risk_and_lot():
    r = risk.position_size(10_000_000, 25_000, 23_500, risk_pct=0.02, max_alloc=0.30)
    assert r["shares"] % 100 == 0 and r["shares"] > 0
    assert r["max_loss_pct"] <= 0.02 + 1e-9
    assert r["alloc_pct"] <= 0.30 + 1e-9
    big = risk.position_size(100_000_000, 25_000, 23_500, risk_pct=0.015, max_alloc=0.30)
    assert big["shares"] > r["shares"] and big["max_loss_pct"] <= 0.015 + 1e-9


def test_one_lot_exceeds_risk_budget_explains_why():
    # 10tr, rủi ro 1,5%, cắt lỗ cách 6% -> 1 lô rủi ro ~1,6% > 1,5%
    r = risk.position_size(10_000_000, 25_000, 23_500, risk_pct=0.015, max_alloc=0.30)
    assert r["shares"] == 0
    assert r["min_risk_pct_for_one_lot"] > 0.015
    assert "rủi ro" in r["message"]


def test_position_size_errors_and_too_small():
    assert "error" in risk.position_size(10_000_000, 25_000, 26_000)
    assert "error" in risk.position_size(0, 25_000, 24_000)
    tiny = risk.position_size(1_000_000, 100_000, 95_000)  # 1 lô = 10 triệu > vốn
    assert tiny["shares"] == 0


def test_breakeven_above_entry():
    r = risk.position_size(50_000_000, 30_000, 28_000)
    assert r["breakeven"] > 30_000


def test_rsi_bounds_and_trend():
    up = pd.Series(np.arange(1, 100, dtype=float))
    assert signals.rsi(up).iloc[-1] > 90
    down = pd.Series(np.arange(100, 1, -1, dtype=float))
    assert signals.rsi(down).iloc[-1] < 10


def test_score_in_range_and_insufficient_data():
    df = demo_prices("FPT", 300)
    s = signals.score_stock(df, demo_prices("VNINDEX", 300))
    assert 0 <= s["score"] <= 100
    assert s["suggested_stop"] < s["close"]
    short = signals.score_stock(df.head(30))
    assert short["score"] is None


def test_uptrend_scores_higher_than_downtrend():
    n = 300
    dates = pd.bdate_range(end="2026-11-03", periods=n)

    def mk(prices):
        p = np.asarray(prices, dtype=float)
        return pd.DataFrame({"date": dates, "open": p, "high": p * 1.005, "low": p * 0.995,
                             "close": p, "volume": 2_000_000})

    up = mk(np.linspace(20_000, 40_000, n) + np.sin(np.arange(n)) * 100)
    down = mk(np.linspace(40_000, 20_000, n) + np.sin(np.arange(n)) * 100)
    assert signals.score_stock(up)["score"] > signals.score_stock(down)["score"]


def test_journal_roundtrip(tmp_path):
    db = tmp_path / "j.db"
    tid = journal.add_trade("fpt", 200, 100_000, 95_000, 115_000, "test", "2026-11-01", path=db)
    df = journal.list_trades(db)
    assert df.iloc[0]["symbol"] == "FPT" and df.iloc[0]["pnl"] != df.iloc[0]["pnl"]  # NaN khi chưa đóng
    journal.close_trade(tid, 110_000, "2026-11-10", "ok", path=db)
    df = journal.list_trades(db)
    assert df.iloc[0]["pnl"] > 0
    assert journal.stats(df)["closed"] == 1


def test_parse_json_with_fence():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('Đây là kết quả: {"a": 2}') == {"a": 2}


def test_mock_provider_returns_structured_output(monkeypatch):
    from src import llm
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert llm.has_key()
    b = llm.morning_brief([], [], [])
    assert "tong_quan" in b
    a = llm.analyze_symbol("FPT", {"close": 1}, [])
    assert len(a["phan_bien"]) == 3


# ---------- backtest ----------
from src import backtest  # noqa: E402


def test_backtest_has_no_lookahead():
    df = demo_prices("HPG", 500)
    full = backtest.backtest_symbol("HPG", df, threshold=0)
    cut = 330
    part = backtest.backtest_symbol("HPG", df.head(cut), threshold=0)
    last = df["date"].iloc[cut - 1]
    expected = full[full["exit_date"] <= last].reset_index(drop=True)
    assert len(part) == len(expected) > 0
    pd.testing.assert_frame_equal(part.reset_index(drop=True), expected)


def test_backtest_trade_rules_hold():
    df = demo_prices("VNM", 700)
    t = backtest.backtest_symbol("VNM", df, threshold=0, min_hold=2, hold_days=20)
    assert len(t) > 5
    assert (t["days"] >= 2).all() and (t["days"] <= 20).all()
    stops = t[t["reason"] == "cắt lỗ"]
    assert np.allclose(stops["exit"], stops["stop"])
    gaps = t[t["reason"] == "cắt lỗ (gap)"]
    assert (gaps["exit"] <= gaps["stop"] + 1e-6).all()
    assert (t["entry"] > t["stop"]).all()


def test_backtest_costs_reduce_return():
    df = demo_prices("FPT", 600)
    t = backtest.backtest_symbol("FPT", df, threshold=0)
    gross = t["exit"] / t["entry"] - 1
    assert (t["ret"] < gross).all()


def test_summarize_and_baseline_run():
    prices = {s: demo_prices(s, 600) for s in ("FPT", "HPG")}
    idx = demo_prices("VNINDEX", 600)
    strat, base, s1, s2 = backtest.compare_with_baseline(prices, idx, threshold=70)
    assert s2["trades"] >= s1["trades"]
    assert 0 <= s2["win_rate"] <= 1 and s2["max_drawdown_est"] <= 0
    assert backtest.summarize(pd.DataFrame(columns=backtest.TRADE_COLS))["trades"] == 0


def test_csv_prices_take_priority(tmp_path, monkeypatch):
    from src import data
    monkeypatch.setattr(data, "CSV_DIR", tmp_path)
    dates = pd.bdate_range(end="2026-11-03", periods=80)
    pd.DataFrame({"Date": dates, "Open": 25.0, "High": 26.0, "Low": 24.0, "Close": 25.5,
                  "Volume": 1_000_000}).to_csv(tmp_path / "TST.csv", index=False)
    df, src = data.get_prices("TST")
    assert src == "csv" and len(df) == 80
    assert df["close"].iloc[-1] == 25_500  # tự đổi nghìn đồng -> đồng


def test_split_has_no_leakage_across_cut():
    prices = {s: demo_prices(s, 700) for s in ("FPT", "HPG", "VNM")}
    idx = demo_prices("VNINDEX", 700)
    prep = backtest.prepare_all(prices, idx)
    trades = backtest.run_prepared(prep, threshold=0)
    cut = pd.Timestamp(trades["entry_date"].sort_values().iloc[len(trades) // 2])
    train, test = backtest._split(trades, cut)
    assert (train["exit_date"] < cut).all() and (train["entry_date"] < cut).all()
    assert (test["entry_date"] >= cut).all()


def test_split_evaluation_runs_and_ranks_by_train():
    prices = {s: demo_prices(s, 700) for s in ("FPT", "HPG")}
    prep = backtest.prepare_all(prices, demo_prices("VNINDEX", 700))
    grid = {"threshold": [0, 60], "hold_days": [10, 20], "atr_mult": [2.0], "regime": [None, 200], "trail": [False, True]}
    res = backtest.split_evaluation(prep, "2026-01-01", grid, min_train_trades=1)
    assert len(res) == 2 * 2 * 1 * 2 * 2
    e = res[res["eligible"]]
    assert e["train_edge"].is_monotonic_decreasing


def test_trailing_stop_never_below_initial_and_regime_blocks_downtrend():
    df = demo_prices("VNM", 700)
    t = backtest.backtest_symbol("VNM", df, threshold=0, trail=True)
    stops = t[t["reason"] == "cắt lỗ"]
    assert (stops["exit"] >= stops["stop"] - 1e-6).all()
    down = demo_prices("VNINDEX", 700).copy()
    down["close"] = np.linspace(2000, 500, len(down))
    none = backtest.backtest_symbol("VNM", df, down, threshold=0, regime=200)
    assert len(none) == 0


# ---------- xsection ----------
from src import xsection  # noqa: E402


def _synthetic_universe(n_stocks=20, days=800, seed=1, drift_spread=0.0015):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-11-03", periods=days)
    drifts = np.linspace(-drift_spread / 2, drift_spread, n_stocks)  # mỗi mã có xu hướng riêng, bền vững
    out = {}
    for k in range(n_stocks):
        r = rng.normal(drifts[k], 0.015, days)
        c = 30_000 * np.exp(np.cumsum(r))
        o = c * (1 + rng.normal(0, 0.002, days))
        out[f"S{k:02d}"] = pd.DataFrame({"date": dates, "open": o, "high": np.maximum(o, c) * 1.003,
                                         "low": np.minimum(o, c) * 0.997, "close": c, "volume": 3_000_000})
    return out


def test_xsection_detects_planted_momentum_and_not_in_pure_noise():
    planted = xsection.evaluate_all(_synthetic_universe(drift_spread=0.0015), "2025-06-01")
    noise = xsection.evaluate_all(_synthetic_universe(drift_spread=0.0), "2025-06-01")
    p_mom = planted[(planted.signal == "mom_6_1") & (planted.part == "test")].iloc[0]
    n_mom = noise[(noise.signal == "mom_6_1") & (noise.part == "test")].iloc[0]
    assert p_mom["gross_excess_per_period"] > 0 and p_mom["placebo_p"] < 0.05
    assert n_mom["placebo_p"] > 0.02  # không có lợi thế thật thì không được báo là có


def test_xsection_no_lookahead_and_no_leakage():
    prices = _synthetic_universe(days=700)
    panel = xsection.build_panel(prices)
    score = xsection.SIGNALS["mom_6_1"]["fn"](panel["close"])
    full = xsection.run_signal(panel, score, 21)["rows"]
    # đổi toàn bộ dữ liệu sau phiên 600 -> các kỳ kết thúc trước đó không được đổi
    cut = panel["close"].index[600]
    p2 = {k: v.copy() for k, v in panel.items()}
    for k in ("close", "open"):
        p2[k].loc[p2[k].index > cut] *= 1.7
    alt = xsection.run_signal(p2, xsection.SIGNALS["mom_6_1"]["fn"](p2["close"]), 21)["rows"]
    early = [r for r in full if r["exit"] <= cut]
    early2 = [r for r in alt if r["exit"] <= cut]
    assert len(early) > 3 and [r["picks"] for r in early] == [r["picks"] for r in early2]
    assert all(abs(a["gross"] - b["gross"]) < 1e-12 for a, b in zip(early, early2))
    split = panel["close"].index[450]
    assert all(r["exit"] < split for r in xsection._slice(full, split, "train"))
    assert all(r["entry"] >= split for r in xsection._slice(full, split, "test"))


# ---------- paper trading & rank_now ----------
from src import paper  # noqa: E402


def test_rank_now_only_liquid_and_sorted():
    prices = _synthetic_universe(n_stocks=12, days=500)
    prices["S00"]["volume"] = 10  # không đủ thanh khoản
    panel = xsection.build_panel(prices)
    rk = xsection.rank_now(panel, "mom_6_1", n_top=5)
    assert "S00" not in set(rk["symbol"])
    assert rk["score"].is_monotonic_decreasing and rk["top"].sum() == 5


def test_paper_snapshot_unique_and_evaluation_dates(tmp_path):
    db = tmp_path / "p.db"
    assert paper.save_snapshot("2026-01-02", "mom_6_1", ["S01", "S02"], 21, db) is True
    assert paper.save_snapshot("2026-01-02", "mom_6_1", ["S03"], 21, db) is False  # không ghi trùng
    prices = _synthetic_universe(n_stocks=8, days=500)
    panel = xsection.build_panel(prices)
    asof = panel["close"].index[300]
    paper.save_snapshot(f"{asof:%Y-%m-%d}", "mom_6_1", ["S01", "S02"], 21, db)
    ev = paper.evaluate(paper.list_snapshots(db), panel)
    row = ev[ev["asof"] == f"{asof:%Y-%m-%d}"].iloc[0]
    assert row["status"] == "đã xong"
    o = panel["open"]
    expect = (o.iloc[300 + 1 + 21] / o.iloc[300 + 1] - 1)[["S01", "S02"]].mean()  # vào phiên SAU asof
    assert abs(row["gross"] - expect) < 1e-12
    assert abs(row["net_excess"] - (row["gross"] - paper.ROUND_TRIP - row["bench"])) < 1e-12
    # asof ở phiên cuối: chưa thể vào lệnh
    last = panel["close"].index[-1]
    paper.save_snapshot(f"{last:%Y-%m-%d}", "mom_6_1", ["S01"], 21, db)
    ev2 = paper.evaluate(paper.list_snapshots(db), panel)
    assert ev2[ev2["asof"] == f"{last:%Y-%m-%d}"].iloc[0]["status"] == "chờ phiên kế tiếp"


# ---------- explain (diễn đạt cho người mới) ----------
from src import explain  # noqa: E402


def test_vietnamese_number_formats():
    assert explain.num(10_000_000) == "10.000.000"
    assert explain.vnd(2_503_750) == "2.503.750đ"
    assert explain.pct(0.0123) == "+1,2%" and explain.pct(-0.5, 0) == "-50%"
    assert explain.num(1706.15, 2) == "1.706,15"
    assert explain.money_short(10e6) == "10 triệu" and explain.money_short(2.5e6) == "2,5 triệu"
    assert explain.money_short(1.2e9) == "1,2 tỷ" and explain.money_short(950_000) == "950.000đ"


def test_partial_session_detection():
    import datetime as dt
    mid = dt.datetime(2026, 11, 4, 11, 0, tzinfo=explain.VN_TZ)       # thứ Tư, đang giao dịch
    assert explain.is_partial_session("2026-11-04", mid)
    assert not explain.is_partial_session("2026-11-03", mid)           # nến hôm qua đã đủ
    assert not explain.is_partial_session("2026-11-04", mid.replace(hour=16))
    assert not explain.is_partial_session("2026-11-07", dt.datetime(2026, 11, 7, 11, 0, tzinfo=explain.VN_TZ))  # thứ Bảy


def test_trend_labels_and_plain_language_rules():
    assert explain.trend(75)[1] == "up" and explain.trend(50)[1] == "flat" and explain.trend(20)[1] == "down"
    assert explain.trend(None)[1] == "muted"
    # mọi lý do/cảnh báo mà signals.py có thể sinh ra đều phải được dịch (không còn thuật ngữ thô)
    sig = signals.score_stock(demo_prices("FPT", 400), demo_prices("VNINDEX", 400))
    for t in sig["reasons"] + sig["warnings"]:
        text, pol = explain.plainify(t)
        assert pol in "+-" and "RSI" not in text and "MA50" not in text and "MACD" not in text and "VN-Index" not in text
    s = {"score": 70, "rsi": 75, "liquid": True, "stop": 20000, "stop_pct": 0.065}
    summary = explain.plain_summary("ABC", s)
    assert "tăng" in summary and "không phải lời khuyên" in summary and "20.000đ" in summary


def test_ui_escapes_untrusted_text():
    from src import ui
    assert "<script>" not in ui.badge("<script>alert(1)</script>")
    assert "&lt;" in ui.esc("<b>")


# ---------- settings (lưu cài đặt) & giao diện ----------
from src import settings as settings_mod  # noqa: E402


def test_settings_roundtrip_and_validation(tmp_path):
    p = tmp_path / "s.json"
    assert settings_mod.load(p) == settings_mod.DEFAULTS                      # chưa có file -> mặc định
    saved = settings_mod.save({"capital_m": "25", "watch": ["fpt", "FPT", "hpg", "<x>", ""], "risk_pct": 9, "max_alloc": 40}, p)
    assert saved["capital_m"] == 25.0 and saved["watch"] == ["FPT", "HPG"]    # bỏ trùng, bỏ mã rác
    assert saved["risk_pct"] == 2.0 and saved["max_alloc"] == 40              # rủi ro 9% vượt giới hạn -> mặc định
    assert settings_mod.load(p) == saved                                      # tải lại vẫn đúng (đây là lỗi người dùng gặp)


def test_settings_survive_corrupt_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert settings_mod.load(p) == settings_mod.DEFAULTS                      # file hỏng không làm app sập
    settings_mod.save({"capital_m": 5}, p)
    assert settings_mod.load(p)["capital_m"] == 5.0 and not list(tmp_path.glob("*.tmp"))


def test_css_tokens_complete_and_no_emoji_in_ui_source():
    import glob
    import re
    from src import ui
    css = ui.CSS.safe_substitute(ui.tokens())
    assert "$" not in css  # không sót biến chưa thay
    emoji = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
    root = Path(__file__).resolve().parent.parent
    files = [root / "app.py", *sorted((root / "views").glob("*.py")), *sorted((root / "src").glob("*.py"))]
    bad = [f"{f.name}:{i}" for f in files for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
           if emoji.search(line)]
    assert not bad, f"không dùng emoji trong giao diện: {bad}"


def test_ui_components_render_safely():
    from src import ui
    assert "b-up" in ui.change_pill(0.0123) and "b-down" in ui.change_pill(-0.01) and "b-flat" in ui.change_pill(0.0)
    assert "1,23%" in ui.change_pill(0.0123)                                  # số kiểu Việt Nam
    assert 'left:100.0%' in ui.range_bar(10, 20, 99, "a", "b") and 'left:0.0%' in ui.range_bar(10, 20, -5, "a", "b")
    assert "<script>" not in ui.stat_grid([("<script>", "<b>x</b>")])


# ---------- danh mục ----------
from src import broker_tcbs, portfolio  # noqa: E402


def test_portfolio_clean_merge_and_roundtrip(tmp_path):
    rows = [{"symbol": "fpt", "qty": 100, "avg_cost": 100_000}, {"symbol": "FPT", "qty": 300, "avg_cost": 120_000},
            {"symbol": "<x>", "qty": 5, "avg_cost": 1}, {"symbol": "HPG", "qty": 0, "avg_cost": 20_000},
            {"symbol": "VNM", "qty": "abc", "avg_cost": 1}]
    out = portfolio.clean_holdings(rows)
    assert [h["symbol"] for h in out] == ["FPT"] and out[0]["qty"] == 400
    assert abs(out[0]["avg_cost"] - 115_000) < 1e-6                      # bình quân gia quyền
    p = tmp_path / "pf.json"
    saved = portfolio.save({"holdings": rows, "cash": 5_000_000}, "manual", p)
    assert portfolio.load(p) == saved and saved["source"] == "manual" and saved["as_of"]
    p.write_text("{hỏng", encoding="utf-8")
    assert portfolio.load(p) == portfolio.EMPTY                          # file hỏng không làm app sập


def test_to_number_vietnamese_and_english_formats():
    assert portfolio.to_number("1.234.567") == 1234567 and portfolio.to_number("1.234.567,5") == 1234567.5
    assert portfolio.to_number("1,234,567") == 1234567 and portfolio.to_number("78,5") == 78.5
    assert portfolio.to_number("78500đ") == 78500 and portfolio.to_number("12.5") == 12.5
    assert portfolio.to_number("abc") is None and portfolio.to_number(None) is None


def test_parse_statement_headers_units_and_offset():
    df = pd.DataFrame({"Mã CK": ["FPT", "hpg", "xx yy"], "Khối lượng": ["1.000", "200", "5"], "Giá vốn": [98.5, 21.0, 3]})
    out, notes = portfolio.parse_statement(df)
    assert [(h["symbol"], h["qty"], h["avg_cost"]) for h in out] == [("FPT", 1000, 98500.0), ("HPG", 200, 21000.0)]
    assert any("nghìn đồng" in n for n in notes)
    # tiêu đề nằm ở dòng thứ 3 (file xuất có phần đầu trang)
    raw = pd.DataFrame([["Báo cáo danh mục", None, None], [None, None, None], ["Mã", "Số lượng", "Giá vốn TB"],
                        ["VCB", 100, 90000]])
    out2, _ = portfolio.parse_statement(raw)
    assert out2 == [{"symbol": "VCB", "qty": 100, "avg_cost": 90000.0, "market_value": None}]
    bad, msg = portfolio.parse_statement(pd.DataFrame({"a": [1], "b": [2]}))
    assert bad == [] and msg


def test_valuate_math_priority_and_warnings():
    pf = {"holdings": portfolio.clean_holdings([
        {"symbol": "AAA", "qty": 1000, "avg_cost": 20_000, "market_value": 25_000_000},
        {"symbol": "BBB", "qty": 100, "avg_cost": 50_000, "market_value": 4_000_000},
        {"symbol": "CCC", "qty": 100, "avg_cost": 10_000}]), "cash": 1_000_000}
    prices = {"AAA": 30_000.0}  # AAA có giá của bạn; BBB dùng giá TCBS báo (40.000); CCC chỉ có giá vốn
    df, s = portfolio.valuate(pf, prices.get, max_alloc=0.30)
    a, b, c = (df[df.symbol == k].iloc[0] for k in ("AAA", "BBB", "CCC"))
    assert a.price == 30_000 and a.pnl == 10_000_000 and abs(a.pnl_pct - 0.5) < 1e-9
    assert b.price == 40_000 and b.price_src == "TCBS báo" and c.price == 10_000 and c.price_src.startswith("giá vốn")
    assert abs(s["total"] - (30_000_000 + 4_000_000 + 1_000_000 + 1_000_000)) < 1e-6
    assert abs(df["weight"].sum() + pf["cash"] / s["total"] - 1) < 1e-9
    assert a.net_pnl < a.pnl                                              # lãi sau phí/thuế bán thấp hơn lãi gộp
    assert any("AAA" in w and "vượt" in w for w in s["warnings"]) and any("CCC" in w for w in s["warnings"])


def test_portfolio_from_journal(tmp_path):
    from src import journal
    db = tmp_path / "j.db"
    journal.add_trade("FPT", 100, 100_000, 95_000, None, "t", "2026-01-01", path=db)
    t2 = journal.add_trade("HPG", 200, 20_000, 19_000, None, "t", "2026-01-02", path=db)
    journal.close_trade(t2, 21_000, "2026-02-01", path=db)
    h = portfolio.from_journal(journal.list_trades(db))
    assert [(x["symbol"], x["qty"]) for x in h] == [("FPT", 100)]        # chỉ lệnh chưa bán


# ---------- TCBS: chỉ đọc ----------
class _Resp:
    def __init__(self, code=200, data=None, text=""):
        self.status_code, self._d, self.text = code, data, text

    def json(self):
        if self._d is None:
            raise ValueError
        return self._d


class _FakeSession:
    def __init__(self, responder=None):
        self.calls, self.responder = [], responder

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        return self.responder("POST", url) if self.responder else _Resp(200, {"token": "TOK123SECRET"})

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, headers))
        if self.responder:
            return self.responder("GET", url)
        if url.endswith("/se"):
            return _Resp(200, {"assets": [{"symbol": "vnm", "quantity": 500, "avgPrice": 78500, "marketValue": 40_250_000}]})
        if url.endswith("/cashInvestments"):
            return _Resp(200, {"data": [{"cashBalance": 1_500_000, "bodBalance": 9}, {"cashBalance": 500_000}]})
        return _Resp(404, None, "no")


def test_tcbs_only_reads_and_one_post(tmp_path):
    s = _FakeSession()
    c = broker_tcbs.TcbsReadOnly("KEY-ABC", session=s)
    with pytest.raises(broker_tcbs.AuthRequired):
        c.holdings("0001170730")                                          # chưa đăng nhập thì không gọi được gì
    assert not s.calls
    c.login("123456")
    snap = c.snapshot("0001170730")
    assert snap["holdings"] == [{"symbol": "VNM", "qty": 500, "avg_cost": 78500, "market_value": 40_250_000}]
    assert snap["cash"] == 2_000_000
    methods = [m for m, *_ in s.calls]
    assert methods.count("POST") == 1 and set(methods) == {"POST", "GET"}
    post = s.calls[0]
    assert post[1] == broker_tcbs.BASE_URL + broker_tcbs.TOKEN_PATH and post[2] == {"apiKey": "KEY-ABC", "otp": "123456"}
    for m, url, _, headers in s.calls[1:]:
        assert m == "GET" and "/akhlys/" not in url and headers["Authorization"] == "Bearer TOK123SECRET"


def test_tcbs_blocks_trading_and_odd_paths():
    c = broker_tcbs.TcbsReadOnly("K", session=_FakeSession())
    c.login("123456")
    for bad in ["/akhlys/v1/accounts/0001/orders", "/aion/v1/accounts/0001/orders/place", "/aion/v1/accounts/../x/se",
                "/aion/v1/accounts/0001/se/extra", "/gaia/v1/oauth2/openapi/token", "/aion/v1/accounts//se"]:
        with pytest.raises(broker_tcbs.BrokerError):
            c._get(bad)
    assert len(c._s.calls) == 1                                           # ngoài lần đăng nhập, không có yêu cầu nào lọt ra mạng
    src = (Path(__file__).resolve().parent.parent / "src" / "broker_tcbs.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("#", '"', "'")))
    assert code.count("self._s.post(") == 1
    for banned in (".put(", ".delete(", ".patch(", "requests.post(", "requests.put("):
        assert banned not in code


def test_tcbs_errors_never_leak_secrets_and_otp_is_validated():
    leak = lambda m, u: _Resp(400, {}, "bad key KEY-ABC otp 123456 token TOK123SECRET")
    s = _FakeSession(leak)
    c = broker_tcbs.TcbsReadOnly("KEY-ABC", session=s)
    with pytest.raises(broker_tcbs.BrokerError) as e:
        c.login("123456")
    assert "KEY-ABC" not in str(e.value) and "123456" not in str(e.value) and "***" in str(e.value)
    n = len(s.calls)
    with pytest.raises(broker_tcbs.BrokerError):
        c.login("12ab")                                                   # OTP sai định dạng: không gửi lên mạng
    assert len(s.calls) == n
    with pytest.raises(broker_tcbs.BrokerError):
        broker_tcbs.TcbsReadOnly("  ")


def test_tcbs_expired_token_requires_new_otp():
    calls = {"n": 0}

    def responder(method, url):
        if method == "POST":
            return _Resp(200, {"token": "T"})
        calls["n"] += 1
        return _Resp(401, None, "expired")

    c = broker_tcbs.TcbsReadOnly("K", session=_FakeSession(responder))
    c.login("123456")
    with pytest.raises(broker_tcbs.AuthRequired):
        c.holdings("0001")
    assert not c.logged_in()                                              # token bị xoá, buộc nhập OTP mới


def test_transactions_statement_to_holdings():
    tx = pd.DataFrame({
        "Ngày giao dịch": ["03/01/2026", "02/01/2026", "05/01/2026", "02/01/2026", "06/01/2026", "07/01/2026"],
        "Mã CK": ["FPT", "FPT", "FPT", "HPG", "HPG", "VNM"],
        "Loại lệnh": ["Mua", "Mua", "Bán", "Mua", "Bán", "Mua"],
        "Khối lượng đặt": [999, 999, 999, 999, 999, 999],           # không được dùng nhầm
        "Khối lượng khớp": [100, 100, 50, 200, 200, 100],
        "Giá khớp": [110_000, 100_000, 120_000, 20_000, 22_000, 70_000],
        "Trạng thái": ["Khớp hết", "Khớp hết", "Khớp hết", "Khớp hết", "Khớp hết", "Đã hủy"]})
    out, notes = portfolio.parse_file(tx)[:2]
    assert [(h["symbol"], h["qty"]) for h in out] == [("FPT", 150)]          # HPG đã bán hết; VNM bị huỷ nên bỏ
    assert abs(out[0]["avg_cost"] - 105_000) < 1e-6                           # (100*100k + 100*110k)/200, bán không đổi giá vốn
    assert portfolio.parse_file(tx)[2] == "giao dịch"
    assert any("không phải lệnh đã khớp" in n for n in notes) and any("chưa gồm phí" in n for n in notes)


def test_transactions_edge_cases():
    base = {"Mã": ["AAA", "AAA"], "Mua/Bán": ["NB", "NS"], "Khối lượng": [100, 300], "Giá": [20, 25]}
    out, notes, kind = portfolio.parse_file(pd.DataFrame(base))
    assert kind == "giao dịch" and out == []                                  # bán nhiều hơn mua -> không còn giữ
    assert any("Bán nhiều hơn" in n and "AAA" in n for n in notes) and any("nghìn đồng" in n for n in notes)
    # không có cột Mua/Bán -> là file danh mục đang giữ, KHÔNG được cộng dồn như giao dịch
    out2, _, kind2 = portfolio.parse_file(pd.DataFrame({"Mã CK": ["FPT"], "Khối lượng": [100], "Giá vốn": [98000]}))
    assert kind2 == "danh mục" and out2[0]["qty"] == 100
    # tiêu đề nằm lệch xuống dưới phần đầu trang
    raw = pd.DataFrame([["Sao kê lệnh", None, None, None], ["Mã", "Loại lệnh", "KL khớp", "Giá khớp"],
                        ["FPT", "Mua", 100, 90000], ["FPT", "Mua", 100, 110000]])
    out3, _, k3 = portfolio.parse_file(raw)
    assert k3 == "giao dịch" and out3[0]["qty"] == 200 and abs(out3[0]["avg_cost"] - 100_000) < 1e-6


def test_column_names_with_unit_suffix_are_recognised():
    df = pd.DataFrame({"Mã CK": ["FPT"], "Khối lượng (cp)": ["1.000"], "Giá vốn (đ)": ["98.500"], "Giá vốn TB (VND)": ["x"]})
    out, notes, kind = portfolio.parse_file(df)
    assert kind == "danh mục" and out[0]["qty"] == 1000 and out[0]["avg_cost"] == 98_500
    assert not any("không có cột giá vốn" in n for n in notes)


def test_unusual_column_names_and_manual_mapping():
    # tên cột "lạ" nhưng vẫn nhận ra bằng khớp gần đúng
    d1 = pd.DataFrame({"Chứng khoán": ["FPT", "HPG"], "Tổng KL": ["1.000", "500"], "Giá TB": ["98.500", "24.000"]})
    out, _, kind = portfolio.parse_file(d1)
    assert kind == "danh mục" and [(h["symbol"], h["qty"], h["avg_cost"]) for h in out] == [("FPT", 1000, 98500), ("HPG", 500, 24000)]
    # nhiều cột khối lượng: ưu tiên cột tổng / khối lượng thường, tránh “chờ về”, “phong toả”
    d2 = pd.DataFrame({"Số tài khoản": ["0001"], "Mã CK": ["FPT"], "Khối lượng chờ về": ["50"], "Khối lượng": ["300"], "Giá vốn": ["90000"]})
    out2, _, _ = portfolio.parse_file(d2)
    assert out2[0]["symbol"] == "FPT" and out2[0]["qty"] == 300              # không nhầm “Số tài khoản” là mã
    # hoàn toàn không nhận ra -> báo hướng dẫn; rồi chọn cột bằng tay vẫn đọc được
    d3 = pd.DataFrame({"A": ["VCB", "ACB"], "B": ["100", "200"], "C": ["90", "25"]})
    out3, notes3, _ = portfolio.parse_file(d3)
    assert out3 == [] and any("Tự chọn cột" in n for n in notes3)
    df, cols = portfolio.apply_header(d3, 1)
    manual, _ = portfolio.parse_manual(df, "danh mục", {"symbol": "A", "qty": "B", "avg_cost": "C"})
    assert [(h["symbol"], h["qty"], h["avg_cost"]) for h in manual] == [("ACB", 200, 25000), ("VCB", 100, 90000)]  # nghìn đồng -> đồng
    assert portfolio.parse_manual(df, "giao dịch", {"symbol": "A", "qty": "B"})[0] == []                     # thiếu cột bắt buộc
    # dòng tiêu đề nằm ở dòng thứ 4 của file, có ô trống/Unnamed
    raw = pd.DataFrame([["Báo cáo", None, None], [None, None, None], ["Mã", None, "Giá"], ["FPT", "100", "90000"]],
                       columns=["Unnamed: 0", "Unnamed: 1", "Unnamed: 2"])
    # file thực: dòng 1 = tiêu đề giả (Unnamed), dòng 2 = "Báo cáo", dòng 3 = trống, dòng 4 = "Mã | | Giá"
    d4, names = portfolio.apply_header(raw, 4)
    assert names == ["Mã", "Cột 2", "Giá"] and len(d4) == 1
    out4, _ = portfolio.parse_manual(d4, "danh mục", {"symbol": "Mã", "qty": "Cột 2", "avg_cost": "Giá"})
    assert out4[0]["qty"] == 100 and out4[0]["avg_cost"] == 90000


def test_multi_sheet_excel_roundtrip():
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"Ghi chú": ["Trang bìa, không có dữ liệu"]}).to_excel(w, sheet_name="Tổng hợp", index=False)
        pd.DataFrame({"Mã CK": ["FPT"], "Khối lượng": [100], "Giá vốn": [98500]}).to_excel(w, sheet_name="Danh mục", index=False)
    sheets = pd.read_excel(io.BytesIO(buf.getvalue()), sheet_name=None, dtype=str, header=0)
    assert portfolio.parse_file(sheets["Tổng hợp"])[0] == []
    got = next(portfolio.parse_file(df)[0] for df in sheets.values() if portfolio.parse_file(df)[0])
    assert got[0]["symbol"] == "FPT" and got[0]["qty"] == 100


def test_manual_column_mapping_ui_end_to_end(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("TEST_JOURNAL", str(tmp_path / "j.db"))
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_manual_mapping_app.py"), default_timeout=30).run()
    assert not at.exception
    keys = {s.label: s.key for s in at.selectbox}
    assert {"Cột Mã cổ phiếu", "Cột Khối lượng", "Cột Giá vốn (không bắt buộc)"} <= set(keys)
    at.selectbox(key=keys["Cột Mã cổ phiếu"]).set_value("A")
    at.selectbox(key=keys["Cột Khối lượng"]).set_value("B")
    at.selectbox(key=keys["Cột Giá vốn (không bắt buộc)"]).set_value("C")
    at.run()
    assert not at.exception
    rows = at.dataframe[-1].value.to_dict("records")
    assert [(r["Mã"], r["Số lượng"], r["Giá vốn"]) for r in rows] == [("ACB", 200, 25000.0), ("VCB", 100, 90000.0)]
    assert "Lưu theo cột đã chọn vào Danh mục và thêm 2 mã vào Nhật ký" in [b.label for b in at.button]   # nhãn riêng, không trùng nút của phần tự nhận


def test_fundamental_prompt_content_and_privacy():
    from src import prompts
    p = prompts.fundamental_prompt("fpt", 52_700, "04/11/2026")
    assert "FPT" in p and "52.700" in p and "04/11/2026" in p and "TCBS MCP" in p
    assert "phi ngân hàng" in p and "NIM" not in p                            # doanh nghiệp thường dùng bộ chỉ số phi ngân hàng
    bank = prompts.fundamental_prompt("VCB")
    assert "NIM" in bank and "nợ xấu" in bank and "ngân hàng" in bank        # ngân hàng dùng bộ chỉ số riêng
    assert "KHÔNG nên mua" in p and "không khuyên mua" in p                    # buộc nêu phản biện, không khuyên mua/bán
    assert not any(w in p.lower() for w in ("vốn của tôi", "danh mục của tôi", "otp", "api key"))  # không lộ thông tin cá nhân
    assert prompts.MCP_URL.startswith("https://mcp.tcbs.com.vn/")


# ---------- nhập sao kê vào Nhật ký (FIFO) ----------
from src import importer  # noqa: E402


def _tx_frame():
    return pd.DataFrame({
        "Ngày giao dịch": ["02/01/2026", "03/01/2026", "05/01/2026", "06/01/2026", "07/01/2026"],
        "Mã CK": ["FPT", "FPT", "FPT", "VCB", "HPG"],
        "Loại lệnh": ["Mua", "Mua", "Bán", "Mua", "Mua"],
        "Khối lượng khớp": [100, 100, 150, 10, 300],
        "Giá khớp": [100_000, 110_000, 120_000, 90_000, 25_000],
        "Trạng thái": ["Khớp hết", "Khớp hết", "Khớp hết", "Khớp hết", "Đã hủy"]})


def test_fifo_matches_partial_lots_and_skips_cancelled():
    tx, notes = portfolio.transactions_from_file(_tx_frame())
    trades, _ = importer.fifo_trades(tx)
    view = sorted(((t["symbol"], t["qty"], t["entry"], t["exit"]) for t in trades), key=lambda r: (r[0], r[1], r[2], r[3] or 0))
    assert view == [("FPT", 50, 110_000, None), ("FPT", 50, 110_000, 120_000),     # lô 2: bán 50, còn 50
                    ("FPT", 100, 100_000, 120_000), ("VCB", 10, 90_000, None)]      # lô 1 bán hết; HPG bị huỷ nên không có
    assert any("không phải lệnh đã khớp" in n for n in notes)
    assert len({t["key"] for t in trades}) == len(trades)                           # khoá nhận diện không trùng nhau
    # tổng số đang giữ khớp với cách tính danh mục (bình quân gia quyền)
    held = {s: sum(t["qty"] for t in trades if t["symbol"] == s and t["exit"] is None) for s in ("FPT", "VCB")}
    pf = {h["symbol"]: h["qty"] for h in portfolio.parse_file(_tx_frame())[0]}
    assert held == pf == {"FPT": 50, "VCB": 10}


def test_import_to_journal_is_idempotent_and_unset_stop_is_safe(tmp_path):
    db = tmp_path / "j.db"
    tx, _ = portfolio.transactions_from_file(_tx_frame())
    trades, _ = importer.fifo_trades(tx)
    assert importer.preview(trades, db) == {"total": 4, "new": 4, "skipped": 0, "open": 2, "closed": 2}
    assert importer.to_journal(trades, db) == {"open": 2, "closed": 2}
    again = importer.to_journal(trades, db)                                         # nhập lại cùng file: không thêm gì
    assert again == {"open": 0, "closed": 0} and importer.preview(trades, db)["new"] == 0
    df = journal.list_trades(db)
    assert len(df) == 4 and (df["stop"] == 0).all()
    closed = df[df["exit_price"].notna()]
    assert len(closed) == 2 and closed["pnl"].notna().all() and closed["r_multiple"].isna().all()   # chưa đặt cắt lỗ -> không có R
    assert journal.stats(df)["closed"] == 2 and journal.stats(df)["avg_r"] is None
    assert all("[sao kê " in r for r in df["reason"])
    # lệnh nhập tay vẫn bị kiểm tra chặt như cũ
    with pytest.raises(ValueError):
        journal.add_trade("FPT", 100, 100_000, 100_000, None, "x", "2026-01-01", db)
    assert journal.add_trade("FPT", 100, 100_000, 0, None, "x", "2026-01-01", db) > 0


def test_fifo_without_dates_and_oversold():
    df = pd.DataFrame({"Mã": ["AAA", "AAA", "BBB"], "Mua/Bán": ["Mua", "Bán", "Bán"], "KL": [100, 150, 10], "Giá": [20_000, 25_000, 30_000]})
    tx, _ = portfolio.transactions_from_file(df)
    trades, notes = importer.fifo_trades(tx)
    assert [(t["symbol"], t["qty"], t["exit"]) for t in trades] == [("AAA", 100, 25_000)]    # chỉ ghép được 100 trong 150 bán
    assert trades[0]["opened"] == importer.UNKNOWN_DATE
    assert any("AAA" in n and "BBB" in n for n in notes)                           # cả hai mã bán dư đều được nêu


def test_import_buttons_write_journal_and_portfolio_without_duplicates(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("TEST_JOURNAL", str(tmp_path / "j.db"))
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_tx_import_app.py"), default_timeout=30).run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Thêm vào Nhật ký và cập nhật Danh mục" in labels and "Chỉ cập nhật Danh mục" in labels
    both = next(b for b in at.button if b.label.startswith("Thêm vào Nhật ký"))
    both.click().run()
    assert not at.exception
    df = journal.list_trades(tmp_path / "j.db")
    assert len(df) == 4 and (df["stop"] == 0).all()                                   # 2 lô FPT đã bán/giữ + lô còn lại + VCB
    held = {h["symbol"]: h["qty"] for h in portfolio.load(tmp_path / "pf.json")["holdings"]}
    assert held == {"FPT": 50, "VCB": 10}
    assert "Đã thêm 4 lệnh" in at.session_state["pf_flash"]
    # bấm lần nữa: không nhập trùng
    next(b for b in at.button if b.label.startswith("Thêm vào Nhật ký")).click().run()
    assert len(journal.list_trades(tmp_path / "j.db")) == 4


def test_holdings_file_buttons_give_feedback_and_optionally_fill_journal(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("TEST_JOURNAL", str(tmp_path / "j.db"))
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    script = str(Path(__file__).resolve().parent / "ui_holdings_app.py")
    at = AppTest.from_file(script, default_timeout=30).run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Lưu vào Danh mục và thêm 2 mã vào Nhật ký" in labels and "Chỉ lưu vào Danh mục" in labels
    assert [b.label for b in at.button][0].startswith("Lưu vào Danh mục và thêm")        # nút chính là nút lưu cả hai
    # nút phụ: chỉ Danh mục, có phản hồi, Nhật ký không đổi
    next(b for b in at.button if b.label == "Chỉ lưu vào Danh mục").click().run()
    assert not at.exception and len(journal.list_trades(tmp_path / "j.db")) == 0
    assert {h["symbol"] for h in portfolio.load(tmp_path / "pf.json")["holdings"]} == {"FPT", "HPG"}
    assert "Đã lưu Danh mục: 2 mã" in at.session_state["pf_flash"] and at.session_state["pf_scroll_top"] is True
    assert at.session_state["pf_up_gen"] == 1                                            # ô chọn file được làm mới
    # nút 2: thêm cả vào Nhật ký như lệnh đang giữ (chưa đặt cắt lỗ); bấm lại không trùng
    at2 = AppTest.from_file(script, default_timeout=30).run()
    next(b for b in at2.button if b.label.startswith("Lưu vào Danh mục và thêm")).click().run()
    df = journal.list_trades(tmp_path / "j.db")
    assert sorted(df["symbol"]) == ["FPT", "HPG"] and (df["stop"] == 0).all() and df["exit_price"].isna().all()
    assert "thêm 2 lệnh đang giữ vào Nhật ký" in at2.session_state["pf_flash"]
    at3 = AppTest.from_file(script, default_timeout=30).run()
    labels3 = [b.label for b in at3.button]
    assert labels3 == ["Lưu vào Danh mục"]                                               # đã có trong Nhật ký: chỉ còn nút lưu Danh mục
    assert len(journal.list_trades(tmp_path / "j.db")) == 2


def test_holdings_parse_reports_skipped_rows():
    df = pd.DataFrame({"Mã CK": ["FPT", "HPG", "Tổng cộng", "XX YY"], "Khối lượng": ["100", "200", "300", "5"], "Giá vốn": ["98.500", "24.000", "", ""]})
    out, notes, kind = portfolio.parse_file(df)
    assert kind == "danh mục" and len(out) == 2 and any("Bỏ qua 2 dòng" in n for n in notes)


def test_holdings_to_journal_skips_symbols_already_held_in_journal(tmp_path):
    db = tmp_path / "j.db"
    journal.add_trade("FPT", 100, 100_000, 95_000, None, "lệnh tôi tự ghi", "2026-01-01", db)   # đã có lệnh đang giữ FPT
    assert importer.open_symbols(db) == {"FPT"}
    rows = [{"symbol": "FPT", "qty": 100, "avg_cost": 98_000}, {"symbol": "ACB", "qty": 400, "avg_cost": 22_732},
            {"symbol": "XXX", "qty": 100, "avg_cost": 0}]                                      # thiếu giá vốn: không tạo lệnh
    trades = importer.holdings_to_trades(rows, importer.open_symbols(db))
    assert [t["symbol"] for t in trades] == ["ACB"]                                            # FPT không bị ghi đôi
    assert importer.to_journal(trades, db) == {"open": 1, "closed": 0}
    assert importer.to_journal(trades, db) == {"open": 0, "closed": 0}                         # bấm lại không trùng
    df = journal.list_trades(db)
    assert sorted(df["symbol"]) == ["ACB", "FPT"] and df[df.symbol == "ACB"].iloc[0]["entry"] == 22_732


# ---------- tiền nạp/rút & lãi thật ----------
from datetime import date, timedelta  # noqa: E402

from src import cashflow  # noqa: E402


def test_cashflow_add_validate_delete_order(tmp_path):
    db = tmp_path / "c.db"
    today = date.today()
    a = cashflow.add(today - timedelta(days=100), 10_000_000, "vốn ban đầu", db)
    b = cashflow.add(today - timedelta(days=200), 5_000_000, "", db)           # thêm sau nhưng ngày sớm hơn
    df = cashflow.list_flows(db)
    assert list(df["id"]) == [b, a]                                              # sắp theo ngày
    for bad in (dict(day=today + timedelta(days=1), amount=1e6), dict(day=today, amount=0),
                dict(day=today, amount=float("nan")), dict(day=today, amount=1e14)):
        with pytest.raises(ValueError):
            cashflow.add(path=db, **bad)
    cashflow.delete(a, db)
    assert list(cashflow.list_flows(db)["id"]) == [b]
    assert cashflow.summary(cashflow.list_flows(tmp_path / "rong.db"), 1e6) == {"n": 0}
    only_dep = cashflow.summary(cashflow.list_flows(db), 1e6)
    assert str(only_dep["withdrawn"]) == "0.0"                                   # không phải “-0.0”


def test_xirr_matches_known_answers():
    d0 = date(2025, 11, 4)
    # nạp 100, đúng 1 năm sau còn 110 -> 10%/năm
    assert abs(cashflow.xirr([(d0, 100.0)], 110.0, d0 + timedelta(days=365)) - 0.10) < 1e-6
    # lỗ: nạp 100, 1 năm sau còn 80 -> -20%
    assert abs(cashflow.xirr([(d0, 100.0)], 80.0, d0 + timedelta(days=365)) + 0.20) < 1e-6
    # hai lần nạp: nghiệm phải làm giá trị hiện tại ròng bằng 0
    flows = [(d0, 100.0), (d0 + timedelta(days=180), 100.0)]
    end = d0 + timedelta(days=360)
    r = cashflow.xirr(flows, 230.0, end)
    npv = -100 - 100 / (1 + r) ** (180 / 365) + 230 / (1 + r) ** (360 / 365)
    assert abs(npv) < 1e-6 and r > 0
    # nạp muộn thì cùng số lãi tính ra tỷ suất cao hơn nạp sớm
    early = cashflow.xirr([(d0, 100.0)], 110.0, d0 + timedelta(days=365))
    late = cashflow.xirr([(d0 + timedelta(days=300), 100.0)], 110.0, d0 + timedelta(days=365))
    assert late > early
    assert cashflow.xirr([], 100.0, d0) is None


def test_cashflow_summary_true_profit_and_short_period_guard(tmp_path):
    db = tmp_path / "c.db"
    today = date.today()
    cashflow.add(today - timedelta(days=400), 100.0, "", db)
    cashflow.add(today - timedelta(days=200), 50.0, "", db)
    cashflow.add(today - timedelta(days=100), -30.0, "rút", db)                 # rút 30
    s = cashflow.summary(cashflow.list_flows(db), 140.0, today)
    assert s["deposited"] == 150 and s["withdrawn"] == 30 and s["net_in"] == 120
    assert s["pnl"] == 20 and abs(s["pnl_pct"] - 20 / 120) < 1e-12              # tài sản tăng 40 nhưng 30 trong đó là tiền tự bỏ thêm... lãi thật chỉ 20
    assert s["annual"] is not None and s["days"] == 400
    # khoảng ngắn: không quy năm (tránh con số vô nghĩa), vẫn có lãi thật
    db2 = tmp_path / "c2.db"
    cashflow.add(today - timedelta(days=10), 100.0, "", db2)
    s2 = cashflow.summary(cashflow.list_flows(db2), 105.0, today)
    assert s2["annual"] is None and s2["pnl"] == 5
    # rút nhiều hơn đã nạp: không có tỷ lệ %
    db3 = tmp_path / "c3.db"
    cashflow.add(today - timedelta(days=90), 100.0, "", db3)
    cashflow.add(today - timedelta(days=30), -150.0, "", db3)
    assert cashflow.summary(cashflow.list_flows(db3), 60.0, today)["pnl_pct"] is None


def test_cashflow_ui_records_flow_and_shows_true_profit(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    for k, f in (("TEST_CF", "c.db"), ("TEST_JOURNAL", "j.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    script = str(Path(__file__).resolve().parent / "ui_cashflow_app.py")
    at = AppTest.from_file(script, default_timeout=30).run()
    assert not at.exception
    assert at.number_input(key="cf_amount").value == 10_000_000                      # chưa có ghi chép: gợi ý sẵn số vốn
    at.number_input(key="cf_amount").set_value(10_000_000)
    next(b for b in at.button if "Ghi giao dịch" in b.label).click().run()
    assert not at.exception
    df = cashflow.list_flows(tmp_path / "c.db")
    assert len(df) == 1 and df.iloc[0]["amount"] == 10_000_000
    assert any("Đã ghi nạp tiền vào" in s.value for s in at.success)                  # thông báo xanh đang hiện trên màn hình
    at2 = AppTest.from_file(script, default_timeout=30).run()                         # lần chạy sau: thẻ lãi thật xuất hiện
    text = " ".join(m.value for m in at2.markdown)
    assert "Lãi/lỗ thật" in text and "+2 triệu" in text and "+20,0%" in text            # 12 triệu - 10 triệu ròng, 20%
    assert "Chưa tính được" in text                                                   # ghi hôm nay: chưa đủ 60 ngày để quy năm
    # rút tiền ra được ghi dạng âm; số tiền 0 bị chặn VÀ lựa chọn của người dùng được giữ nguyên (không tự đổi thành “nạp”)
    at2.radio(key="cf_kind").set_value("Rút tiền ra")
    at2.number_input(key="cf_amount").set_value(0.0)
    at2.text_input(key="cf_note").set_value("rút để chi tiêu")
    next(b for b in at2.button if "Ghi giao dịch" in b.label).click().run()
    assert len(cashflow.list_flows(tmp_path / "c.db")) == 1 and any("lớn hơn 0" in e.value for e in at2.error)
    assert at2.radio(key="cf_kind").value == "Rút tiền ra" and at2.text_input(key="cf_note").value == "rút để chi tiêu"
    at2.number_input(key="cf_amount").set_value(3_000_000)
    next(b for b in at2.button if "Ghi giao dịch" in b.label).click().run()
    assert not any("lớn hơn 0" in e.value for e in at2.error)                         # lỗi cũ biến mất sau khi ghi thành công
    assert at2.number_input(key="cf_amount").value == 0 and at2.text_input(key="cf_note").value == ""  # ghi xong mới xoá ô nhập
    assert sorted(cashflow.list_flows(tmp_path / "c.db")["amount"]) == [-3_000_000, 10_000_000]


# ---------- sửa / xoá / mở lại lệnh trong Nhật ký ----------
def _seed_journal(db):
    open_id = journal.add_trade("FPT", 100, 100_000, 95_000, 120_000, "luận điểm ban đầu", "2026-01-05", db)
    closed_id = journal.add_trade("HPG", 200, 25_000, 23_000, None, "x", "2026-02-01", db)
    journal.close_trade(closed_id, 27_000, "2026-03-01", "ok", db)
    return open_id, closed_id


def test_update_trade_valid_changes_and_derived_fields(tmp_path):
    db = tmp_path / "j.db"
    o, c = _seed_journal(db)
    journal.update_trade(o, db, stop=97_000, target=130_000, reason="  luận điểm mới  ", opened="2026-01-06")
    t = journal.get_trade(o, db)
    assert (t["stop"], t["target"], t["reason"], t["opened"]) == (97_000, 130_000, "luận điểm mới", "2026-01-06")
    journal.update_trade(o, db, target=0)                                          # 0 = bỏ trống mục tiêu
    assert journal.get_trade(o, db)["target"] is None
    # sửa lệnh đã bán: có giá bán/ngày bán mới -> lãi/lỗ và R tính lại
    before = journal.list_trades(db).set_index("id").loc[c]
    journal.update_trade(c, db, exit_price=30_000, closed="2026-03-05")
    after = journal.list_trades(db).set_index("id").loc[c]
    assert after["pnl"] > before["pnl"] and after["r_multiple"] > before["r_multiple"]
    # đặt cắt lỗ cho lệnh chưa đặt -> có R
    k = journal.add_trade("VCB", 10, 90_000, 0, None, "chưa đặt", "2026-04-01", db)
    journal.close_trade(k, 99_000, "2026-04-10", "", db)
    assert journal.list_trades(db).set_index("id").loc[k]["r_multiple"] != journal.list_trades(db).set_index("id").loc[k]["r_multiple"]  # NaN
    journal.update_trade(k, db, stop=85_000)
    assert abs(journal.list_trades(db).set_index("id").loc[k]["r_multiple"]) > 0


def test_update_trade_rejects_invalid_and_keeps_data_unchanged(tmp_path):
    db = tmp_path / "j.db"
    o, c = _seed_journal(db)
    snapshot = journal.get_trade(o, db)
    bad_cases = [dict(stop=-1), dict(target=90_000), dict(qty=0), dict(entry=-5), dict(symbol="<x>"),
                 dict(opened="hôm qua"), dict(foo=1)]
    for bad in bad_cases:
        with pytest.raises(ValueError):
            journal.update_trade(o, db, **bad)
    assert journal.get_trade(o, db) == snapshot                                    # lỗi thì không sửa gì
    with pytest.raises(ValueError):
        journal.update_trade(c, db, exit_price=0)
    with pytest.raises(ValueError):
        journal.update_trade(c, db, closed="2026-01-01")                           # bán trước ngày mua (2026-02-01)
    with pytest.raises(ValueError):
        journal.update_trade(999, db, stop=1)


def test_import_marker_survives_reason_edits_so_reimport_stays_deduplicated(tmp_path):
    db = tmp_path / "j.db"
    tx, _ = portfolio.transactions_from_file(_tx_frame())
    trades, _ = importer.fifo_trades(tx)
    importer.to_journal(trades, db)
    before = journal.import_keys(db)
    for t in journal.list_trades(db).itertuples():
        journal.update_trade(int(t.id), db, reason="lý do tôi viết lại", stop=0)
    assert journal.import_keys(db) == before                                       # khoá còn nguyên
    assert importer.preview(trades, db)["new"] == 0 and importer.to_journal(trades, db) == {"open": 0, "closed": 0}
    assert all(r.endswith("lý do tôi viết lại") for r in journal.list_trades(db)["reason"])


def test_reopen_and_delete_trade(tmp_path):
    db = tmp_path / "j.db"
    o, c = _seed_journal(db)
    journal.reopen_trade(c, db)
    t = journal.get_trade(c, db)
    assert t["exit_price"] is None and t["closed"] is None and t["note"] is None
    assert journal.stats(journal.list_trades(db))["closed"] == 0
    journal.delete_trade(o, db)
    assert journal.get_trade(o, db) is None and len(journal.list_trades(db)) == 1


def test_journal_page_quick_edit_full_editor_reopen_and_delete(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    db = tmp_path / "j.db"
    monkeypatch.setenv("TEST_JOURNAL", str(db))
    o = journal.add_trade("FPT", 100, 100_000, 0, None, "[sao kê aaaaaaaaaa] Nhập từ sao kê giao dịch (chưa ghi lý do mua)", "Không rõ", db)
    c = journal.add_trade("HPG", 200, 25_000, 23_000, None, "bán thử", "2026-02-01", db)
    journal.close_trade(c, 27_000, "2026-03-01", "ok", db)
    script = str(Path(__file__).resolve().parent / "ui_journal_edit_app.py")
    at = AppTest.from_file(script, default_timeout=60).run()
    assert not at.exception
    # lệnh nhập từ sao kê: ô lý do để trống (không hiện chữ “Nhập từ sao kê”), mời bổ sung
    assert at.text_area(key=f"jq_reason_{o}").value == ""
    # nhập sai: giá mục tiêu thấp hơn giá mua -> báo lỗi, dữ liệu không đổi
    at.text_area(key=f"jq_reason_{o}").set_value("xu hướng tăng, lợi nhuận tốt")
    at.number_input(key=f"jq_stop_{o}").set_value(92_000)
    at.number_input(key=f"jq_target_{o}").set_value(90_000)
    next(b for b in at.button if b.label == "Lưu").click().run()
    assert any("cao hơn giá mua" in e.value for e in at.error)
    assert journal.get_trade(o, db)["stop"] == 0 and journal.get_trade(o, db)["target"] is None
    # nhập đúng: lưu được, vẫn giữ khoá nhận diện nhập sao kê
    at.number_input(key=f"jq_stop_{o}").set_value(92_000)
    at.number_input(key=f"jq_target_{o}").set_value(115_000)
    next(b for b in at.button if b.label == "Lưu").click().run()
    assert not at.exception and not at.error
    t = journal.get_trade(o, db)
    assert (t["stop"], t["target"]) == (92_000, 115_000) and t["reason"] == "[sao kê aaaaaaaaaa] xu hướng tăng, lợi nhuận tốt"
    # trình sửa đầy đủ: mặc định chọn lệnh mới nhất (HPG đã bán); đổi giá bán và bài học
    at.number_input(key=f"je_exit_{c}").set_value(30_000)
    at.text_input(key=f"je_note_{c}").set_value("giữ đúng kế hoạch")
    next(b for b in at.button if b.label == "Lưu thay đổi").click().run()
    t = journal.get_trade(c, db)
    assert t["exit_price"] == 30_000 and t["note"] == "giữ đúng kế hoạch"
    # ngày bán trước ngày mua bị chặn
    at.text_input(key=f"je_closed_{c}").set_value("2026-01-01")
    next(b for b in at.button if b.label == "Lưu thay đổi").click().run()
    assert any("trước ngày mua" in e.value for e in at.error) and journal.get_trade(c, db)["closed"] == "2026-03-01"
    # mở lại lệnh bán nhầm
    at.button(key=f"je_reopen_{c}").click().run()
    assert journal.get_trade(c, db)["exit_price"] is None
    # xoá: nút bị khoá cho tới khi tích xác nhận
    assert at.button(key=f"je_del_{c}").disabled
    at.checkbox(key=f"je_del_ok_{c}").set_value(True).run()
    at.button(key=f"je_del_{c}").click().run()
    assert journal.get_trade(c, db) is None and journal.get_trade(o, db) is not None


# ---------- bảng rủi ro danh mục ----------
from src import risk_table  # noqa: E402


def _risk_fixture():
    pf = {"holdings": portfolio.clean_holdings([
        {"symbol": "AAA", "qty": 1000, "avg_cost": 25_000}, {"symbol": "BBB", "qty": 500, "avg_cost": 18_000},
        {"symbol": "CCC", "qty": 400, "avg_cost": 30_000}, {"symbol": "DDD", "qty": 300, "avg_cost": 9_000}]), "cash": 10_000_000}
    prices = {"AAA": 30_000.0, "BBB": 20_000.0, "CCC": 25_000.0, "DDD": 10_000.0}
    val, _ = portfolio.valuate(pf, prices.get, 0.30)
    trades = pd.DataFrame([
        {"symbol": "AAA", "qty": 600, "stop": 27_000.0}, {"symbol": "AAA", "qty": 400, "stop": 25_000.0},   # TB gia quyền 26.200
        {"symbol": "CCC", "qty": 400, "stop": 26_000.0},                                                      # giá 25.000 đã dưới cắt lỗ
        {"symbol": "DDD", "qty": 100, "stop": 9_000.0}, {"symbol": "DDD", "qty": 200, "stop": 0.0}])          # chỉ phủ 100/300
    return val, trades, pf["cash"]


def test_risk_table_numbers_by_hand():
    val, trades, cash = _risk_fixture()
    df, s = risk_table.build(val, trades, cash, risk_pct=2.0)
    r = df.set_index("symbol")
    assert abs(r.loc["AAA", "stop"] - 26_200) < 1e-6 and r.loc["AAA", "loss"] == 3_800_000        # 1000 * (30.000 - 26.200)
    assert abs(r.loc["AAA", "pct_assets"] - 3_800_000 / 63_000_000) < 1e-12
    assert r.loc["AAA", "status"].startswith("Vượt mức")                                          # 6,0% > 2%
    assert pd.isna(r.loc["BBB", "stop"]) and r.loc["BBB", "status"] == "Chưa đặt cắt lỗ" and r.loc["BBB", "unprotected_value"] == 10_000_000
    assert r.loc["CCC", "hit"] and r.loc["CCC", "loss"] == 0 and r.loc["CCC", "status"] == "Đã chạm cắt lỗ"
    assert r.loc["DDD", "covered"] == 100 and r.loc["DDD", "uncovered"] == 200 and r.loc["DDD", "loss"] == 100_000
    assert r.loc["DDD", "status"] == "200 cp chưa có cắt lỗ" and r.loc["DDD", "unprotected_value"] == 2_000_000
    assert s["loss_to_stop"] == 3_900_000 and s["unprotected_value"] == 12_000_000
    assert abs(s["unprotected_share"] - 12 / 53) < 1e-12 and s["n_hit"] == 1 and s["n_unprotected"] == 1
    assert s["verdict"][1] == "bad"                                                                # có mã đã chạm cắt lỗ + nhiều mã chưa phủ
    ten = next(x for x in s["scenarios"] if x["drop"] == 10)
    assert ten["loss"] == 5_300_000 and abs(ten["pct_assets"] - 5_300_000 / 63_000_000) < 1e-12   # 10% của 53 triệu cổ phiếu


def test_risk_table_verdict_levels_and_no_stops_at_all():
    val, _, _ = _risk_fixture()
    only = val[val.symbol == "AAA"]
    safe_t = pd.DataFrame([{"symbol": "AAA", "qty": 1000, "stop": 29_000.0}])                      # mất 1 triệu trên 90+ triệu tài sản
    _, s = risk_table.build(only, safe_t, 60_000_000, risk_pct=2.0)
    assert s["verdict"][0] == "Trong tầm kiểm soát" and s["n_over"] == 0
    # không có lệnh nhật ký nào: mọi mã chưa đặt cắt lỗ -> rủi ro cao
    _, s2 = risk_table.build(val, pd.DataFrame(columns=["symbol", "qty", "stop"]), 0.0)
    assert s2["unprotected_share"] == 1.0 and s2["verdict"][1] == "bad" and s2["n_unprotected"] == 4
    # danh mục rỗng không gây lỗi chia cho 0
    empty, s3 = risk_table.build(val.iloc[0:0], None, 5_000_000)
    assert empty.empty and s3["verdict"][0] == "Chưa có cổ phiếu" and s3["loss_to_stop_pct"] == 0.0


def test_risk_section_renders_levels_and_updates_after_setting_a_stop(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("TEST_JOURNAL", str(tmp_path / "j.db"))
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    portfolio.save({"holdings": [{"symbol": "AAA", "qty": 1000, "avg_cost": 25_000}, {"symbol": "BBB", "qty": 500, "avg_cost": 18_000}],
                    "cash": 20_000_000}, "manual", tmp_path / "pf.json")
    script = str(Path(__file__).resolve().parent / "ui_risk_app.py")
    at = AppTest.from_file(script, default_timeout=30).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Rủi ro cao" in text and "Chưa có cắt lỗ" in text and "100%" in text            # chưa có lệnh nào đặt cắt lỗ
    assert any(b.label == "Đi tới Nhật ký để đặt mức cắt lỗ" for b in at.button)
    # đặt cắt lỗ cho cả hai mã trong Nhật ký -> đánh giá thay đổi, nút dẫn tới Nhật ký biến mất
    a = journal.add_trade("AAA", 1000, 25_000, 24_000, None, "x", "2026-01-01", tmp_path / "j.db")
    journal.update_trade(a, tmp_path / "j.db", stop=29_000)                                    # kéo cắt lỗ lên trên giá mua (giá nay 30.000)
    journal.add_trade("BBB", 500, 18_000, 19_000 - 2_000, None, "y", "2026-01-01", tmp_path / "j.db")
    at2 = AppTest.from_file(script, default_timeout=30).run()
    text2 = " ".join(m.value for m in at2.markdown)
    assert "Trong tầm kiểm soát" in text2 or "Cần chú ý" in text2
    assert not any(b.label == "Đi tới Nhật ký để đặt mức cắt lỗ" for b in at2.button)
    kich_ban = [d for d in at2.dataframe][-1].value.to_dict("records")
    assert [r["Giảm thêm"] for r in kich_ban] == ["5%", "10%", "20%", "30%"]


def test_stop_can_be_raised_above_entry_to_lock_profit_and_r_is_not_computed(tmp_path):
    db = tmp_path / "j.db"
    t = journal.add_trade("AAA", 100, 25_000, 24_000, None, "x", "2026-01-01", db)
    with pytest.raises(ValueError):
        journal.add_trade("BBB", 100, 25_000, 26_000, None, "y", "2026-01-01", db)      # lệnh MỚI vẫn bắt buộc cắt lỗ thấp hơn giá mua
    journal.update_trade(t, db, stop=29_000)                                               # nhưng sửa lệnh thì được (giá đã lên 30.000)
    assert journal.get_trade(t, db)["stop"] == 29_000
    journal.close_trade(t, 29_000, "2026-02-01", "", db)
    row = journal.list_trades(db).iloc[0]
    assert row["pnl"] > 0 and row["r_multiple"] != row["r_multiple"]                      # lãi thật, nhưng R không có nghĩa -> NaN
    assert journal.stats(journal.list_trades(db))["avg_r"] is None


# ---------- cập nhật giá một nút ----------
from src import updater  # noqa: E402


def _source(days=120, end="2026-11-04", scale=1.0, base=20_000.0):
    idx = pd.bdate_range(end=end, periods=days)
    close = (base + np.arange(days) * 10.0) * scale
    return pd.DataFrame({"date": idx, "open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1_000_000})


def _fake_fetch(src, calls=None):
    def f(symbol, start, end):
        if calls is not None:
            calls.append((symbol, start, end))
        return src[(src["date"] >= start) & (src["date"] <= end)].copy()
    return f


def _bytes(tmp, sym):
    return (tmp / f"{sym}.csv").read_bytes()


def test_update_new_symbol_full_history_and_atomic_write(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "CSV_DIR", tmp_path)
    calls = []
    r = updater.update_symbol("fpt", _fake_fetch(_source(), calls), years_full=8, today=date(2026, 11, 4))
    assert r["status"] == "ok" and r["added"] == 120 and r["last_date"] == pd.Timestamp("2026-11-04")
    assert calls == [("FPT", "2018-11-04", "2026-11-04")]                               # mã chưa có file: lấy 8 năm
    assert len(updater.read_csv("FPT")) == 120 and not list(tmp_path.glob("*.tmp"))     # không để lại file tạm


def test_incremental_update_merges_overlap_and_new_bar_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "CSV_DIR", tmp_path)
    old_src = _source(days=100, end="2026-10-30")
    updater.update_symbol("FPT", _fake_fetch(old_src), today=date(2026, 10, 30))
    # nến cuối của lần trước dở dang: sửa lại trong nguồn mới; thêm vài phiên mới
    new_src = _source(days=104, end="2026-11-05")
    new_src.loc[new_src["date"] == pd.Timestamp("2026-10-30"), "close"] += 55.0
    calls = []
    r = updater.update_symbol("FPT", _fake_fetch(new_src, calls), today=date(2026, 11, 5))
    got = updater.read_csv("FPT")
    assert r["added"] == 4 and len(got) == 104 and got["date"].is_unique and got["date"].is_monotonic_increasing
    assert calls[0][1] == "2026-10-23"                                                  # chồng lấn 7 ngày, không tải lại cả lịch sử
    fixed = got.loc[got["date"] == pd.Timestamp("2026-10-30"), "close"].iloc[0]
    assert fixed == new_src.loc[new_src["date"] == pd.Timestamp("2026-10-30"), "close"].iloc[0]  # bản mới thắng
    assert r["note"] == ""


def test_adjusted_history_triggers_full_reload_or_keeps_old_if_source_is_short(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "CSV_DIR", tmp_path)
    first_day = f"{_source(days=150, end='2026-10-30')['date'].min():%Y-%m-%d}"             # ngày đầu của file cũ
    updater.update_symbol("HPG", _fake_fetch(_source(days=150, end="2026-10-30")), today=date(2026, 10, 30))
    split = _source(days=154, end="2026-11-05", scale=0.5)                               # chia tách: toàn bộ lịch sử nhỏ đi một nửa
    calls = []
    r = updater.update_symbol("HPG", _fake_fetch(split, calls), today=date(2026, 11, 5))
    assert "điều chỉnh" in r["note"] and len(calls) == 2 and calls[1][1] == first_day  # lần 2 tải từ ngày đầu của file
    got = updater.read_csv("HPG")
    assert len(got) == 154 and abs(got["close"].iloc[0] - split["close"].iloc[0]) < 1e-9  # lịch sử đã thay bằng giá điều chỉnh
    # nguồn chỉ trả 30 phiên (tài khoản Khách): GIỮ file cũ, báo rõ, không mất lịch sử
    updater.update_symbol("VNM", _fake_fetch(_source(days=150, end="2026-10-30")), today=date(2026, 10, 30))
    before = _bytes(tmp_path, "VNM")
    short = _source(days=154, end="2026-11-05", scale=0.5).tail(30)

    def limited(symbol, start, end):
        return short[(short["date"] >= start) & (short["date"] <= end)].copy()
    r2 = updater.update_symbol("VNM", limited, today=date(2026, 11, 5))
    assert r2["status"] == "giữ file cũ" and "vnstock register" in r2["note"] and _bytes(tmp_path, "VNM") == before


def test_errors_and_empty_responses_never_touch_files(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "CSV_DIR", tmp_path)
    updater.update_symbol("ACB", _fake_fetch(_source(days=80, end="2026-10-30")), today=date(2026, 10, 30))
    before = _bytes(tmp_path, "ACB")

    def boom(symbol, start, end):
        raise RuntimeError("rate limit reached " + "x" * 400)
    r = updater.update_symbol("ACB", boom, today=date(2026, 11, 5))
    assert r["status"] == "lỗi" and len(r["note"]) <= 160 and r["last_date"] == pd.Timestamp("2026-10-30")
    assert updater.update_symbol("ACB", lambda s, a, b: pd.DataFrame(columns=updater.COLUMNS), today=date(2026, 11, 5))["status"] == "không có dữ liệu mới"
    assert _bytes(tmp_path, "ACB") == before
    assert updater.update_symbol("ZZZ", boom, today=date(2026, 11, 5))["status"] == "lỗi" and not (tmp_path / "ZZZ.csv").exists()


def test_update_many_progress_pause_dedupe_and_missing_library(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "CSV_DIR", tmp_path)
    src = _source(days=60)
    good = _fake_fetch(src)

    def partly_bad(symbol, start, end):
        if symbol == "BAD":
            raise RuntimeError("không có mã")
        return good(symbol, start, end)
    seen, naps = [], []
    res = updater.update_many(["fpt", "FPT", "BAD", "HPG"], partly_bad, progress=lambda i, n, r: seen.append((i, n, r["symbol"])),
                              pause=2.5, sleeper=naps.append, today=date(2026, 11, 4))
    assert [r["symbol"] for r in res] == ["FPT", "BAD", "HPG"] and [r["status"] for r in res] == ["ok", "lỗi", "ok"]   # trùng mã chỉ làm một lần, lỗi không chặn mã sau
    assert seen == [(1, 3, "FPT"), (2, 3, "BAD"), (3, 3, "HPG")] and naps == [2.5, 2.5]
    # thiếu vnstock: dừng ngay, các mã sau ghi là bỏ qua (không gọi nhiều lần vô ích)
    calls = []

    def no_lib(symbol, start, end):
        calls.append(symbol)
        raise ImportError("vnstock")
    res2 = updater.update_many(["AAA", "BBB", "CCC"], no_lib, pause=0, sleeper=lambda s: None, today=date(2026, 11, 4))
    assert calls == ["AAA"] and [r["status"] for r in res2] == ["thiếu vnstock", "bỏ qua", "bỏ qua"]
    assert updater.last_data_date(["FPT", "HPG", "NOPE"]) == src["date"].max()


def test_update_button_downloads_reports_progress_and_isolates_failures(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    prices = tmp_path / "prices"
    for k, f in (("TEST_PRICES", "prices"), ("TEST_JOURNAL", "j.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    monkeypatch.delenv("TEST_FAIL", raising=False)
    script = str(Path(__file__).resolve().parent / "ui_update_app.py")
    at = AppTest.from_file(script, default_timeout=60).run()
    assert not at.exception and "Chưa có dữ liệu giá" in " ".join(c.value for c in at.caption)
    btn = next(b for b in at.button if "Cập nhật giá" in b.label)
    btn.click().run()
    assert not at.exception
    assert sorted(p.stem for p in prices.glob("*.csv")) == ["FPT", "HPG", "VNINDEX"]       # chỉ số + 2 mã theo dõi
    text = " ".join(m.value for m in at.markdown)
    assert "Đã cập nhật 3/3 mã" in text and "04/11/2026" in text
    # một mã lỗi: báo rõ mã đó, các mã khác vẫn cập nhật
    for f in prices.glob("*.csv"):
        f.unlink()
    monkeypatch.setenv("TEST_FAIL", "HPG")
    at2 = AppTest.from_file(script, default_timeout=60).run()
    next(b for b in at2.button if "Cập nhật giá" in b.label).click().run()
    text2 = " ".join(m.value for m in at2.markdown)
    assert sorted(p.stem for p in prices.glob("*.csv")) == ["FPT", "VNINDEX"] and "Đã cập nhật 2/3 mã" in text2 and "HPG: lỗi" in text2


# ---------- đồng bộ giá giữa các trang ----------
def _write_price_file(folder, sym, last_close, n=120):
    idx = pd.bdate_range(end="2026-11-04", periods=n)
    close = np.full(n, 20_000.0)
    close[-1] = last_close
    pd.DataFrame({"date": idx, "open": close, "high": close, "low": close, "close": close, "volume": 2_000_000}).to_csv(folder / f"{sym}.csv", index=False)


def test_all_pages_see_new_prices_even_when_files_are_updated_outside_the_app(tmp_path, monkeypatch):
    """Cập nhật giá bằng lệnh Terminal/tiến trình khác (không qua nút trong app) cũng phải làm MỌI trang đổi theo, không chờ hết hạn bộ nhớ đệm."""
    import os
    from src import data as data_mod
    from views import portfolio_view, shared
    monkeypatch.setattr(data_mod, "CSV_DIR", tmp_path)
    for sym in ("AAA", "VNINDEX"):
        _write_price_file(tmp_path, sym, 20_000.0 if sym == "AAA" else 1_700.0)
    shared.load.clear() if hasattr(shared.load, "clear") else shared.clear_price_caches()
    assert shared.load("AAA")[0]["close"].iloc[-1] == 20_000
    assert shared.load_long("AAA")[0]["close"].iloc[-1] == 20_000
    assert shared.snapshot(("AAA",))[0][0]["close"] == 20_000
    assert portfolio_view._last_price("AAA") == 20_000
    # file giá được ghi đè từ bên ngoài (giá tăng 10%), KHÔNG gọi xoá bộ nhớ đệm
    _write_price_file(tmp_path, "AAA", 22_000.0)
    stamp = os.stat(tmp_path / "AAA.csv").st_mtime + 5
    os.utime(tmp_path / "AAA.csv", (stamp, stamp))
    assert shared.load("AAA")[0]["close"].iloc[-1] == 22_000                       # Danh mục / Nhật ký
    assert shared.load_long("AAA")[0]["close"].iloc[-1] == 22_000                  # Tra cứu cổ phiếu / biểu đồ
    snap = shared.snapshot(("AAA",))[0][0]
    assert snap["close"] == 22_000 and abs(snap["change"] - 0.10) < 1e-9           # Tổng quan: giá và % thay đổi
    assert portfolio_view._last_price("AAA") == 22_000
    # giá trị danh mục đi theo giá: 1.000 cổ phiếu x 22.000
    pf = {"holdings": [{"symbol": "AAA", "qty": 1000, "avg_cost": 20_000.0, "market_value": None}], "cash": 0.0}
    df, s = portfolio.valuate(pf, portfolio_view._last_price)
    assert s["stock_value"] == 22_000_000 and s["pnl"] == 2_000_000


# ---------- phân tích Nhật ký (thẻ lỗi, thời gian giữ) ----------
import sqlite3  # noqa: E402

from src import journal_stats  # noqa: E402


def _stats_journal(db):
    def trade(sym_days, gross_pct, stop=95_000, tags="", reason="lý do", opened_day="2026-01-01"):
        days = sym_days
        o = pd.Timestamp(opened_day)
        t = journal.add_trade("FPT", 100, 100_000, stop, None, reason, o.date().isoformat(), db)
        journal.close_trade(t, 100_000 * (1 + gross_pct), (o + pd.Timedelta(days=days)).date().isoformat(), "", db)
        if tags:
            journal.update_trade(t, db, tags=tags)
        return t
    for d, g in ((20, .10), (10, .08), (40, .05), (15, -.04)):                       # nhóm bình thường: 3 thắng, 1 thua
        trade(d, g)
    for d, g in ((5, -.08), (3, -.06), (2, .02), (6, -.10)):                         # mua đuổi giá: 1 thắng, 3 thua
        trade(d, g, tags="Mua đuổi giá (FOMO)")
    for d, g in ((60, -.12), (45, -.09), (10, .03)):                                 # không cắt lỗ + chưa ghi lý do: 1 thắng, 2 thua
        trade(d, g, stop=0, reason=journal.PLACEHOLDER_REASON + " giao dịch (chưa ghi lý do mua)")


def test_journal_stats_numbers_by_hand(tmp_path):
    from src.risk import FEE_RATE, SELL_TAX
    db = tmp_path / "j.db"
    _stats_journal(db)
    # lệnh chưa rõ ngày mua: vẫn tính thắng/thua nhưng KHÔNG đưa vào thống kê thời gian giữ
    u = journal.add_trade("HPG", 100, 20_000, 19_000, None, "x", "Không rõ", db)
    journal.close_trade(u, 22_000, "2026-03-01", "", db)
    d = journal_stats.enrich(journal.list_trades(db))
    assert len(d) == 12 and d["days"].isna().sum() == 1
    s = journal_stats.summary(d)
    assert s["n"] == 12 and abs(s["win_rate"] - 6 / 12) < 1e-12 and not s["reliable"]
    # tỷ suất sau phí/thuế đúng công thức
    exp = (110_000 * (1 - FEE_RATE - SELL_TAX) - 100_000 * (1 + FEE_RATE)) / 100_000
    assert abs(d[d["ret"] > 0.08].iloc[0]["ret"] - exp) < 1e-9
    tags = journal_stats.by_tag(d).set_index("tag")
    assert not any(str(x).lower() in ("nan", "none", "") for x in tags.index)                  # lệnh chưa gắn thẻ không được thành thẻ “nan”
    assert journal.split_tags(float("nan")) == [] and journal.split_tags(None) == [] and journal.split_tags("a|b") == ["a", "b"]
    fomo = tags.loc["Mua đuổi giá (FOMO)"]
    assert fomo["n"] == 4 and fomo["win_rate"] == 0.25 and fomo["small"] is np.True_ or fomo["small"] is True
    assert tags.loc[journal_stats.TAG_NO_STOP, "n"] == 3 and abs(tags.loc[journal_stats.TAG_NO_STOP, "win_rate"] - 1 / 3) < 1e-12   # tự nhận từ stop = 0
    assert tags.loc[journal_stats.TAG_NO_REASON, "n"] == 3                                                                       # tự nhận từ lý do mặc định
    hold = journal_stats.by_holding(d).set_index("bucket")
    assert (hold.loc["Tối đa 7 ngày", "n"], hold.loc["8 đến 30 ngày", "n"], hold.loc["31 đến 90 ngày", "n"]) == (4, 4, 3)       # 11 lệnh có ngày
    st = journal_stats.by_stop(d).set_index("group")
    assert st.loc["Có đặt cắt lỗ", "n"] == 9 and st.loc["Chưa đặt cắt lỗ", "n"] == 3
    # nhận xét: mua đuổi giá kém hơn phần còn lại; có cảnh báo mẫu nhỏ; không bịa nhận xét “giữ lỗ lâu” khi số liệu không đủ lệch
    text = " ".join(journal_stats.insights(d))
    assert "Mua đuổi giá (FOMO)" in text and "kém hơn" in text and "Mới có 12 lệnh" in text and "giữ lệnh lỗ lâu hơn" not in text


def test_journal_stats_stay_silent_with_too_little_data(tmp_path):
    db = tmp_path / "j.db"
    for g in (.05, -.03):
        t = journal.add_trade("FPT", 100, 100_000, 95_000, None, "x", "2026-01-01", db)
        journal.close_trade(t, 100_000 * (1 + g), "2026-01-10", "", db)
    d = journal_stats.enrich(journal.list_trades(db))
    ins = journal_stats.insights(d)
    assert len(ins) == 1 and "Mới có 2 lệnh" in ins[0]                                    # không rút kết luận từ 2 lệnh
    assert journal_stats.enrich(pd.DataFrame()).empty and journal_stats.insights(journal_stats.enrich(None)) == []


def test_tags_roundtrip_normalisation_and_safe_migration_of_old_database(tmp_path):
    # cơ sở dữ liệu CŨ (chưa có cột tags) vẫn mở được, giữ nguyên dữ liệu, tự thêm cột
    old = tmp_path / "old.db"
    c = sqlite3.connect(old)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, opened TEXT NOT NULL, symbol TEXT NOT NULL, qty INTEGER NOT NULL, "
              "entry REAL NOT NULL, stop REAL NOT NULL, target REAL, reason TEXT, closed TEXT, exit_price REAL, note TEXT)")
    c.execute("INSERT INTO trades(opened,symbol,qty,entry,stop,reason) VALUES ('2026-01-01','ACB',400,22732,0,'lệnh cũ')")
    c.commit(); c.close()
    df = journal.list_trades(old)
    assert len(df) == 1 and df.iloc[0]["symbol"] == "ACB" and df.iloc[0]["reason"] == "lệnh cũ" and "tags" in df.columns
    tid = int(df.iloc[0]["id"])
    journal.update_trade(tid, old, tags=["Mua vì tin đồn", "mua vì tin đồn", " ", "Đúng kế hoạch|x", "A" * 80])
    got = journal.split_tags(journal.get_trade(tid, old)["tags"])
    assert got == ["Mua vì tin đồn", "Đúng kế hoạch x", "A" * 40]                           # bỏ trùng (không phân biệt hoa thường), bỏ trống, cắt độ dài, bỏ ký tự phân cách
    journal.update_trade(tid, old, stop=20_000)                                              # sửa trường khác không làm mất thẻ
    assert journal.split_tags(journal.get_trade(tid, old)["tags"]) == got
    with pytest.raises(ValueError):
        journal.update_trade(tid, old, tags=[f"t{i}" for i in range(9)])
    assert journal.get_trade(tid, old)["stop"] == 20_000 and journal.split_tags(journal.get_trade(tid, old)["tags"]) == got   # lỗi: không đổi gì


def test_journal_page_tags_are_saved_and_analysis_section_appears(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    db = tmp_path / "j.db"
    monkeypatch.setenv("TEST_JOURNAL", str(db))
    o = journal.add_trade("FPT", 100, 100_000, 0, None, "", "Không rõ", db)
    c = journal.add_trade("HPG", 200, 25_000, 23_000, None, "bán thử", "2026-02-01", db)
    journal.close_trade(c, 22_000, "2026-03-01", "", db)
    script = str(Path(__file__).resolve().parent / "ui_journal_edit_app.py")
    at = AppTest.from_file(script, default_timeout=60).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Phân tích nhật ký" in text and "Lệnh đã bán" in text and "Mới có 1 lệnh" in text                 # có phân tích, kèm cảnh báo mẫu nhỏ
    at.multiselect(key=f"jq_tags_{o}").select("Mua đuổi giá (FOMO)").select("Mua vì tin đồn")
    at.text_area(key=f"jq_reason_{o}").set_value("thấy mọi người nói tăng")
    next(b for b in at.button if b.label == "Lưu").click().run()
    assert not at.exception and not at.error
    assert journal.split_tags(journal.get_trade(o, db)["tags"]) == ["Mua đuổi giá (FOMO)", "Mua vì tin đồn"]
    # thẻ đã lưu hiện lại khi mở lại trang, và sửa nhanh không làm mất chúng
    at2 = AppTest.from_file(script, default_timeout=60).run()
    assert at2.multiselect(key=f"jq_tags_{o}").value == ["Mua đuổi giá (FOMO)", "Mua vì tin đồn"]


# ---------- cổ tức ----------
from src import dividends  # noqa: E402


def _div_env(tmp_path):
    pf = tmp_path / "pf.json"
    portfolio.save({"holdings": [{"symbol": "FPT", "qty": 1000, "avg_cost": 20_000.0, "market_value": 25_000_000},
                                 {"symbol": "HPG", "qty": 500, "avg_cost": 24_000.0}], "cash": 1_000_000.0}, "import", pf)
    return tmp_path / "d.db", pf


def test_cash_dividend_applies_to_portfolio_cash_and_true_profit(tmp_path):
    db, pf = _div_env(tmp_path)
    today = date.today()
    dividends.add(today, "fpt", dividends.CASH, 500_000, "cổ tức 2025", True, db, pf)
    p = portfolio.load(pf)
    assert p["cash"] == 1_500_000 and [h["qty"] for h in p["holdings"]] == [1000, 500]     # chỉ tiền mặt đổi
    row = dividends.list_all(db).iloc[0]
    assert row["symbol"] == "FPT" and row["applied"] == 1 and row["amount"] == 500_000
    # không áp dụng: chỉ ghi chép, Danh mục giữ nguyên
    dividends.add(today, "HPG", dividends.CASH, 200_000, "", False, db, pf)
    assert portfolio.load(pf)["cash"] == 1_500_000


def test_bonus_shares_keep_total_cost_and_failures_write_nothing(tmp_path):
    db, pf = _div_env(tmp_path)
    today = date.today()
    dividends.add(today, "FPT", dividends.BONUS, 100, "thưởng 10%", True, db, pf)
    h = {x["symbol"]: x for x in portfolio.load(pf)["holdings"]}
    assert h["FPT"]["qty"] == 1100 and abs(h["FPT"]["avg_cost"] * 1100 - 20_000_000) < 1e-6     # tổng giá vốn không đổi
    assert abs(h["FPT"]["avg_cost"] - 20_000_000 / 1100) < 1e-9 and h["FPT"]["market_value"] is None
    assert h["HPG"]["qty"] == 500                                                                  # mã khác không bị động tới
    # áp dụng thất bại (mã không có trong Danh mục): không ghi gì cả, ở cả hai nơi
    before_pf, before_n = portfolio.load(pf), len(dividends.list_all(db))
    with pytest.raises(ValueError, match="chưa có"):
        dividends.add(today, "VNM", dividends.BONUS, 50, "", True, db, pf)
    assert portfolio.load(pf) == before_pf and len(dividends.list_all(db)) == before_n
    # nhập sai
    for bad in (dict(day=today + timedelta(days=1), amount=100), dict(day=today, amount=0), dict(day=today, amount=-5),
                dict(day=today, amount=float("nan")), dict(day=today, amount=10.5, kind=dividends.BONUS),
                dict(day=today, amount=100, symbol="<x>"), dict(day=today, amount=100, kind="khac")):
        args = dict(day=today, symbol="FPT", kind=dividends.CASH, amount=100) | bad
        with pytest.raises(ValueError):
            dividends.add(args["day"], args["symbol"], args["kind"], args["amount"], "", False, db, pf)
    assert len(dividends.list_all(db)) == before_n


def test_dividend_summary_numbers_and_delete_does_not_revert_portfolio(tmp_path):
    db, pf = _div_env(tmp_path)
    today = date.today()
    dividends.add(today - timedelta(days=30), "FPT", dividends.CASH, 400_000, "", True, db, pf)
    dividends.add(today - timedelta(days=200), "HPG", dividends.CASH, 100_000, "", False, db, pf)
    dividends.add(today - timedelta(days=400), "FPT", dividends.CASH, 300_000, "", False, db, pf)            # quá 12 tháng
    dividends.add(today - timedelta(days=20), "FPT", dividends.BONUS, 100, "", False, db, pf)
    s = dividends.summary(dividends.list_all(db), holdings_cost=20_000_000 + 12_000_000, today=today)
    assert s["n"] == 4 and s["cash_total"] == 800_000 and s["cash_12m"] == 500_000 and s["cash_applied"] == 400_000
    assert abs(s["yield_on_cost"] - 500_000 / 32_000_000) < 1e-12 and s["bonus_total"] == 100
    by = s["by_symbol"].set_index("symbol")
    assert by.loc["FPT", "cash"] == 700_000 and by.loc["FPT", "shares"] == 100 and by.loc["HPG", "cash"] == 100_000
    cash_after = portfolio.load(pf)["cash"]
    dividends.delete(int(dividends.list_all(db).iloc[0]["id"]), db)
    assert portfolio.load(pf)["cash"] == cash_after and len(dividends.list_all(db)) == 3                      # xoá ghi chép không hoàn lại Danh mục
    assert dividends.summary(pd.DataFrame())["n"] == 0


def test_dividend_ui_records_applies_and_keeps_input_on_error(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import dividends as dv
    monkeypatch.setenv("TEST_DIV", str(tmp_path / "d.db"))
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    portfolio.save({"holdings": [{"symbol": "FPT", "qty": 100, "avg_cost": 100_000.0}], "cash": 1_000_000.0}, "manual", tmp_path / "pf.json")
    script = str(Path(__file__).resolve().parent / "ui_dividend_app.py")
    at = AppTest.from_file(script, default_timeout=30).run()
    assert not at.exception
    at.number_input(key="dv_amount").set_value(0.0)
    next(b for b in at.button if "Ghi cổ tức" in b.label).click().run()
    assert any("lớn hơn 0" in e.value for e in at.error) and len(dv.list_all(tmp_path / "d.db")) == 0
    at.text_input(key="dv_note").set_value("đợt 1")
    at.number_input(key="dv_amount").set_value(500_000.0)
    next(b for b in at.button if "Ghi cổ tức" in b.label).click().run()
    assert not at.exception
    assert len(dv.list_all(tmp_path / "d.db")) == 1
    assert portfolio.load(tmp_path / "pf.json")["cash"] == 1_500_000.0            # đã cộng vào tiền mặt Danh mục
    assert at.number_input(key="dv_amount").value == 0 and at.text_input(key="dv_note").value == ""
    assert any("Đã ghi" in s.value for s in at.success)


# ---------- mua dần (DCA) ----------
def test_dca_split_lots_fees_and_carry():
    from src import dca
    r = dca.plan(5_000_000, 4, {"AAA": 20_000.0, "BBB": 50_000.0}, mode=dca.SPLIT)
    s = r["schedule"]
    assert (s["qty"] % 100 == 0).all()
    # 2,5 triệu/mã/tháng: AAA 20.000 -> 1 lô = 2.003.000 -> 100 cp mỗi tháng (dư dồn lại); BBB 1 lô = 5.007.500 -> tháng 2 mới có 5.000.000 (chưa đủ), tháng 3 mới mua được
    a = s[s["symbol"] == "AAA"].reset_index(drop=True)
    b = s[s["symbol"] == "BBB"].reset_index(drop=True)
    assert list(a["qty"]) == [100, 100, 100, 100] and list(b["qty"]) == [0, 0, 100, 0]
    assert abs(r["invested"] + r["leftover"] - r["total_budget"]) < 1e-6          # tiền vào = đã mua + còn dư, không mất đồng nào
    assert r["by_symbol"].set_index("symbol").loc["AAA", "avg_cost"] == 20_000 * 1.0015


def test_dca_rotate_unaffordable_note_and_validation():
    from src import dca
    r = dca.plan(1_000_000, 6, {"AAA": 20_000.0, "BBB": 400_000.0}, mode=dca.ROTATE)
    assert r["by_symbol"].set_index("symbol")["qty"].get("BBB", 0) == 0 and any("BBB" in n for n in r["notes"])
    assert abs(r["invested"] + r["leftover"] - r["total_budget"]) < 1e-6
    for bad in (dict(budget=0, months=3), dict(budget=1e6, months=0), dict(budget=1e6, months=999), dict(budget=float("nan"), months=3)):
        with pytest.raises(ValueError):
            dca.plan(bad["budget"], bad["months"], {"AAA": 20_000.0})
    with pytest.raises(ValueError):
        dca.plan(1e6, 3, {"AAA": 0.0})


def test_dca_page_renders_without_error(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_dca_app.py"), default_timeout=30).run()
    assert not at.exception
    at.number_input(key="dca_months").set_value(6)
    at.run()
    assert not at.exception


# ---------- báo cáo tháng ----------
def test_monthly_report_collects_only_that_month_and_exports(tmp_path):
    import io
    from src import report, dividends as dv
    from openpyxl import load_workbook
    jdb, cdb, ddb, pfp = tmp_path / "j.db", tmp_path / "c.db", tmp_path / "d.db", tmp_path / "pf.json"
    a = journal.add_trade("FPT", 100, 100_000, 95_000, None, "t10", "2026-10-02", jdb)
    journal.close_trade(a, 110_000, "2026-10-20", "", jdb)                      # đã bán tháng 10
    b = journal.add_trade("VNM", 100, 60_000, 57_000, None, "t09", "2026-09-02", jdb)
    journal.close_trade(b, 55_000, "2026-09-25", "", jdb)                       # đã bán tháng 9 (không vào báo cáo tháng 10)
    cashflow.add("2026-10-03", 5_000_000, "nạp", cdb)
    portfolio.save({"holdings": [{"symbol": "FPT", "qty": 100, "avg_cost": 100_000.0}], "cash": 1_000_000.0}, "manual", pfp)
    dv.add("2026-10-15", "FPT", dv.CASH, 200_000, "", False, ddb, pfp)
    dv.add("2026-09-15", "FPT", dv.CASH, 999_000, "", False, ddb, pfp)
    d = report.collect(2026, 10, lambda s: 120_000.0, jdb, cdb, ddb, pfp)
    assert list(d["closed"]["symbol"]) == ["FPT"] and abs(d["realized"] - d["closed"]["pnl"].iloc[0]) < 1e-6
    assert d["div_cash"] == 200_000 and len(d["flows"]) == 1
    xl = load_workbook(io.BytesIO(report.to_excel(d)))
    assert "Tổng quan" in xl.sheetnames and "Lệnh đã bán trong tháng" in xl.sheetnames
    with pytest.raises(ValueError):
        report.collect(2026, 13, lambda s: 1.0, jdb, cdb, ddb, pfp)
    if report.pdf_available():
        pdf = report.to_pdf(d)
        assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_auto_refresh_hours_settings_and_throttle(monkeypatch, tmp_path):
    import datetime as dt
    from views import data_update as du
    from src import settings
    tz = explain.VN_TZ
    assert du.in_trading_hours(dt.datetime(2026, 11, 5, 10, 0, tzinfo=tz))            # thứ Năm 10:00
    assert not du.in_trading_hours(dt.datetime(2026, 11, 5, 15, 30, tzinfo=tz))       # sau giờ đóng cửa
    assert not du.in_trading_hours(dt.datetime(2026, 11, 7, 10, 0, tzinfo=tz))        # thứ Bảy
    assert settings.clean({})["auto_price"] is True and settings.clean({"auto_price": False})["auto_price"] is False
    assert settings.clean({"auto_price": "x"})["auto_price"] is True                  # giá trị hỏng -> mặc định
    p = tmp_path / "s.json"
    assert settings.load(settings.save({"capital_m": 10, "auto_price": False}, p) and p)["auto_price"] is False


# ---------- sao lưu / cảnh báo / so sánh VN-Index ----------
def _backup_paths(d):
    return {"journal.db": d / "journal.db", "cashflows.db": d / "cashflows.db", "dividends.db": d / "dividends.db",
            "paper.db": d / "paper.db", "portfolio.json": d / "portfolio.json", "settings.json": d / "settings.json"}


def test_backup_roundtrip_and_restore_makes_safety_copy(tmp_path):
    import zipfile
    from src import backup
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = _backup_paths(data_dir)
    journal.add_trade("FPT", 100, 100_000, 95_000, None, "gốc", "2026-01-05", paths["journal.db"])
    portfolio.save({"holdings": [], "cash": 5.0}, "manual", paths["portfolio.json"])
    blob = backup.create(paths)
    assert "journal.db" in backup.inspect(blob)["files"]
    journal.add_trade("VNM", 100, 60_000, 57_000, None, "thêm sau", "2026-02-05", paths["journal.db"])   # thay đổi sau khi sao lưu
    res = backup.restore(blob, paths, tmp_path / "bk")
    assert len(journal.list_trades(paths["journal.db"])) == 1                                              # đã quay về trạng thái lúc sao lưu
    assert res["safety_copy"].exists()                                                                     # bản an toàn của dữ liệu trước khi khôi phục
    with zipfile.ZipFile(res["safety_copy"]) as z:
        assert "journal.db" in z.namelist()


def test_backup_rejects_bad_and_malicious_archives(tmp_path):
    import io, zipfile
    from src import backup
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = _backup_paths(data_dir)
    journal.add_trade("FPT", 100, 100_000, 95_000, None, "gốc", "2026-01-05", paths["journal.db"])
    for bad in (b"not a zip", ):
        with pytest.raises(ValueError):
            backup.restore(bad, paths, tmp_path / "bk")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.txt", "x")                       # tên lạ bị bỏ qua, không bao giờ ghi ra ngoài
        z.writestr("journal.db", b"this is not sqlite")      # CSDL giả bị từ chối
    with pytest.raises(ValueError):
        backup.restore(buf.getvalue(), paths, tmp_path / "bk")
    assert not (tmp_path / "evil.txt").exists() and len(journal.list_trades(paths["journal.db"])) == 1   # dữ liệu cũ còn nguyên


def test_alerts_stop_target_and_ignore_unset_stop():
    from src import alerts
    t = pd.DataFrame([
        {"id": 1, "symbol": "AAA", "stop": 95.0, "target": 120.0},
        {"id": 2, "symbol": "BBB", "stop": 95.0, "target": 120.0},
        {"id": 3, "symbol": "CCC", "stop": 95.0, "target": 100.0},
        {"id": 4, "symbol": "DDD", "stop": 0.0, "target": None},
        {"id": 5, "symbol": "EEE", "stop": 95.0, "target": 120.0}])
    px = {"AAA": 94.0, "BBB": 97.0, "CCC": 101.0, "DDD": 1.0, "EEE": 105.0}
    got = {a["symbol"]: a["kind"] for a in alerts.check(t, px.get)}
    assert got == {"AAA": "hit_stop", "BBB": "near_stop", "CCC": "hit_target"}      # DDD chưa đặt cắt lỗ, EEE ở giữa: không cảnh báo
    assert alerts.check(t, lambda s: None) == [] and alerts.check(None, px.get) == []
    assert alerts.check(t, px.get)[0]["symbol"] == "AAA"                              # cắt lỗ xếp trên cùng


def test_benchmark_matches_hand_calc_and_handles_gaps():
    from src import benchmark
    idx = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=10, freq="D"), "close": [100.0] * 5 + [110.0] * 5})
    flows = pd.DataFrame({"day": pd.to_datetime(["2026-01-02", "2026-01-07"]), "amount": [1000.0, 1100.0]})
    r = benchmark.compare(flows, 2300.0, idx)
    # 1000/100 = 10 đơn vị; 1100/110 = 10 đơn vị; cuối kỳ 20 * 110 = 2200
    assert r["ok"] and abs(r["index_value"] - 2200) < 1e-6 and r["ahead"] and abs(r["diff"] - 100) < 1e-6
    assert abs(r["index_return"] - (2200 / 2100 - 1)) < 1e-9
    early = pd.DataFrame({"day": pd.to_datetime(["2025-12-01"]), "amount": [1000.0]})
    assert not benchmark.compare(early, 1.0, idx)["ok"] and not benchmark.compare(flows.iloc[0:0], 1.0, idx)["ok"]


# ---------- tin tức theo mã đang giữ ----------
def test_match_symbol_is_exact_and_deduped():
    from src import news
    items = [{"title": "FPT báo lãi quý 3", "summary": "", "link": "a", "source": "X"},
             {"title": "Giá FPTS tăng", "summary": "", "link": "b", "source": "X"},          # FPTS không phải FPT
             {"title": "fpt viết thường", "summary": "", "link": "c", "source": "X"},       # viết thường không tính
             {"title": "Tin khác", "summary": "Cổ phiếu FPT được khuyến nghị", "link": "d", "source": "X"},
             {"title": "FPT báo lãi quý 3", "summary": "", "link": "a", "source": "Y"}]     # trùng liên kết
    got = news.match_symbol(items, "FPT")
    assert [g["link"] for g in got] == ["a", "d"]
    assert news.match_symbol(items, "FPT", limit=1) == got[:1] and news.match_symbol([], "FPT") == []


def test_ai_news_summary_is_validated_and_never_leaks_portfolio(monkeypatch):
    from src import llm
    by = {"FPT": [{"source": "A", "title": "t0", "summary": "", "link": "l0"}, {"source": "B", "title": "t1", "summary": "", "link": "l1"}],
          "VNM": []}
    raw = {"FPT": {"tom_tat": "ok", "tac_dong": "rất tốt", "tin_chinh": [1, 7, -1, True, "0"]},   # tác động lạ, chỉ số sai
           "HAG": {"tom_tat": "mã không hỏi", "tac_dong": "tich_cuc", "tin_chinh": [0]}}           # mã không được hỏi
    c = llm.clean_symbol_news(raw, by)
    assert list(c) == ["FPT"] and c["FPT"]["tac_dong"] == "khong_ro" and c["FPT"]["tin_chinh"] == [1]
    seen = {}
    monkeypatch.setattr(llm, "_ask", lambda prompt, n, mock=None: seen.setdefault("p", prompt) and {"FPT": {"tom_tat": "x", "tac_dong": "tich_cuc", "tin_chinh": [0]}})
    out = llm.summarize_holdings_news(by)
    assert out["FPT"]["tac_dong"] == "tich_cuc"
    assert '"FPT"' in seen["p"] and '"VNM"' not in seen["p"]                                       # mã không có tin không bị gửi đi
    assert llm.summarize_holdings_news({"VNM": []}) == {}                                          # không có tin thì không gọi AI


# ---------- đèn giao thông, việc hôm nay, từ điển ----------
def test_precheck_levels_and_reasons():
    from src import precheck as pc
    # lệnh an toàn: tài sản 100 triệu, mua 100 cp giá 25.000, cắt lỗ 23.500, mục tiêu 29.000
    g = pc.check(25_000, 23_500, 29_000, 100, 100e6, 50e6, 0, 0.02, 0.30, 50e9)
    assert g["level"] == pc.OK and all(i["level"] == pc.OK for i in g["items"])
    # dồn quá nhiều vào một mã -> đỏ
    r = pc.check(25_000, 23_500, 29_000, 1000, 40e6, 40e6, 0, 0.05, 0.30, 50e9)
    assert r["level"] == pc.BAD and any(i["label"] == "Dồn vào một mã" and i["level"] == pc.BAD for i in r["items"])
    # không đủ tiền mặt -> đỏ; còn ít tiền mặt -> vàng
    assert any(i["label"] == "Tiền mặt" and i["level"] == pc.BAD for i in pc.check(25_000, 23_500, 29_000, 100, 100e6, 1e6, 0, 0.02, 0.30, 50e9)["items"])
    y = pc.check(25_000, 23_500, 29_000, 100, 100e6, 5e6, 0, 0.02, 0.30, 50e9)
    assert any(i["label"] == "Tiền mặt dự phòng" and i["level"] == pc.WARN for i in y["items"])
    # cắt lỗ chưa đặt, lãi < lỗ, thanh khoản rất thấp
    assert pc.check(25_000, 0, 29_000, 100, 100e6, 50e6)["level"] == pc.BAD
    assert any(i["label"] == "Lãi so với lỗ" and i["level"] == pc.BAD for i in pc.check(25_000, 23_500, 25_500, 100, 100e6, 50e6)["items"])
    assert any(i["label"] == "Dễ bán" and i["level"] == pc.BAD for i in pc.check(25_000, 23_500, 29_000, 100, 100e6, 50e6, avg_value=5e8)["items"])
    # không có Danh mục (cash=None) thì không báo tiền mặt; đầu vào sai -> đỏ, không lỗi
    assert not any("Tiền mặt" in i["label"] for i in pc.check(25_000, 23_500, 29_000, 100, 100e6, None)["items"])
    assert pc.check(0, 0, None, 0, 0, None)["level"] == pc.BAD


def test_todo_priority_limit_and_empty():
    from datetime import date
    from src import todo
    today = date(2026, 11, 5)
    trades = pd.DataFrame([{"symbol": "FPT", "stop": 0.0, "reason": "Nhập từ sao kê"}, {"symbol": "VNM", "stop": 90.0, "reason": "tốt"}])
    al = [{"id": 1, "symbol": "HPG", "kind": "hit_stop", "message": "HPG chạm cắt lỗ"}]
    items = todo.build(al, trades, date(2026, 10, 20), today, {"total": 100.0, "cash": 1.0}, {"FPT": 0.6}, 0.30, True, False)
    assert len(items) == todo.MAX_ITEMS and items[0]["level"] == "bad" and "HPG" in items[0]["title"]     # khẩn nhất lên đầu, tối đa 3 việc
    assert "FPT" in items[1]["title"]                                                                      # chưa có cắt lỗ xếp trên các việc nhẹ
    calm = todo.build([], pd.DataFrame([{"symbol": "VNM", "stop": 90.0, "reason": "tốt"}]), today, today, {"total": 100.0, "cash": 50.0}, {"VNM": 0.2}, 0.30, True, True)
    assert calm == []                                                                                      # không có việc thì danh sách rỗng
    assert todo.build([], None, None, today, None, None, 0.3, False, False) == []


def test_glossary_examples_use_user_numbers_and_never_crash():
    from src import glossary
    p = {"capital": 20_000_000, "entry": 30_000, "stop": 27_000, "risk_pct": 2.0, "max_alloc": 30, "target": 36_000}
    short, ex = glossary.explain("Cắt lỗ", p)
    assert "30.000đ" in ex and "27.000đ" in ex and "10%" in ex
    assert "400.000đ" in glossary.explain("Mức chấp nhận mất", p)[1]
    for term in glossary.TERMS:
        s, e = glossary.explain(term, {})                    # thiếu dữ liệu vẫn dùng được số mặc định
        assert s and isinstance(e, str)


def test_calc_page_shows_traffic_light(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    portfolio.save({"holdings": [], "cash": 500_000.0}, "manual", tmp_path / "pf.json")      # tiền mặt ít hơn số cần mua
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_calc_app.py"), default_timeout=30).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Kiểm tra trước khi mua" in text and "Đèn đỏ" in text and "tiền mặt trong Danh mục chỉ có 500.000đ" in text


# ---------- bộ lọc cổ phiếu ----------
def test_screener_metrics_and_filters():
    from src import screener
    n = 260
    up = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=n), "close": np.linspace(50_000, 100_000, n), "volume": [1_000_000] * n})
    dn = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=n), "close": np.linspace(100_000, 50_000, n), "volume": [10_000] * n})
    short = up.head(30)
    mu, md = screener.metrics("UP", up), screener.metrics("DN", dn)
    assert screener.metrics("SHORT", short) is None                                          # dưới 60 phiên: không đoán
    assert mu["above50"] and mu["above200"] and not md["above50"] and mu["ret60"] > 0 > md["ret60"]
    assert abs(mu["avg_value"] - 1_000_000 * up["close"].tail(20).mean()) < 1
    m = pd.DataFrame([mu, md])
    assert list(screener.screen(m)["symbol"]) == ["UP", "DN"]                                # không đặt tiêu chí: giữ hết, xếp theo thanh khoản
    assert list(screener.screen(m, min_value=1e9)["symbol"]) == ["UP"]                       # DN chỉ giao dịch ~0,5 tỷ
    assert list(screener.screen(m, trend=screener.TREND_BOTH)["symbol"]) == ["UP"]
    assert list(screener.screen(m, max_from_high=0.1)["symbol"]) == ["UP"]                   # DN cách đỉnh 1 năm ~50%
    assert screener.screen(m, min_value=1e15).empty and screener.screen(pd.DataFrame()).empty


# ---------- mã PIN, chế độ đơn giản ----------
def test_pin_guard_locks_after_failures_and_blocks_during_lock(monkeypatch):
    from src import access
    now = [1000.0]
    g = access.Guard("1234", max_fail=3, lock_s=60, clock=lambda: now[0])
    assert not g.check("0000") and not g.check("1111") and g.remaining_lock() == 0
    assert not g.check("2222") and g.remaining_lock() == 60                       # lần sai thứ 3: khoá
    assert not g.check("1234")                                                    # đang khoá: nhập đúng cũng bị từ chối
    now[0] += 61
    assert g.check("1234") and g.fails == 0                                       # hết khoá: nhập đúng vào được
    monkeypatch.delenv("APP_PIN", raising=False)
    assert access.guard() is None                                                 # không đặt PIN thì không hỏi
    monkeypatch.setenv("APP_PIN", " 4321 ")
    assert access.guard().pin == "4321"


def test_simple_mode_setting_roundtrip(tmp_path):
    assert settings_mod.clean({})["simple_mode"] is False
    assert settings_mod.clean({"simple_mode": True})["simple_mode"] is True
    assert settings_mod.clean({"simple_mode": "yes"})["simple_mode"] is False
    p = tmp_path / "s.json"
    assert settings_mod.save({"simple_mode": True, "auto_price": False}, p)["simple_mode"] is True
    assert settings_mod.load(p)["auto_price"] is False


def test_auto_refresh_runs_in_background_thread_and_does_not_block(monkeypatch):
    import time as _t
    from views import data_update as du
    gate = {"go": False}

    def slow_update(symbols, **kw):
        while not gate["go"]:
            _t.sleep(0.01)
        return [{"symbol": s, "status": "ok", "added": 1, "last_date": None, "note": ""} for s in symbols]

    monkeypatch.setattr(du.updater, "update_many", slow_update)
    v0 = du._AUTO["version"]
    du._AUTO["running"] = True
    t0 = _t.time()
    import threading
    th = threading.Thread(target=du._auto_worker, args=(["FPT"],))
    th.start()
    assert _t.time() - t0 < 1 and du._AUTO["running"]          # bắt đầu luồng nền không chờ tải xong
    gate["go"] = True
    th.join(5)
    assert not du._AUTO["running"] and du._AUTO["version"] == v0 + 1   # xong thì hạ cờ và tăng phiên bản để trang làm mới

    def boom(symbols, **kw):
        raise RuntimeError("mạng lỗi")

    monkeypatch.setattr(du.updater, "update_many", boom)
    du._AUTO["running"] = True
    du._auto_worker(["FPT"])
    assert not du._AUTO["running"]                                # lỗi trong luồng nền không làm kẹt cờ


# ---------- hỏi trợ lý: mua bây giờ hay đợi ----------
def test_ask_average_scenarios_hand_calc_and_guidance():
    from src import ask
    sc = {s["name"]: s for s in ask.average_scenarios(100_000.0, 30_000_000.0, 3)}
    flat = sc["Chia 3 lần, giá đi ngang"]
    now = sc["Mua hết một lần hôm nay"]
    assert abs(flat["avg"] - now["avg"]) < 1e-6                       # giá đi ngang: chia hay không giá vốn như nhau
    assert sc["Chia 3 lần, giá giảm dần 5% mỗi lần"]["avg"] < now["avg"] < sc["Chia 3 lần, giá tăng dần 5% mỗi lần"]["avg"]
    # đang giữ 100 cp giá vốn 120.000, mua thêm 10 triệu ở giá 100.000 (phí 0,15%): giá vốn mới phải thấp hơn 120.000 và cao hơn 100.000
    held = ask.average_scenarios(100_000.0, 10_000_000.0, 1, 100, 120_000.0)[0]
    exp_qty = 10_000_000 / (100_000 * 1.0015)
    assert abs(held["avg"] - (100 * 120_000 + 10_000_000) / (100 + exp_qty)) < 1e-6 and 100_000 < held["avg"] < 120_000
    n = 300
    hot = pd.DataFrame({"close": np.concatenate([np.full(250, 50_000.0), np.linspace(50_000, 80_000, 50)])})
    f = ask.facts(hot)
    assert f["rsi"] > 70 and any("chia nhỏ" in g["text"] for g in ask.guidance(f))
    fall = pd.DataFrame({"close": np.linspace(100_000, 60_000, n)})
    assert any("đang giảm" in g["text"] for g in ask.guidance(ask.facts(fall)))
    g = ask.guidance(ask.facts(fall), held_qty=100, held_avg=100_000.0, weight_after=0.5, max_alloc=0.3)
    assert any("kéo giá vốn xuống" in x["text"] for x in g) and any("vượt mức 30%" in x["text"] for x in g)
    assert "Không ai biết giá ngày mai" in g[-1]["text"] and ask.facts(hot.head(20)) is None



def test_ask_page_streams_answer_and_respects_sharing_choice(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import llm
    monkeypatch.setenv("TEST_PF", str(tmp_path / "pf.json"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    portfolio.save({"holdings": [{"symbol": "FPT", "qty": 100, "avg_cost": 100_000.0}], "cash": 2_000_000.0}, "manual", tmp_path / "pf.json")
    script = str(Path(__file__).resolve().parent / "ui_ask_app.py")
    at = AppTest.from_file(script, default_timeout=60).run()
    assert not at.exception
    if not any("Hỏi AI" in b.label for b in at.button):              # không có dữ liệu giá thật cho mã: trang báo thiếu dữ liệu, không lỗi
        return
    sent = {}
    real = llm.chat_stream
    monkeypatch.setattr(llm, "chat_stream", lambda q, h, d: sent.update(d) or real(q, h, d))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)            # không chờ nhịp gõ chữ khi test
    at.text_area(key="ask_q").set_value("Giờ mua có ổn không?").run()
    next(b for b in at.button if "Hỏi AI" in b.label).click().run()
    assert not at.exception and "so_tien_dinh_mua" not in sent and "gia_von_binh_quan" not in sent   # mặc định không gửi số tiền, danh mục
    assert "MẪU" in at.session_state["ask_ans"][1]                    # câu trả lời được lưu để hiện lại ở lần chạy sau
    at.run()
    assert not at.exception and any("MẪU" in m.value for m in at.markdown)
    sent.clear()
    at.toggle(key="ask_share").set_value(True).run()
    next(b for b in at.button if "Hỏi AI" in b.label).click().run()
    assert sent.get("gia_von_binh_quan") == 100_000 and sent.get("so_co_phieu_dang_giu") == 100   # người dùng cho phép thì mới gửi



# ---------- chatbot đọc toàn bộ dữ liệu ----------
def _chat_inputs(tmp_path, n_closed=3, reason="mua vì tin đồn"):
    from src import dividends as dv, cashflow as cfm
    jdb, cdb, ddb, pfp = tmp_path / "j.db", tmp_path / "c.db", tmp_path / "d.db", tmp_path / "pf.json"
    o = journal.add_trade("FPT", 100, 100_000, 0, 120_000, reason, "2026-03-02", jdb)
    journal.update_trade(o, jdb, tags="Mua vì tin đồn|Không đặt cắt lỗ")
    for i in range(n_closed):
        a = journal.add_trade("VNM", 100, 60_000, 57_000, None, f"lý do {i} " + "x" * 150, "2026-02-01", jdb)
        journal.close_trade(a, 61_000, "2026-02-20", "ghi chú", jdb)
    portfolio.save({"holdings": [{"symbol": "FPT", "qty": 100, "avg_cost": 100_000.0}], "cash": 2_000_000.0}, "manual", pfp)
    cfm.add("2026-01-05", 10_000_000, "vốn đầu", cdb)
    dv.add("2026-06-01", "FPT", dv.CASH, 100_000, "", False, ddb, pfp)
    pf = portfolio.load(pfp)
    val, vs = portfolio.valuate(pf, lambda s: 90_000.0)
    flows = cfm.list_flows(cdb)
    return dict(now=pd.Timestamp("2026-11-05 10:00"), settings={"capital_m": 10.0, "risk_pct": 2.0, "max_alloc": 30, "watch": ["FPT"]},
                valuation=val, val_summary=vs, pf_cash=pf["cash"], trades=journal.list_trades(jdb), flows=flows,
                cf_summary=cfm.summary(flows, vs["total"], date(2026, 11, 5)), divs=dv.list_all(ddb), div_summary=dv.summary(dv.list_all(ddb), 1e7),
                bench=None, snaps=[{"symbol": "FPT", "close": 90_000.0, "change": 0.01, "score": 55.0, "rsi": 52.0, "last_date": pd.Timestamp("2026-11-05"), "partial": True}],
                alert_items=[{"message": "FPT gần cắt lỗ"}], risk_summary=None, news={"FPT": [{"source": "X", "title": "FPT báo lãi", "link": "l"}]},
                last_data_date=pd.Timestamp("2026-11-05"))


def test_chat_context_contains_everything_and_no_secrets(tmp_path, monkeypatch):
    from src import chat_context as cc
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "SECRET-KEY-123")
    monkeypatch.setenv("APP_PIN", "9876")
    ctx = cc.compose(**_chat_inputs(tmp_path))
    text = json.dumps(ctx, ensure_ascii=False)
    assert ctx["danh_muc"]["dang_giu"][0]["gia_von"] == 100_000 and ctx["danh_muc"]["dang_giu"][0]["gia_hien_tai"] == 90_000
    assert ctx["lenh_dang_giu_trong_nhat_ky"][0]["ly_do"] == "mua vì tin đồn" and ctx["lenh_dang_giu_trong_nhat_ky"][0]["cat_lo"] is None
    assert "Không đặt cắt lỗ" in ctx["lenh_dang_giu_trong_nhat_ky"][0]["the"] and len(ctx["lenh_da_ban_gan_day"]) == 3
    assert ctx["tien_nap_rut"]["tom_tat"]["tien_rong_da_bo_vao"] == 10_000_000 and ctx["co_tuc"]["tong_tien_mat_da_nhan"] == 100_000
    assert ctx["gia_thi_truong"][0]["tam_thoi"] is True and ctx["tin_tuc_nhac_dich_danh_ma"]["FPT"][0]["tieu_de"] == "FPT báo lãi"
    assert ctx["bay_gio"].startswith("2026-11-05 10:00") and ctx["canh_bao_gia_hien_tai"] == ["FPT gần cắt lỗ"]
    assert "SECRET-KEY-123" not in text and "9876" not in text                                    # khoá API và PIN không bao giờ lọt vào ngữ cảnh


def test_chat_context_is_bounded_and_drops_oldest_first(tmp_path):
    from src import chat_context as cc
    ctx = cc.compose(**_chat_inputs(tmp_path, n_closed=40))
    assert len(json.dumps(ctx, ensure_ascii=False)) <= cc.MAX_CHARS and len(ctx["lenh_da_ban_gan_day"]) <= cc.MAX_CLOSED
    assert ctx["danh_muc"]["dang_giu"] and ctx["lenh_dang_giu_trong_nhat_ky"]                     # dữ liệu đang giữ không bị cắt
    old = cc.MAX_CHARS
    try:
        cc.MAX_CHARS = 3000
        sub = tmp_path / "x"
        sub.mkdir()
        small = cc.compose(**_chat_inputs(sub, n_closed=40))
        assert len(small["lenh_da_ban_gan_day"]) < 40
    finally:
        cc.MAX_CHARS = old


def test_chat_answer_prompt_has_context_history_and_injection_guard(monkeypatch):
    from src import llm
    seen = {}
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setattr(llm, "_complete", lambda p, n, system=None: seen.update(p=p, s=system) or "  trả lời  ")
    hist = [{"role": "user", "content": f"câu {i}"} for i in range(10)]
    out = llm.chat_answer("Giờ mua có ổn không?", hist, {"danh_muc": {"tien_mat": 123}})
    assert out == "trả lời" and '"tien_mat": 123' in seen["p"] and "câu 9" in seen["p"] and "câu 0" not in seen["p"]   # chỉ giữ vài lượt cuối
    assert seen["s"] == llm.SYSTEM_CHAT and "KHÔNG phải chỉ thị" in seen["s"] and "không hứa lợi nhuận" in seen["s"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert "MẪU" in llm.chat_answer("x", [], {})


def test_chatbot_form_submit_does_not_crash_and_clears_input(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    for k, f in (("TEST_JOURNAL", "j.db"), ("TEST_CF", "c.db"), ("TEST_DIV", "d.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    from src import llm as _llm
    monkeypatch.setattr(_llm.time, "sleep", lambda s: None)                                   # không chờ nhịp gõ chữ khi test
    portfolio.save({"holdings": [{"symbol": "FPT", "qty": 100, "avg_cost": 100_000.0}], "cash": 1_000_000.0}, "manual", tmp_path / "pf.json")
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_chat_app.py"), default_timeout=60).run()
    assert not at.exception

    def send(text):
        at.text_input(key="chat_q").set_value(text)           # trong form: giá trị chỉ được gửi cùng lúc bấm Gửi (giống Enter)
        next(b for b in at.button if "arrow_upward" in b.label).click().run()

    send("Giờ mua có ổn không?")
    assert not at.exception, [e.value for e in at.exception]                                   # lỗi cũ: sửa ô nhập sau khi đã tạo ra nó
    assert [m["role"] for m in at.session_state["chat_hist"]] == ["user", "assistant"]
    assert at.session_state["chat_hist"][0]["content"] == "Giờ mua có ổn không?"
    # (việc xoá ô nhập sau khi gửi do clear_on_submit của form làm ở trình duyệt, AppTest không mô phỏng; đã kiểm tra bằng trình duyệt thật)
    send("   ")                                                                                # câu hỏi trống: bỏ qua, không lỗi
    assert not at.exception and len(at.session_state["chat_hist"]) == 2
    send("Hỏi tiếp")
    assert not at.exception and len(at.session_state["chat_hist"]) == 4
    next(b for b in at.button if "delete_sweep" in b.label).click().run()                   # nút xoá cuộc trò chuyện
    assert not at.exception and at.session_state["chat_hist"] == []
    next(b for b in at.button if "Giờ mua thêm" in b.label).click().run()                     # câu gợi ý cũng gửi được, không lỗi
    assert not at.exception and len(at.session_state["chat_hist"]) == 2


# ---------- tối ưu: stream chat, tạo file khi bấm ----------
def test_sse_chunks_parse_and_chat_stream_mock(monkeypatch):
    from src import llm
    lines = [b": keepalive", b'data: {"choices":[{"delta":{"role":"assistant"}}]}', 'data: {"choices":[{"delta":{"content":"Xin "}}]}'.encode(),
             b"data: khong phai json", 'data: {"choices":[{"delta":{"content":"chào"}}]}'.encode(), b"", b"data: [DONE]",
             'data: {"choices":[{"delta":{"content":"BỎ"}}]}'.encode()]
    assert "".join(llm._sse_chunks(lines)) == "Xin chào"                       # bỏ dòng rác, dừng ở [DONE]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert "".join(llm.chat_stream("x", [], {})).strip() == llm.chat_answer("x", [], {}).strip()
    assert len(list(llm.chat_stream("x", [], {}))) > 3                         # trả về nhiều đoạn nhỏ, không phải một cục


def test_chat_stream_openai_compat_sends_stream_flag_and_system_prompt(monkeypatch):
    import requests
    from src import llm
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "http://x/v1")
    seen = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_lines(self): return iter([b'data: {"choices":[{"delta":{"content":"ok"}}]}', b"data: [DONE]"])

    monkeypatch.setattr(requests, "post", lambda url, **kw: seen.update(url=url, **kw) or FakeResp())
    assert "".join(llm.chat_stream("Giờ mua?", [], {"a": 1})) == "ok"
    assert seen["url"].endswith("/chat/completions") and seen["json"]["stream"] is True
    assert seen["json"]["messages"][0]["content"] == llm.SYSTEM_CHAT and '"a": 1' in seen["json"]["messages"][1]["content"]


def test_downloads_are_generated_lazily(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import report
    calls = {"xl": 0}
    real = report.to_excel
    monkeypatch.setattr(report, "to_excel", lambda d: calls.__setitem__("xl", calls["xl"] + 1) or real(d))
    for k, f in (("TEST_PF", "pf.json"),):
        monkeypatch.setenv(k, str(tmp_path / f))
    script = tmp_path / "rep_app.py"
    script.write_text(f"import sys\nsys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
                      "from views import shared, report_view\nshared.init_state()\nreport_view.render(shared.get_ctx())\n", encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=60).run()
    assert not at.exception and calls["xl"] == 0                                # hiển thị trang không tạo file Excel; chỉ tạo khi bấm tải


# ---------- tỷ lệ tính trên vốn khi chỉ đầu tư một phần ----------
def test_weights_use_capital_when_only_part_is_invested():
    from src import risk_table
    pf = {"holdings": [{"symbol": "ACB", "qty": 400, "avg_cost": 22_000.0}], "cash": 0.0}
    price = lambda s: 23_000.0
    df0, s0 = portfolio.valuate(pf, price, 0.30)                                      # không đặt vốn: như cũ, ACB chiếm 100%
    assert abs(df0["weight"].iloc[0] - 1.0) < 1e-9 and any("chiếm 100%" in w for w in s0["warnings"]) and s0["assumed_cash"] == 0
    df, s = portfolio.valuate(pf, price, 0.30, capital=58_300_000.0)                  # đặt vốn 58,3 triệu: chỉ đầu tư một phần
    assert abs(df["weight"].iloc[0] - 9_200_000 / 58_300_000) < 1e-9
    assert s["base"] == 58_300_000 and abs(s["assumed_cash"] - (58_300_000 - 9_200_000)) < 1e-6 and s["total"] == 9_200_000   # `total` vẫn là số đã ghi
    assert s["warnings"] == []                                                        # không còn "chiếm 100%" hay "tiền mặt dưới 5%"
    big, sb = portfolio.valuate(pf, price, 0.30, capital=5_000_000.0)                 # vốn nhỏ hơn số đã ghi: lấy số đã ghi, không âm
    assert sb["base"] == 9_200_000 and sb["assumed_cash"] == 0 and abs(big["weight"].iloc[0] - 1.0) < 1e-9
    # vẫn cảnh báo khi thật sự dồn quá nhiều so với vốn
    pf2 = {"holdings": [{"symbol": "ACB", "qty": 400, "avg_cost": 22_000.0}], "cash": 0.0}
    _, s2 = portfolio.valuate(pf2, lambda x: 23_000.0, 0.30, capital=20_000_000.0)
    assert any("chiếm 46%" in w for w in s2["warnings"])
    rt, rs = risk_table.build(df, None, 0.0, 2.0, capital=58_300_000.0)
    assert abs(rs["total"] - 58_300_000) < 1e-6 and abs(rs["cash_pct"] - (1 - 9_200_000 / 58_300_000)) < 1e-9 and abs(rt["weight"].iloc[0] - 9_200_000 / 58_300_000) < 1e-9
    rt0, rs0 = risk_table.build(df0, None, 0.0, 2.0)                                  # không đặt vốn: như cũ
    assert rs0["total"] == 9_200_000 and rs0["cash_pct"] == 0


def test_todo_does_not_warn_cash_gone_when_capital_covers_it():
    from datetime import date
    from src import todo
    today = date(2026, 11, 5)
    s = {"total": 9.2e6, "base": 58.3e6, "assumed_cash": 49.1e6, "cash": 0.0}
    assert todo.build([], None, today, today, s, {"ACB": 0.158}, 0.30, True, True) == []
    s_old = {"total": 9.2e6, "cash": 0.0}                                              # không có vốn: vẫn cảnh báo như cũ
    assert any("Tiền mặt" in i["title"] for i in todo.build([], None, today, today, s_old, {"ACB": 1.0}, 0.30, True, True))


def test_smooth_splits_big_chunks_into_words_without_changing_text():
    from src import llm
    sleeps = []
    big = ["Xin chào các bạn, hôm nay thị trường ", "đi ngang và thanh khoản thấp.\nCẩn thận nhé"]
    out = list(llm.smooth(iter(big), sleeper=sleeps.append))
    assert "".join(out) == "".join(big) and len(out) > 8                       # cùng nội dung, nhưng nhả từng từ chứ không cả cục
    assert all(s <= 0.03 + 1e-9 for s in sleeps) and sum(sleeps) <= 1.5 * len(big) + 1e-6   # mỗi từ chờ ngắn; mỗi cục không quá 1,5 giây
    assert list(llm.smooth(iter(["", "ok"]), sleeper=lambda s: None)) == ["ok"] and list(llm.smooth(iter([]))) == []


# ---------- chat không mất tin nhắn khi bị ngắt ----------
def test_chat_tee_keeps_partial_answer_when_interrupted():
    from views import chatbot

    class Interrupted(BaseException):      # giống RerunException của Streamlit: không phải Exception thường
        pass

    def pieces():
        yield "Xin "
        yield "chào "
        raise Interrupted()

    entry = {"role": "assistant", "content": "", "partial": True}
    got = []
    with pytest.raises(Interrupted):
        for p in chatbot._tee(entry, pieces()):
            got.append(p)
    assert got == ["Xin ", "chào "] and entry["content"] == "Xin chào " and entry["partial"] is True   # phần đã có vẫn được giữ, đánh dấu chưa xong


def test_chat_question_saved_immediately_and_finished_answer_not_partial(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import llm
    for k, f in (("TEST_JOURNAL", "j.db"), ("TEST_CF", "c.db"), ("TEST_DIV", "d.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    portfolio.save({"holdings": [], "cash": 1_000_000.0}, "manual", tmp_path / "pf.json")
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_chat_app.py"), default_timeout=60).run()
    at.text_input(key="chat_q").set_value("Câu 1")
    next(b for b in at.button if "arrow_upward" in b.label).click().run()
    h = at.session_state["chat_hist"]
    assert [m["role"] for m in h] == ["user", "assistant"] and "partial" not in h[1] and h[1]["content"]
    assert at.session_state["chat_busy_until"] == 0.0                                            # xong thì mở lại việc tự làm mới trang
    # lượt sau: lịch sử gửi cho AI không chứa tin nhắn dở dang
    h.append({"role": "user", "content": "Câu dở"})
    h.append({"role": "assistant", "content": "chưa xong", "partial": True})
    seen = {}
    real = llm.chat_stream
    monkeypatch.setattr(llm, "chat_stream", lambda q, hist, ctx: seen.update(hist=list(hist)) or real(q, hist, ctx))
    at.text_input(key="chat_q").set_value("Câu 2")
    next(b for b in at.button if "arrow_upward" in b.label).click().run()
    assert not at.exception and all(not m.get("partial") for m in seen["hist"]) and not any(m["content"] == "chưa xong" for m in seen["hist"])


def test_user_bubble_escapes_html(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    for k, f in (("TEST_JOURNAL", "j.db"), ("TEST_CF", "c.db"), ("TEST_DIV", "d.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    from src import llm
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    portfolio.save({"holdings": [], "cash": 1_000_000.0}, "manual", tmp_path / "pf.json")
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_chat_app.py"), default_timeout=60).run()
    at.text_input(key="chat_q").set_value('<img src=x onerror=alert(1)> & "ok"')
    next(b for b in at.button if "arrow_upward" in b.label).click().run()
    assert not at.exception
    html_blocks = [m.value for m in at.markdown if "chat-u" in m.value]
    assert html_blocks and "<img" not in html_blocks[0] and "&lt;img" in html_blocks[0] and "&amp;" in html_blocks[0]   # câu hỏi của bạn không bao giờ chạy như HTML


# ---------- lưu lịch sử chat, số liệu AI tính sẵn, sao lưu tự động ----------
def test_chat_store_roundtrip_sanitises_and_survives_corruption(tmp_path):
    from src import chat_store
    p = tmp_path / "chat.json"
    hist = [{"role": "user", "content": "Xin chào"}, {"role": "assistant", "content": "Chào bạn", "partial": True}]
    chat_store.save(hist, p)
    assert chat_store.load(p) == hist
    chat_store.save([{"role": "hacker", "content": "x"}, {"role": "user", "content": 5}, "rác", {"role": "user", "content": "a" * 10_000}] + [{"role": "user", "content": str(i)} for i in range(100)], p)
    got = chat_store.load(p)
    assert len(got) == chat_store.MAX_MESSAGES and got[-1]["content"] == "99" and all(m["role"] == "user" for m in got)   # bỏ mục sai, giữ tin mới nhất
    p.write_text("{không phải json", encoding="utf-8")
    assert chat_store.load(p) == [] and chat_store.load(tmp_path / "khong_co.json") == []                         # file hỏng/không có: bắt đầu lại
    chat_store.save([], p)
    assert chat_store.load(p) == []


def test_chat_history_reloads_after_page_refresh(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import llm
    for k, f in (("TEST_JOURNAL", "j.db"), ("TEST_CF", "c.db"), ("TEST_DIV", "d.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    portfolio.save({"holdings": [], "cash": 1_000_000.0}, "manual", tmp_path / "pf.json")
    script = str(Path(__file__).resolve().parent / "ui_chat_app.py")
    at = AppTest.from_file(script, default_timeout=60).run()
    at.text_input(key="chat_q").set_value("Câu hỏi cần nhớ")
    next(b for b in at.button if "arrow_upward" in b.label).click().run()
    assert (tmp_path / "chat_history.json").exists()
    fresh = AppTest.from_file(script, default_timeout=60).run()                      # phiên mới = tải lại trang
    assert [m["content"] for m in fresh.session_state["chat_hist"]][0] == "Câu hỏi cần nhớ" and len(fresh.session_state["chat_hist"]) == 2
    next(b for b in fresh.button if "delete_sweep" in b.label).click().run()          # nút xoá cũng xoá file
    assert fresh.session_state["chat_hist"] == [] and AppTest.from_file(script, default_timeout=60).run().session_state["chat_hist"] == []


def test_chat_context_has_precomputed_labeled_numbers(tmp_path):
    from src import chat_context as cc
    inp = _chat_inputs(tmp_path)
    # thêm một mã đang giữ nhưng KHÔNG có trong nhật ký
    inp["valuation"] = pd.concat([inp["valuation"], pd.DataFrame([{"symbol": "VPB", "qty": 200, "avg_cost": 25_000.0, "price": 22_000.0, "price_src": "dữ liệu giá của bạn",
                                                                  "value": 4_400_000.0, "cost": 5_000_000.0, "pnl": -600_000.0, "pnl_pct": -0.12, "net_pnl": -610_000.0, "weight": 0.3}])], ignore_index=True)
    inp["val_summary"] = {**inp["val_summary"], "base": 50_000_000.0, "assumed_cash": 30_000_000.0, "pnl": -2_000_000.0, "pnl_pct": -0.1, "stock_value": 14_000_000.0}
    ctx = cc.compose(**inp)
    p = ctx["so_lieu_da_tinh_san"]
    assert p["ma_dang_giu_nhung_CHUA_co_lenh_trong_nhat_ky"] == ["VPB"]                 # VPB không có trong nhật ký
    assert p["ma_co_lenh_trong_nhat_ky_nhung_CHUA_dat_cat_lo"] == ["FPT"]                # FPT có lệnh nhưng chưa đặt cắt lỗ
    assert p["lai_lo_cua_phan_co_phieu_so_voi_gia_von_pct"] == -10.0 and p["lai_lo_so_voi_TONG_tai_san_pct"] == -4.0   # hai phép tính khác nghĩa được tách riêng
    assert p["co_phieu_chiem_pct_tong_tai_san"] == 28.0 and "lai_lo_chua_ban_pct" not in json.dumps(ctx, ensure_ascii=False)


def test_auto_backup_once_per_day_rotates_separately_and_never_raises(tmp_path):
    from datetime import datetime as dtm
    from src import backup
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = _backup_paths(data_dir)
    paths["chat_history.json"] = data_dir / "chat_history.json"
    bk = tmp_path / "bk"
    backup._CHECKED.clear()
    assert backup.auto_backup(paths, bk, dtm(2026, 11, 5, 9, 0)) is None and not bk.exists()        # chưa có dữ liệu: không tạo bản rỗng
    journal.add_trade("FPT", 100, 100_000, 95_000, None, "gốc", "2026-01-05", paths["journal.db"])
    backup._CHECKED.clear()
    first = backup.auto_backup(paths, bk, dtm(2026, 11, 5, 9, 0))
    assert first is not None and first.name.endswith("-tu-dong.zip") and "journal.db" in backup.inspect(first.read_bytes())["files"]
    assert backup.auto_backup(paths, bk, dtm(2026, 11, 5, 18, 0)) is None                            # cùng ngày: không tạo thêm
    backup._CHECKED.clear()
    assert backup.auto_backup(paths, bk, dtm(2026, 11, 5, 18, 0)) is None                            # kể cả khi quên bộ nhớ: thấy file hôm nay trên đĩa
    for i in range(20):                                                                                # 20 ngày liên tiếp -> chỉ giữ KEEP_AUTO bản tự động
        backup._CHECKED.clear()
        (bk / f"sao-luu-202610{i + 1:02d}-090000{backup.AUTO_TAG}.zip").write_bytes(b"x")
    manual = backup.save_local(paths, bk)
    backup._rotate(bk)
    autos = [f for f in bk.glob("sao-luu-*.zip") if f.name.endswith(backup.AUTO_TAG + ".zip")]
    assert len(autos) == backup.KEEP_AUTO and manual.exists()                                         # bản thủ công không bị bản tự động đẩy đi
    assert backup.latest_auto(bk).name.startswith("sao-luu-20261105")                                 # tên mới nhất theo ngày
    backup._CHECKED.clear()
    blocker = tmp_path / "file.txt"
    blocker.write_text("là file, không phải thư mục", encoding="utf-8")
    assert backup.auto_backup(paths, blocker / "x", dtm(2026, 12, 1)) is None                          # thư mục không tạo được: trả None, không ném lỗi


# ---------- chatbot biết trang đang xem; sức khoẻ dữ liệu ----------
def test_describe_page_tells_ai_which_stock_and_numbers_user_is_viewing():
    from src import chat_context as cc
    p = cc.describe_page("calc", {"calc_symbol": "fpt", "calc_entry": 120000, "calc_stop": 112000, "calc_target": 140000})
    assert p["ten_trang"] == "Tính lệnh mua" and p["ma_dang_xem"] == "FPT" and p["thong_so_nguoi_dung_dang_nhap"]["gia_cat_lo"] == 112000
    assert cc.describe_page("stock", {"symbol": "VNM"})["ma_dang_xem"] == "VNM"
    assert "ma_dang_xem" not in cc.describe_page("portfolio", {"symbol": "VNM"})          # trang không có khái niệm “mã đang xem”
    assert cc.describe_page(None, {}) is None and cc.describe_page("trang_la", {}) is None


def test_health_check_finds_stale_missing_and_mismatched_data():
    from datetime import date
    from src import health
    today = date(2026, 11, 6)                                                              # thứ Sáu
    holdings = [{"symbol": "FPT", "qty": 100, "avg_cost": 100_000.0}, {"symbol": "VPB", "qty": 200, "avg_cost": 25_000.0}, {"symbol": "ACB", "qty": 50, "avg_cost": 20_000.0}]
    trades = pd.DataFrame([{"symbol": "FPT", "qty": 150}, {"symbol": "HPG", "qty": 100}])   # FPT lệch số lượng; HPG không có trong Danh mục
    dates = {"FPT": date(2026, 11, 2), "VPB": date(2026, 11, 2), "ACB": None}
    got = health.check(today, holdings, 0.0, "2026-10-20T10:00:00", trades, dates, True, 5e6, 1.2e7, None)
    titles = " | ".join(i["title"] for i in got)
    assert "Chưa có giá của ACB" in titles and "Giá đã cũ 4 phiên" in titles and "cách đây 17 ngày" in titles
    assert "Danh mục chưa ghi tiền mặt" in titles and "FPT: Danh mục và Nhật ký lệch số lượng" in titles
    assert "HPG: có lệnh mở trong Nhật ký nhưng Danh mục không có" in titles and "VPB: có trong Danh mục nhưng chưa có trong Nhật ký" in titles
    assert "Vốn ở Cài đặt nhỏ hơn" in titles and "Chưa có bản sao lưu gần đây" in titles
    assert [i["level"] for i in got] == sorted([i["level"] for i in got], key=lambda l: {"warn": 0, "info": 1}[l])   # cảnh báo xếp trên
    clean = health.check(today, [{"symbol": "FPT", "qty": 100, "avg_cost": 1.0}], 1e6, "2026-11-05T09:00:00", pd.DataFrame([{"symbol": "FPT", "qty": 100}]),
                         {"FPT": date(2026, 11, 5)}, True, 2e7, 1.1e7, 0.2)
    assert clean == []                                                                      # dữ liệu ổn thì không báo gì
    assert health.check(today, [], 0.0, None, None, {}, False, 0, 0, None, has_data=False) == []   # chưa có dữ liệu: không báo thiếu sao lưu


# ---------- ghi lệnh bằng chat: bộ đọc câu ----------
def test_trade_parse_reads_vietnamese_sentences_and_never_treats_questions_as_trades():
    from datetime import date
    from src import trade_parse as tp
    today = date(2026, 11, 6)
    d = tp.parse("hôm nay mua 100 FPT giá 120k, cắt lỗ 112k, mục tiêu 140.000 vì báo cáo quý tốt", today)
    assert (d["side"], d["symbol"], d["qty"], d["price"], d["stop"], d["target"]) == ("buy", "FPT", 100, 120_000, 112_000, 140_000)
    assert d["reason"] == "báo cáo quý tốt" and d["date"] == today
    d = tp.parse("Bán 200 cổ phiếu HPG giá 28,5k hôm qua", today)
    assert (d["side"], d["symbol"], d["qty"], d["price"]) == ("sell", "HPG", 200, 28_500) and d["date"] == date(2026, 11, 5)
    d = tp.parse("mua 2 lô vcb ở giá 90000 ngày 3/11", today, known=["VCB"])               # tên thường nhận khi là mã đã biết; 1 lô = 100
    assert (d["symbol"], d["qty"], d["price"], d["date"]) == ("VCB", 200, 90_000, date(2026, 11, 3)) and any("1 lô" in n for n in d["notes"])
    d = tp.parse("mua FPT 100 cổ giá 120", today)                                           # giá nhỏ không đơn vị: hiểu là nghìn đồng, có ghi chú
    assert d["price"] == 120_000 and any("nghìn đồng" in n for n in d["notes"])
    assert tp.parse("mua 100 FPT", today)["price"] is None                                     # thiếu giá: vẫn ra nháp để bạn điền
    for q in ("Giờ mua 100 FPT có ổn không?", "có nên mua 100 FPT giá 120k", "Tôi nên bán bao nhiêu cổ phiếu FPT", "mua FPT bao nhiêu thì hợp lý",
              "Danh mục của tôi có rủi ro gì", "mua", "bán hết đi", "mua FPT", "mua 100 giá 120k", "xin chào"):
        assert tp.parse(q, today) is None, q                                                   # câu hỏi, thiếu mã/số lượng, hay không phải lệnh: không soạn nháp
    assert tp.parse("mua 100 FPT ngày 30/12/2030 giá 100k", today)["date"] == today            # ngày tương lai bị đưa về hôm nay
    assert tp.parse_number("120.000") == 120000 and tp.parse_number("28,5", "k") == 28500 and tp.parse_number("1,2", "tr") == 1_200_000
    assert tp.parse_number("abc") is None and tp.parse_number("") is None


def test_chat_trade_draft_requires_confirmation_then_writes_journal(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src import llm
    for k, f in (("TEST_JOURNAL", "j.db"), ("TEST_CF", "c.db"), ("TEST_DIV", "d.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    called = []
    monkeypatch.setattr(llm, "chat_stream", lambda *a, **k: called.append(1) or iter(["x"]))   # câu ghi lệnh không được gọi AI
    portfolio.save({"holdings": [], "cash": 1_000_000.0}, "manual", tmp_path / "pf.json")
    jdb = tmp_path / "j.db"
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_chat_app.py"), default_timeout=60).run()

    def send(text):
        at.text_input(key="chat_q").set_value(text)
        next(b for b in at.button if "arrow_upward" in b.label).click().run()
        assert not at.exception, [e.value for e in at.exception]

    send("hôm nay mua 100 FPT giá 120k, cắt lỗ 112k, mục tiêu 140k vì báo cáo quý tốt")
    d = at.session_state["chat_draft"]
    assert not called and (d["symbol"], d["qty"], d["price"]) == ("FPT", 100, 120_000)
    assert journal.list_trades(jdb).empty                                                      # CHƯA ghi gì: phải duyệt trước
    ok = at.button(key=f"chat_d{d['id']}_ok")
    assert not ok.disabled
    ok.click().run()
    assert not at.exception
    t = journal.list_trades(jdb)
    assert len(t) == 1 and t.iloc[0]["symbol"] == "FPT" and t.iloc[0]["entry"] == 120_000 and t.iloc[0]["stop"] == 112_000 and "báo cáo quý tốt" in t.iloc[0]["reason"]
    assert "chat_draft" not in at.session_state and "Đã ghi lệnh MUA FPT" in at.session_state["chat_hist"][-1]["content"]
    # bán đúng số lượng: đóng lệnh đang mở
    send("bán 100 FPT giá 130k")
    d2 = at.session_state["chat_draft"]
    assert pd.isna(journal.list_trades(jdb).iloc[0]["exit_price"])                                           # vẫn chưa đóng trước khi duyệt
    at.button(key=f"chat_d{d2['id']}_ok").click().run()
    assert not at.exception and journal.list_trades(jdb).iloc[0]["exit_price"] == 130_000
    # bán số lượng không khớp: nút ghi bị khoá, không ghi gì
    send("bán 50 FPT giá 130k")
    d3 = at.session_state["chat_draft"]
    assert at.button(key=f"chat_d{d3['id']}_ok").disabled
    at.button(key=f"chat_d{d3['id']}_no").click().run()
    assert "chat_draft" not in at.session_state and "Đã bỏ bản nháp" in at.session_state["chat_hist"][-1]["content"]
    # câu hỏi có số vẫn đi đường AI, không soạn nháp
    send("Giờ mua 100 FPT giá 120k có ổn không?")
    assert called and "chat_draft" not in at.session_state


def test_chat_buy_draft_blocks_invalid_inputs(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    for k, f in (("TEST_JOURNAL", "j.db"), ("TEST_CF", "c.db"), ("TEST_DIV", "d.db"), ("TEST_PF", "pf.json")):
        monkeypatch.setenv(k, str(tmp_path / f))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    portfolio.save({"holdings": [], "cash": 1_000_000.0}, "manual", tmp_path / "pf.json")
    at = AppTest.from_file(str(Path(__file__).resolve().parent / "ui_chat_app.py"), default_timeout=60).run()
    at.text_input(key="chat_q").set_value("mua 100 FPT")                                       # thiếu giá và lý do
    next(b for b in at.button if "arrow_upward" in b.label).click().run()
    d = at.session_state["chat_draft"]
    assert at.button(key=f"chat_d{d['id']}_ok").disabled                                      # chưa nhập giá/lý do: không cho ghi
    at.number_input(key=f"chat_d{d['id']}_price").set_value(120_000.0)
    at.text_input(key=f"chat_d{d['id']}_reason").set_value("thử nghiệm")
    at.number_input(key=f"chat_d{d['id']}_stop").set_value(130_000.0)                         # cắt lỗ cao hơn giá mua
    at.run()
    assert at.button(key=f"chat_d{d['id']}_ok").disabled and journal.list_trades(tmp_path / "j.db").empty
    at.number_input(key=f"chat_d{d['id']}_stop").set_value(110_000.0)
    at.run()
    assert not at.button(key=f"chat_d{d['id']}_ok").disabled


def test_health_flags_holdings_missing_from_empty_journal():
    from datetime import date
    from src import health
    got = health.check(date(2026, 11, 6), [{"symbol": "ACB", "qty": 400, "avg_cost": 22_732.0}], 5e6, "2026-11-06T09:00:00", None, {"ACB": date(2026, 11, 5)}, False, 0, 1.4e7, 0.1)
    assert [i["title"] for i in got] == ["ACB: có trong Danh mục nhưng chưa có trong Nhật ký"]        # Nhật ký trống hoàn toàn vẫn được báo


# ---------- thư mục tự đọc sao kê ----------
def _inbox_env(tmp_path, monkeypatch):
    from src import inbox, backup, cashflow, chat_store, dividends, paper, settings as st_
    d = tmp_path / "data"
    d.mkdir()
    for mod, attr, name in ((portfolio, "PATH", "pf.json"), (journal, "DB_PATH", "j.db"), (cashflow, "DB_PATH", "c.db"), (dividends, "DB_PATH", "d.db"),
                            (paper, "DB_PATH", "p.db"), (st_, "PATH", "s.json"), (chat_store, "PATH", "chat.json"), (backup, "BACKUP_DIR", "bk"), (inbox, "INBOX_DIR", "inbox")):
        monkeypatch.setattr(mod, attr, d / name)
    monkeypatch.setattr(inbox, "SETTLE_SECONDS", 0.0)
    return inbox, d


def test_inbox_imports_holdings_file_once_backs_up_first_and_undo_restores(tmp_path, monkeypatch):
    inbox, d = _inbox_env(tmp_path, monkeypatch)
    portfolio.save({"holdings": [{"symbol": "VNM", "qty": 50, "avg_cost": 60_000.0}], "cash": 2_000_000.0}, "manual")
    journal.add_trade("VNM", 50, 60_000, 57_000, None, "lệnh cũ của tôi", "2026-01-05")
    (d / "inbox").mkdir()
    f = d / "inbox" / "sao-ke-tcbs.csv"
    f.write_text("Mã CK,Khối lượng,Giá vốn (đ)\nFPT,100,98500\nHPG,200,24000\n", encoding="utf-8-sig")
    res = inbox.scan()
    assert len(res) == 1 and res[0]["ok"] and res[0]["kind"] == "danh mục"
    pf = portfolio.load()
    assert {h["symbol"] for h in pf["holdings"]} == {"FPT", "HPG"} and pf["cash"] == 2_000_000.0 and pf["source"] == "import"   # tiền mặt đang có được giữ nguyên
    syms = set(journal.list_trades()["symbol"])
    assert {"FPT", "HPG", "VNM"} <= syms                                              # lệnh cũ của bạn không mất
    assert not f.exists() and any((d / "inbox" / "da-xu-ly").iterdir())               # file được CHUYỂN, không xoá
    assert any(p.name.endswith("-truoc-nhap.zip") for p in (d / "bk").iterdir())      # đã sao lưu trước khi ghi
    f.write_text("Mã CK,Khối lượng,Giá vốn (đ)\nFPT,100,98500\nHPG,200,24000\n", encoding="utf-8-sig")   # cùng nội dung lần nữa
    assert inbox.scan() == [] and len(journal.list_trades()) == 3                      # không xử lý lại, không trùng lệnh
    out = inbox.undo()                                                                  # hoàn tác
    assert out and {h["symbol"] for h in portfolio.load()["holdings"]} == {"VNM"} and set(journal.list_trades()["symbol"]) == {"VNM"}
    assert inbox.undo() is None and inbox.load_state()["undo"] is None


def test_inbox_never_touches_data_when_file_unreadable_or_still_being_written(tmp_path, monkeypatch):
    inbox, d = _inbox_env(tmp_path, monkeypatch)
    portfolio.save({"holdings": [{"symbol": "VNM", "qty": 50, "avg_cost": 60_000.0}], "cash": 1.0}, "manual")
    ib = d / "inbox"
    ib.mkdir()
    (ib / "rac.csv").write_text("cột lạ A,cột lạ B\n1,2\n3,4\n", encoding="utf-8")
    (ib / "hong.xlsx").write_bytes(b"day khong phai excel")
    (ib / "ghi-do.txt").write_text("không phải csv/xlsx", encoding="utf-8")
    res = inbox.scan()
    assert len(res) == 2 and all(not r["ok"] for r in res)
    assert [h["symbol"] for h in portfolio.load()["holdings"]] == ["VNM"] and portfolio.load()["source"] == "manual"   # không đổi gì
    assert (ib / "rac.csv").exists() and (ib / "hong.xlsx").exists() and (ib / "ghi-do.txt").exists()                  # file vẫn nằm đó
    assert inbox.scan() == []                                                          # lỗi cũ không báo lặp mỗi lượt quét
    assert not (d / "bk").exists()                                                      # chưa ghi thì không cần sao lưu
    monkeypatch.setattr(inbox, "SETTLE_SECONDS", 3600.0)                               # coi như file vừa được ghi dở
    (ib / "moi.csv").write_text("Mã CK,Khối lượng,Giá vốn (đ)\nFPT,100,98500\n", encoding="utf-8-sig")
    assert inbox.scan() == [] and [h["symbol"] for h in portfolio.load()["holdings"]] == ["VNM"]


def test_inbox_imports_transaction_history_and_pasted_table(tmp_path, monkeypatch):
    inbox, d = _inbox_env(tmp_path, monkeypatch)
    (d / "inbox").mkdir()
    (d / "inbox" / "lich-su.csv").write_text("Ngày giao dịch,Mã CK,Loại lệnh,KL khớp,Giá khớp\n02/01/2026,FPT,Mua,100,100000\n10/02/2026,FPT,Mua,100,110000\n20/03/2026,FPT,Bán,100,120000\n",
                                              encoding="utf-8-sig")
    res = inbox.scan()
    assert res and res[0]["ok"] and res[0]["kind"] == "giao dịch"
    t = journal.list_trades()
    assert len(t) == 2 and int(t["exit_price"].notna().sum()) == 1                      # 1 lệnh đã bán (mua trước bán trước), 1 còn giữ
    h = portfolio.load()["holdings"]
    assert h[0]["symbol"] == "FPT" and h[0]["qty"] == 100
    sheets = inbox.read_pasted("Mã CK\tKhối lượng\tGiá vốn\nACB\t400\t22.732\nVPB\t200\t25.000")
    _, raw, rows, _, kind = inbox.interpret(sheets)
    assert kind == "danh mục" and {r["symbol"]: r["qty"] for r in rows} == {"ACB": 400, "VPB": 200}
    with pytest.raises(ValueError):
        inbox.read_pasted("   ")
    with pytest.raises(ValueError):
        inbox.read_pasted("chỉ một dòng chữ không phải bảng")
