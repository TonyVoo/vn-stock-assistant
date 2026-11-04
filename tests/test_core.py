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
