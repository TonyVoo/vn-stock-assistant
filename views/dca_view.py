"""Trang Kế hoạch mua dần (DCA): chia tiền mỗi tháng để mua dần thay vì dồn một lần."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import dca, explain, portfolio, ui
from views import shared


def _last_price(sym: str):
    try:
        df, _ = shared.load(sym)
        return float(df["close"].iloc[-1]) if df is not None and len(df) else None
    except Exception:  # noqa: BLE001
        return None


def render(ctx) -> None:
    ui.page_header("Kế hoạch mua dần", "Mỗi tháng bỏ một số tiền cố định để mua, thay vì dồn hết vào một lần.")
    ui.callout("Mua dần giúp giá vốn trung bình mượt hơn và đỡ lo chọn sai thời điểm, nhưng KHÔNG đảm bảo có lãi. "
               "Bảng dưới giả định giá giữ nguyên như hôm nay, vì không ai biết giá tương lai.", "info")
    held = [h["symbol"] for h in portfolio.load()["holdings"]]
    options = list(dict.fromkeys(list(ctx.watchlist) + held))
    c1, c2 = st.columns(2)
    budget = c1.number_input("Số tiền bỏ ra mỗi tháng (đồng)", min_value=100_000.0, value=2_000_000.0, step=100_000.0, format="%.0f", key="dca_budget",
                            help="Số tiền bạn có thể bỏ ra đều đặn mỗi tháng.")
    c1.caption(f"= {explain.vnd(budget)} mỗi tháng")
    months = c2.number_input("Số tháng", min_value=1, max_value=dca.MAX_MONTHS, value=12, step=1, key="dca_months")
    syms = st.multiselect("Mã muốn mua dần", options, default=options[:2], key="dca_syms", accept_new_options=True,
                          help="Chọn 1 đến 3 mã. Càng nhiều mã thì mỗi mã nhận càng ít tiền mỗi tháng.")
    mode = st.radio("Cách chia", list(dca.MODE_LABEL), format_func=dca.MODE_LABEL.get, key="dca_mode",
                    help="Chia cho tất cả: mỗi tháng mua mọi mã một ít. Luân phiên: dồn cả tháng vào một mã, tháng sau mã khác; "
                         "hợp khi số tiền nhỏ, vì giá một lô (100 cổ phiếu) thường lớn hơn phần tiền chia cho từng mã.")
    syms = [s.upper().strip() for s in syms]
    if not syms:
        ui.callout("Hãy chọn ít nhất một mã.", "warn")
        return
    prices, missing = {}, []
    for s in syms:
        p = _last_price(s)
        (prices.__setitem__(s, p) if p else missing.append(s))
    if missing:
        ui.callout(f"Chưa có dữ liệu giá của {', '.join(missing)}. Hãy bấm Cập nhật giá ở trang Tổng quan rồi quay lại.", "warn")
    if not prices:
        return
    weights = {}
    if mode == dca.SPLIT and len(prices) > 1:
        with st.expander(":material/tune: Chia tỷ lệ khác nhau cho từng mã (tuỳ chọn)"):
            for s in prices:
                weights[s] = st.number_input(f"Tỷ trọng {s} (%)", 0, 100, int(100 / len(prices)), key=f"dca_w_{s}")
            if sum(weights.values()) <= 0:
                st.error("Tổng tỷ trọng phải lớn hơn 0.")
                return
    try:
        res = dca.plan(float(budget), int(months), prices, weights or None, mode)
    except ValueError as e:
        st.error(str(e))
        return
    ui.section("Kết quả kế hoạch", "Giá lấy theo phiên đóng cửa gần nhất trong dữ liệu của bạn")
    a, b, c = st.columns(3)
    with a:
        ui.stat_card("Tổng tiền dự định bỏ ra", explain.money_short(res["total_budget"]), f"{explain.vnd(budget)} × {int(months)} tháng")
    with b:
        ui.stat_card("Tiền thực sự mua cổ phiếu (gồm phí)", explain.money_short(res["invested"]), "đã tính phí mua, mua theo lô 100")
    with c:
        ui.stat_card("Tiền còn dư chưa mua được", explain.money_short(res["leftover"]), "chưa đủ một lô, dồn sang tháng sau")
    for n in res["notes"]:
        ui.callout(n, "warn")
    by = res["by_symbol"]
    st.dataframe(pd.DataFrame({"Mã": by["symbol"], "Giá hiện tại": by["symbol"].map(lambda s: explain.vnd(prices[s])),
                               "Tổng số cổ phiếu": by["qty"].map(explain.num), "Tổng tiền đã chi": by["spent"].map(explain.vnd),
                               "Giá vốn bình quân": by["avg_cost"].map(lambda x: explain.vnd(x) if x == x else "Chưa mua được")}),
                 hide_index=True, width="stretch")
    with st.expander(":material/table_rows: Lịch mua từng tháng"):
        s = res["schedule"]
        st.dataframe(pd.DataFrame({"Tháng thứ": s["month"], "Mã": s["symbol"], "Số cổ phiếu mua": s["qty"].map(explain.num),
                                   "Tiền chi (gồm phí)": s["spent"].map(explain.vnd), "Tiền dư dồn sang sau": s["carry"].map(explain.vnd)}),
                     hide_index=True, width="stretch")
    st.caption("Phí mua được tính 0,15%. Đây chỉ là bản kế hoạch để bạn tự thực hiện, app không đặt lệnh thay bạn.")
