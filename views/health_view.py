"""Mục “Sức khoẻ dữ liệu” ở Tổng quan: chỗ dữ liệu cũ, thiếu hoặc không khớp. Cũng cấp dữ liệu này cho chatbot."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from src import backup, cashflow, explain, health, journal, portfolio, ui
from views import shared

LEVEL = {"warn": ("Nên sửa", "flat"), "info": ("Lưu ý", "muted")}


def _price_dates(symbols) -> dict:
    out = {}
    for s in symbols:
        try:
            df, src = shared.load(s)
            out[s] = None if src == "demo" or df is None or not len(df) else df["date"].iloc[-1].date()
        except Exception:  # noqa: BLE001
            out[s] = None
    return out


def gather() -> list:
    pf = portfolio.load()
    t = journal.list_trades()
    open_t = t[t["exit_price"].isna()] if not t.empty else None
    held = [h["symbol"] for h in pf["holdings"]]
    capital = float(st.session_state.get("capital_m", 0.0)) * 1_000_000
    total = sum(h["avg_cost"] * h["qty"] for h in pf["holdings"]) + pf["cash"]
    try:
        _, s = portfolio.valuate(pf, lambda sym: None)
        total = s["total"]
    except Exception:  # noqa: BLE001
        pass
    last = backup.latest_auto()
    age = (dt.datetime.now().timestamp() - last.stat().st_mtime) / 86400 if last else None
    now = dt.datetime.now(explain.VN_TZ)
    return health.check(now.date(), pf["holdings"], pf["cash"], pf.get("as_of"), open_t, _price_dates(held), len(cashflow.list_flows()) > 0,
                        capital, total, age, has_data=bool(held) or not t.empty)


def render() -> None:
    items = gather()
    if not items:
        st.caption("Sức khoẻ dữ liệu: ổn, chưa thấy chỗ nào cũ hay lệch nhau.")
        return
    n_warn = sum(1 for i in items if i["level"] == "warn")
    with st.expander(f":material/health_and_safety: Sức khoẻ dữ liệu: {len(items)} điểm cần xem" + (f" ({n_warn} nên sửa)" if n_warn else ""), expanded=bool(n_warn)):
        for i, it in enumerate(items):
            label, kind = LEVEL[it["level"]]
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f'<div class="item">{ui.badge(label, kind)} <b>{ui.esc(it["title"])}</b><div class="d">{ui.esc(it["detail"])}</div></div>', unsafe_allow_html=True)
            if c2.button("Đi tới", key=f"hl_go_{i}", width="stretch"):
                shared.open_page(it["page"])
