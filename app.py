"""Trợ lý chứng khoán — chạy: streamlit run app.py"""
from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src import ui  # noqa: E402
from views import calc, guide, journal_view, overview, portfolio_view, research, settings_view, shared, stock  # noqa: E402

st.set_page_config(page_title="Trợ lý chứng khoán", page_icon=":material/show_chart:", layout="wide", initial_sidebar_state="collapsed")
ui.inject_css()
shared.init_state()

ROUTES = [  # (khoá, hàm vẽ, tiêu đề, biểu tượng, đường dẫn)
    ("overview", overview.render, "Tổng quan", ":material/dashboard:", "tong-quan"),
    ("stock", stock.render, "Tra cứu cổ phiếu", ":material/search:", "tra-cuu"),
    ("calc", calc.render, "Tính lệnh mua", ":material/calculate:", "tinh-lenh"),
    ("portfolio", portfolio_view.render, "Danh mục", ":material/account_balance_wallet:", "danh-muc"),
    ("journal", journal_view.render, "Nhật ký giao dịch", ":material/menu_book:", "nhat-ky"),
    ("research", research.render, "Nghiên cứu (nâng cao)", ":material/science:", "nghien-cuu"),
    ("guide", guide.render, "Hướng dẫn", ":material/help:", "huong-dan"),
    ("settings", settings_view.render, "Cài đặt", ":material/settings:", "cai-dat"),
]
pages = []
for key, fn, title, icon, path in ROUTES:
    pg = st.Page(shared.page(fn), title=title, icon=icon, url_path=path, default=(key == "overview"))
    shared.PAGES[key] = pg
    pages.append(pg)

nav = st.navigation(pages, position="top")
ui.ticker_strip(shared.strip_items())
nav.run()
