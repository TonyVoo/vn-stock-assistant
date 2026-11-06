"""Mục “Tin tức về các mã bạn đang giữ”: tin nhắc đích danh từng mã (có nguồn, liên kết) và tóm tắt bằng AI nếu đã bật."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from src import explain, journal, llm, news as newsmod, portfolio, ui
from views import shared

KIND = {"tich_cuc": ("Tin tốt", "up"), "tieu_cuc": ("Tin xấu", "down"), "trung_tinh": ("Trung lập", "muted"), "khong_ro": ("Chưa đủ để kết luận", "muted")}


def held_symbols() -> list:
    syms = [h["symbol"] for h in portfolio.load()["holdings"]]
    t = journal.list_trades()
    if not t.empty:
        syms += list(t[t["exit_price"].isna()]["symbol"])
    return list(dict.fromkeys(str(s).upper() for s in syms))


def _summarize() -> None:
    st.session_state["hn_error"] = None
    try:
        by = st.session_state["hn_by"]
        st.session_state["hn_ai"] = (llm.summarize_holdings_news(by), dt.datetime.now(explain.VN_TZ))
    except Exception as e:  # noqa: BLE001
        st.session_state["hn_error"] = f"Không tóm tắt được ({type(e).__name__}). Thử lại sau ít phút."


def render() -> None:
    syms = held_symbols()
    if not syms:
        return
    ui.section("Tin tức về các mã bạn đang giữ", "Chỉ lấy tin nhắc đích danh mã trong tiêu đề hoặc mô tả, từ CafeF, VnExpress, Vietstock")
    try:
        items = shared.news_items()
    except Exception:  # noqa: BLE001
        items = []
    if not items:
        ui.callout("Chưa tải được tin tức (có thể do mạng). Thử lại sau ít phút.", "warn")
        return
    by = {s: newsmod.match_symbol(items, s) for s in syms}
    st.session_state["hn_by"] = by
    if not any(by.values()):
        ui.callout("Hiện chưa có tin nào nhắc đích danh " + ", ".join(syms) + " trong các nguồn đang theo dõi. Không có tin không có nghĩa là không có gì xảy ra.", "info")
        return
    ai = st.session_state.get("hn_ai")
    if shared.ai_ready():
        st.button(":material/auto_awesome: Tóm tắt bằng AI", key="hn_btn", on_click=_summarize,
                  help="Chỉ gửi mã và tiêu đề/mô tả tin công khai cho AI. Không gửi số lượng, giá vốn hay vốn của bạn.")
        if st.session_state.get("hn_error"):
            ui.callout(st.session_state["hn_error"], "bad")
    else:
        st.caption("Muốn có tóm tắt tự động, bật AI (xem trang Hướng dẫn, mục “Bật AI”). Không bật thì vẫn đọc được các tin bên dưới.")
    for s in syms:
        its = by[s]
        with st.container(border=True):
            head = f"**{s}**"
            summ = ai[0].get(s) if ai else None
            if summ:
                label, kind = KIND[summ["tac_dong"]]
                head += "  " + ui.badge(label, kind)
            st.markdown(head, unsafe_allow_html=True)
            if not its:
                st.caption("Không có tin nhắc đích danh mã này.")
                continue
            if summ and summ["tom_tat"]:
                st.write(summ["tom_tat"])
            main = set(summ["tin_chinh"]) if summ else set()
            for i, n in enumerate(its):
                mark = "  (tin AI cho là quan trọng)" if i in main else ""
                st.markdown(f"- [{n['title']}]({n['link']}) · {n['source']}{mark}" if n.get("link") and str(n["link"]).startswith("http")
                            else f"- {n['title']} · {n['source']}{mark}")
    if ai:
        st.caption(f"Tóm tắt tạo lúc {ai[1]:%H:%M %d/%m}. AI chỉ đọc tiêu đề và mô tả ngắn, có thể sai hoặc thiếu; hãy mở bài gốc trước khi quyết định. Không phải lời khuyên đầu tư.")
