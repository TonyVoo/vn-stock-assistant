"""Trang Báo cáo tháng: chọn tháng rồi tải về Excel hoặc PDF."""
from __future__ import annotations

from datetime import date

import streamlit as st

from src import explain, report, ui
from views import shared


def _last_price(sym: str):
    try:
        df, _ = shared.load(sym)
        return float(df["close"].iloc[-1]) if df is not None and len(df) else None
    except Exception:  # noqa: BLE001
        return None


def _months(n: int = 24):
    t, out = date.today(), []
    y, m = t.year, t.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def render(ctx) -> None:
    ui.page_header("Báo cáo tháng", "Tổng hợp tài sản, lệnh đã bán, tiền nạp/rút và cổ tức của một tháng để lưu hoặc in.")
    ym = st.selectbox("Chọn tháng", _months(), format_func=lambda t: f"Tháng {t[1]:02d}/{t[0]}", key="rp_month")
    d = report.collect(ym[0], ym[1], _last_price)
    s = d["summary"]
    a, b, c, e = st.columns(4)
    with a:
        ui.stat_card("Tổng tài sản hiện tại", explain.money_short(s["total"]), "theo giá đóng cửa gần nhất")
    with b:
        ui.stat_card("Lãi/lỗ lệnh đã bán trong tháng", explain.money_short(d["realized"]), f"{len(d['closed'])} lệnh, đã trừ phí và thuế",
                     "up" if d["realized"] > 0 else "down" if d["realized"] < 0 else "")
    with c:
        ui.stat_card("Lệnh mở trong tháng", str(len(d["opened"])), "")
    with e:
        ui.stat_card("Cổ tức tiền mặt nhận", explain.money_short(d["div_cash"]), "")
    if len(d["closed"]):
        ui.section("Lệnh đã bán trong tháng")
        cl = d["closed"]
        st.dataframe({"Mã": cl["symbol"], "Ngày bán": cl["closed"], "Giá mua": cl["entry"].map(explain.vnd),
                      "Giá bán": cl["exit_price"].map(explain.vnd), "Lãi/lỗ sau phí": cl["pnl"].map(explain.vnd)},
                     hide_index=True, width="stretch")
    else:
        ui.callout("Tháng này chưa có lệnh nào đã bán trong Nhật ký.", "info")
    for t in d["insights"]:
        st.caption(t)
    ui.section("Tải báo cáo")
    x, y = st.columns(2)
    x.download_button(":material/table_view: Tải Excel", lambda: report.to_excel(d), f"bao-cao-{ym[0]}-{ym[1]:02d}.xlsx",
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch", key="rp_xlsx")
    if report.pdf_available():
        y.download_button(":material/picture_as_pdf: Tải PDF", lambda: report.to_pdf(d), f"bao-cao-{ym[0]}-{ym[1]:02d}.pdf",
                          "application/pdf", width="stretch", key="rp_pdf", type="primary")
    else:
        y.button(":material/picture_as_pdf: Tải PDF", disabled=True, width="stretch",
                 help="Cần cài fpdf2 và có phông chữ hỗ trợ tiếng Việt (Arial). Hãy dùng Excel.")
    st.caption("Báo cáo chỉ để tham khảo cá nhân, không phải lời khuyên đầu tư. Dữ liệu lấy từ Danh mục, Nhật ký, Tiền nạp/rút và Cổ tức trên máy bạn.")
