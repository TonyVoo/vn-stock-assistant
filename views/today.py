"""Khối “Hôm nay bạn cần làm gì” ở Tổng quan: tối đa 3 việc, có nút đi tới đúng trang."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from src import explain, journal, portfolio, todo, ui, updater
from views import alert_banner, health_view, shared

LEVEL = {"bad": ("Cần làm ngay", "down"), "warn": ("Nên làm", "flat"), "info": ("Khi rảnh", "muted")}


def _last_price(sym: str):
    return alert_banner._last_price(sym)


def gather(ctx) -> list:
    now = dt.datetime.now(explain.VN_TZ)
    t = journal.list_trades()
    open_t = t[t["exit_price"].isna()] if not t.empty else None
    pf = portfolio.load()
    summary, weights = None, None
    if pf["holdings"]:
        df, summary = portfolio.valuate(pf, _last_price, st.session_state.get("max_alloc", 30) / 100,
                                           float(st.session_state.get("capital_m", 0.0)) * 1_000_000)
        weights = dict(zip(df["symbol"], df["weight"]))
    from src import cashflow
    last = updater.last_data_date(["VNINDEX"])
    return todo.build(alert_banner.current(), open_t, last.date() if last is not None else None, now.date(), summary, weights,
                      st.session_state.get("max_alloc", 30) / 100, bool(pf["holdings"]), len(cashflow.list_flows()) > 0,
                      market_closed_now=now.time() > dt.time(15, 5))


def render(ctx) -> None:
    ui.section("Hôm nay bạn cần làm gì?", "Tối đa 3 việc, việc quan trọng nhất ở trên cùng")
    items = gather(ctx)
    if not items:
        ui.callout("Hôm nay bạn không cần làm gì. Không mua, không bán cũng là một lựa chọn tốt.", "good")
        health_view.render()
        return
    for i, it in enumerate(items):
        label, kind = LEVEL[it["level"]]
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        with c1:
            st.markdown(f'<div class="card">{ui.badge(label, kind)} <b>{ui.esc(it["title"])}</b>'
                        f'<div class="hint" style="margin-top:6px">{ui.esc(it["detail"])}</div></div>', unsafe_allow_html=True)
        with c2:
            if st.button("Đi tới", key=f"todo_go_{i}", width="stretch"):
                shared.open_page(it["page"])
    health_view.render()
