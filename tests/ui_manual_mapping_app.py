"""Ứng dụng nhỏ chỉ để kiểm thử giao diện chọn cột (chạy bằng streamlit.testing)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src import journal, portfolio

journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])      # không đọc/ghi dữ liệu thật của người dùng
portfolio.PATH = Path(os.environ["TEST_PF"])

from views import portfolio_view

raw = pd.DataFrame({"A": ["VCB", "ACB"], "B": ["100", "200"], "C": ["90", "25"]})  # tên cột hoàn toàn không đoán được
portfolio_view._manual_columns(raw, "S", {"cash": 0.0}, True)
