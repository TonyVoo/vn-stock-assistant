"""Trang Cài đặt: vốn, danh sách theo dõi, mức an toàn. Bấm Lưu để ghi ra file (không mất khi tải lại trang)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from src import data as datamod
from src import explain, settings, ui
from views import data_update, shared


def _available_symbols():
    have = {p.stem.upper() for p in datamod.CSV_DIR.glob("*.csv")} - {"VNINDEX"}
    return sorted(have | set(datamod.VN30_DEFAULT))


def render(ctx) -> None:
    ui.page_header("Cài đặt", "Chỉnh xong bấm “Lưu cài đặt”. Cài đặt được lưu trên máy bạn và vẫn còn khi tải lại trang.")
    s = st.session_state
    with st.form("settings_form"):
        st.markdown("**Vốn của bạn**")
        capital = st.number_input("Số tiền bạn dự định dùng để đầu tư (triệu đồng)", 0.1, 1_000_000.0,
                                  float(s["capital_m"]), step=1.0,
                                  help="App dùng số này để tính nên mua bao nhiêu cổ phiếu. Ví dụ 10 = 10 triệu đồng.")
        st.markdown("**Danh sách mã theo dõi**")
        opts = _available_symbols()
        watch = st.multiselect("Các mã hiện ở trang Tổng quan", opts, default=[w for w in s["watch"] if w in opts],
                               help="Mã ngoài danh sách này cần tải dữ liệu trước (xem trang Hướng dẫn).")
        st.markdown("**Mức an toàn mặc định cho trang “Tính lệnh mua”**")
        a, b = st.columns(2)
        risk_pct = a.slider("Chấp nhận mất tối đa bao nhiêu % vốn nếu một lệnh sai?", 0.5, 5.0, float(s["risk_pct"]), 0.5,
                            format="%.1f%%", help="Người mới nên để 1–2%.")
        max_alloc = b.slider("Tối đa bao nhiêu % vốn dồn vào một mã?", 10, 50, int(s["max_alloc"]), 5, format="%d%%",
                             help="Không nên bỏ hết trứng vào một giỏ.")
        if st.form_submit_button(":material/save: Lưu cài đặt", type="primary"):
            if not watch:
                st.error("Cần chọn ít nhất một mã để theo dõi.")
            else:
                saved = settings.save({"capital_m": capital, "watch": watch, "risk_pct": risk_pct, "max_alloc": max_alloc})
                s.update(saved)
                st.toast("Đã lưu cài đặt", icon=":material/check_circle:")
                st.success(f"Đã lưu: vốn {explain.money_short(saved['capital_m'] * 1e6)}, theo dõi {len(saved['watch'])} mã.")
    if st.button("Khôi phục mặc định"):
        s.update(settings.save(dict(settings.DEFAULTS)))
        st.rerun()

    ui.section("Dữ liệu giá")
    data_update.render_panel(ctx)

    ui.section("Thông tin hệ thống")
    c1, c2 = st.columns(2)
    with c1:
        ui.stat_card("AI", shared.ai_name(), "Đã bật" if shared.ai_ready() else "Chưa bật (tuỳ chọn). Xem trang Hướng dẫn.")
    with c2:
        df, src = shared.load("VNINDEX")
        nguon = {"csv": "File CSV trên máy", "demo": "Giả lập (chưa có dữ liệu thật)"}.get(src, src)
        ui.stat_card("Dữ liệu giá", nguon, f"Đến hết phiên {df['date'].iloc[-1]:%d/%m/%Y}" if len(df) else "")
    st.caption(f"Cài đặt được lưu tại: {Path(settings.PATH)}")
