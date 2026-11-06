"""Ứng dụng nhỏ chỉ để kiểm thử phần Cổ tức (chạy bằng streamlit.testing)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import dividends, portfolio

dividends.DB_PATH = Path(os.environ["TEST_DIV"])          # không đọc/ghi dữ liệu thật của người dùng
portfolio.PATH = Path(os.environ["TEST_PF"])

from views import portfolio_view

portfolio_view._dividend_section(portfolio.load())
