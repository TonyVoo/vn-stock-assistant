"""Ứng dụng nhỏ chỉ để kiểm thử phần Tiền nạp/rút (chạy bằng streamlit.testing)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import cashflow, journal, portfolio

cashflow.DB_PATH = Path(os.environ["TEST_CF"])            # không đọc/ghi dữ liệu thật của người dùng
journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])
portfolio.PATH = Path(os.environ["TEST_PF"])

from views import portfolio_view

portfolio_view._cashflow_section(12_000_000.0, 2_000_000.0, True, 10_000_000.0)
