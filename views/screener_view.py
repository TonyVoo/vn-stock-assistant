"""Bộ lọc cổ phiếu ở trang Tra cứu: chọn tiêu chí, thu hẹp danh sách cần xem."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import explain, screener, ui
from src.data import VN30_DEFAULT
from views import shared


@st.cache_data(ttl=900, show_spinner=False)
def _metrics(symbols: tuple, vers: tuple) -> pd.DataFrame:
    rows = []
    for s in symbols:
        df, src = shared.load_long(s)
        if src == "demo":
            continue  # dữ liệu giả lập không được lọt vào kết quả
        m = screener.metrics(s, df)
        if m:
            rows.append(m)
    return pd.DataFrame(rows, columns=screener.COLUMNS)


def render(ctx) -> None:
    with st.expander(":material/filter_alt: Lọc cổ phiếu theo tiêu chí (để thu hẹp danh sách cần xem)"):
        ui.callout("Bộ lọc chỉ giúp bạn xem ít mã hơn. Một mã qua được bộ lọc KHÔNG có nghĩa là nên mua: nghiên cứu của app chưa tìm thấy "
                   "lợi thế đáng tin từ các tiêu chí kỹ thuật như xu hướng.", "info")
        universe = tuple(sorted(set(ctx.watchlist) | set(VN30_DEFAULT)))
        m = _metrics(universe, tuple(shared._ver(s) for s in universe))
        if m.empty:
            st.caption("Chưa có dữ liệu giá để lọc. Hãy bấm Cập nhật giá ở trang Tổng quan.")
            return
        a, b = st.columns(2)
        min_val = a.slider("Giao dịch tối thiểu mỗi phiên (tỷ đồng)", 0, 200, 10, key="sc_val",
                           help="Mã giao dịch ít thì khó mua bán nhanh. Người mới nên chọn từ 10 tỷ trở lên.")
        trend = b.selectbox("Xu hướng", screener.TRENDS, key="sc_trend",
                            help="Giá nằm trên đường trung bình thường cho thấy xu hướng đang tốt, nhưng chưa chắc còn tiếp tục.")
        c, d, e = st.columns(3)
        use_vol = c.checkbox("Giới hạn biến động", key="sc_usevol")
        max_vol = c.slider("Biến động tối đa mỗi ngày (%)", 0.5, 6.0, 2.5, 0.1, key="sc_vol", disabled=not use_vol,
                           help="Mức lên xuống trung bình mỗi ngày trong 20 phiên gần nhất. Càng thấp càng ít giật.")
        use_rsi = d.checkbox("Loại mã đang quá nóng", key="sc_usersi")
        max_rsi = d.slider("RSI tối đa", 50, 90, 70, key="sc_rsi", disabled=not use_rsi,
                           help="RSI cao nghĩa là giá vừa tăng rất nhanh, dễ điều chỉnh. Thường coi trên 70 là nóng.")
        use_high = e.checkbox("Giới hạn cách đỉnh 1 năm", key="sc_usehigh")
        max_high = e.slider("Cách đỉnh 1 năm tối đa (%)", 5, 80, 30, key="sc_high", disabled=not use_high,
                            help="Giá hiện tại thấp hơn đỉnh 1 năm bao nhiêu phần trăm.")
        res = screener.screen(m, min_val * 1e9, trend, max_vol / 100 if use_vol else None, max_rsi if use_rsi else None,
                              max_high / 100 if use_high else None)
        st.markdown(f"**{len(res)}/{len(m)} mã** thoả các tiêu chí đã chọn.")
        if res.empty:
            st.caption("Không mã nào thoả. Thử nới bớt tiêu chí.")
            return
        st.dataframe(pd.DataFrame({
            "Mã": res["symbol"], "Giá": res["close"].map(explain.num), "Giao dịch mỗi phiên": (res["avg_value"] / 1e9).map(lambda x: f"{explain.num(x, 1)} tỷ"),
            "60 phiên": res["ret60"].map(lambda x: explain.pct(x, 1) if x == x else ""), "Cách đỉnh 1 năm": res["from_high"].map(lambda x: explain.pct(x, 0)),
            "Biến động/ngày": res["vol"].map(lambda x: explain.pct(x, 1, signed=False)), "RSI": res["rsi"].map(lambda x: f"{x:.0f}"),
            "Trên MA50": res["above50"].map(lambda x: "Có" if x else "Không")}), hide_index=True, width="stretch")
        pick = st.selectbox("Xem chi tiết một mã", list(res["symbol"]), key="sc_pick")
        if st.button("Xem mã này", key="sc_go"):
            st.session_state["symbol"] = pick
            st.rerun()
