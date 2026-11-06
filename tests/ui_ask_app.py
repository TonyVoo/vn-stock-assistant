"""Ứng dụng nhỏ chỉ để kiểm thử trang Hỏi trợ lý (AI chế độ mẫu)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src import portfolio

portfolio.PATH = Path(os.environ["TEST_PF"])

from views import ask_view
from views.shared import Ctx

st.session_state.setdefault("risk_pct", 2.0)
st.session_state.setdefault("max_alloc", 30)
ask_view.render(Ctx(capital=10_000_000.0, watchlist=["FPT", "VNM"]))
