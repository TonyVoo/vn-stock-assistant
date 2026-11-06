"""Ứng dụng nhỏ chỉ để kiểm thử trang Tính lệnh mua."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src import portfolio

portfolio.PATH = Path(os.environ["TEST_PF"])

from views import calc
from views.shared import Ctx

st.session_state.setdefault("risk_pct", 2.0)
st.session_state.setdefault("max_alloc", 30)
calc.render(Ctx(capital=10_000_000.0, watchlist=["FPT"]))
