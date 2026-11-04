"""Ứng dụng nhỏ chỉ để kiểm thử bảng rủi ro (chạy bằng streamlit.testing)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import journal, portfolio

journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])      # không đọc/ghi dữ liệu thật của người dùng
portfolio.PATH = Path(os.environ["TEST_PF"])

from views import portfolio_view

pf = portfolio.load()
df, s = portfolio.valuate(pf, {"AAA": 30_000.0, "BBB": 20_000.0}.get, 0.30)
portfolio_view._risk_section(df, s, pf)
