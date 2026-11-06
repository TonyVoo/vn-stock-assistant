"""Từ điển bấm là hiểu: giải thích ngắn + ví dụ bằng số thật của bạn. Dùng ở mọi trang (nút trên cùng) và ở trang Hướng dẫn."""
from __future__ import annotations

import streamlit as st

from src import glossary


def _personal() -> dict:
    s = st.session_state
    return {"capital": float(s.get("capital_m", 10.0)) * 1_000_000, "risk_pct": float(s.get("risk_pct", 2.0)), "max_alloc": float(s.get("max_alloc", 30)),
            "entry": float(s.get("calc_entry", 25000)), "stop": float(s.get("calc_stop", 23500)), "target": float(s.get("calc_target", 29000))}


def _show(term: str) -> None:
    short, ex = glossary.explain(term, _personal())
    st.markdown(f"**{term}**: {short}")
    if ex:
        st.info(ex, icon=":material/lightbulb:")


def popover() -> None:
    with st.popover(":material/help: Từ điển", help="Không hiểu một từ? Chọn từ đó, có ví dụ bằng số của bạn."):
        term = st.selectbox("Bạn muốn hiểu từ nào?", list(glossary.TERMS), key="gl_pick")
        _show(term)


def full() -> None:
    st.caption("Các ví dụ dùng vốn, mức chấp nhận mất và giá ở trang Tính lệnh mua của bạn.")
    for term in glossary.TERMS:
        with st.expander(term):
            _show(term)
