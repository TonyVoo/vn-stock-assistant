"""Trợ lý chứng khoán — chạy: streamlit run app.py"""
from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src import access, backup, ui  # noqa: E402
from views import alert_banner, chatbot, ask_view, glossary_ui, calc, data_update, dca_view, guide, journal_view, overview, portfolio_view, report_view, research, settings_view, shared, stock  # noqa: E402

st.set_page_config(page_title="Trợ lý chứng khoán", page_icon=":material/show_chart:", layout="wide", initial_sidebar_state="collapsed")
ui.inject_css()
shared.init_state()
backup.auto_backup()  # tối đa một bản tự động mỗi ngày, rất nhanh; lỗi thì bỏ qua

_guard = access.guard()
if _guard is not None and not st.session_state.get("authed"):  # có đặt APP_PIN: phải nhập mã mới thấy dữ liệu
    st.title("Trợ lý chứng khoán")
    wait = _guard.remaining_lock()
    if wait > 0:
        st.error(f"Nhập sai nhiều lần. Thử lại sau {int(wait) + 1} giây.")
        st.stop()
    with st.form("pin_form"):
        entered = st.text_input("Nhập mã PIN", type="password")
        if st.form_submit_button("Vào", type="primary"):
            if _guard.check(entered):
                st.session_state["authed"] = True
                st.rerun()
            st.error("Mã PIN chưa đúng.")
    st.stop()

data_update.inbox_tick()  # sau cổng PIN: nếu có sao kê mới trong data/inbox thì tự đọc (tối đa 10 giây một lần)

ROUTES = [  # (khoá, hàm vẽ, tiêu đề, biểu tượng, đường dẫn)
    ("overview", overview.render, "Tổng quan", ":material/dashboard:", "tong-quan"),
    ("stock", stock.render, "Tra cứu cổ phiếu", ":material/search:", "tra-cuu"),
    ("ask", ask_view.render, "Hỏi trợ lý", ":material/forum:", "hoi-dap"),
    ("calc", calc.render, "Tính lệnh mua", ":material/calculate:", "tinh-lenh"),
    ("dca", dca_view.render, "Mua dần", ":material/event_repeat:", "mua-dan"),
    ("portfolio", portfolio_view.render, "Danh mục", ":material/account_balance_wallet:", "danh-muc"),
    ("journal", journal_view.render, "Nhật ký giao dịch", ":material/menu_book:", "nhat-ky"),
    ("report", report_view.render, "Báo cáo tháng", ":material/summarize:", "bao-cao"),
    ("research", research.render, "Nghiên cứu (nâng cao)", ":material/science:", "nghien-cuu"),
    ("guide", guide.render, "Hướng dẫn", ":material/help:", "huong-dan"),
    ("settings", settings_view.render, "Cài đặt", ":material/settings:", "cai-dat"),
]
ADVANCED = {"dca", "report", "research"}  # ẩn ở chế độ đơn giản
GROUPS = {"overview": "Tổng quan", "stock": "Thị trường", "ask": "Thị trường", "calc": "Thị trường", "dca": "Thị trường",
          "portfolio": "Tài khoản của tôi", "journal": "Tài khoản của tôi", "report": "Tài khoản của tôi",
          "research": "Khác", "guide": "Khác", "settings": "Khác"}  # gom nhóm để thanh điều hướng không bị chật
grouped: dict = {}
for key, fn, title, icon, path in ROUTES:
    if key in ADVANCED and st.session_state.get("simple_mode", False):
        continue
    pg = st.Page(shared.page(fn, key), title=title, icon=icon, url_path=path, default=(key == "overview"))
    shared.PAGES[key] = pg
    grouped.setdefault(GROUPS[key], []).append(pg)

nav = st.navigation(grouped, position="top")
ui.ticker_strip(shared.strip_items())
data_update.auto_refresh(shared.get_ctx())
_, gl = st.columns([8, 1])
with gl:
    glossary_ui.popover()
alert_banner.render()
nav.run()
chatbot.render(shared.get_ctx())  # sau khi trang đã vẽ, để chatbot biết bạn đang xem trang/mã nào (nút nổi cố định nên thứ tự không ảnh hưởng vị trí)
