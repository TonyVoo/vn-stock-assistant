"""Ứng dụng nhỏ chỉ để kiểm thử chatbot nổi (AI chế độ mẫu, dữ liệu tạm)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src import cashflow, chat_store, dividends, journal, portfolio

journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])
cashflow.DB_PATH = Path(os.environ["TEST_CF"])
dividends.DB_PATH = Path(os.environ["TEST_DIV"])
portfolio.PATH = Path(os.environ["TEST_PF"])
chat_store.PATH = Path(os.environ["TEST_PF"]).parent / "chat_history.json"   # không đụng lịch sử chat thật

from views import chatbot
from views.shared import Ctx

st.session_state.setdefault("risk_pct", 2.0)
st.session_state.setdefault("max_alloc", 30)
st.session_state.setdefault("capital_m", 10.0)
chatbot.render(Ctx(capital=10_000_000.0, watchlist=["FPT"]))
