"""Ứng dụng nhỏ chỉ để kiểm thử hai nút của file danh mục đang giữ (chạy bằng streamlit.testing)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src import journal, portfolio

journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])      # không đụng vào dữ liệu thật của người dùng
portfolio.PATH = Path(os.environ["TEST_PF"])

from views import portfolio_view

df = pd.DataFrame({"Mã CK": ["FPT", "HPG", "Tổng cộng"], "Khối lượng": ["100", "200", "300"], "Giá vốn (đ)": ["98.500", "24.000", ""]})
rows, notes, _ = portfolio.parse_file(df)
st_notes = notes
portfolio_view._holdings_actions(rows, portfolio.load(), "t")
