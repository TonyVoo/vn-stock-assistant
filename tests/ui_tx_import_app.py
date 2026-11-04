"""Ứng dụng nhỏ chỉ để kiểm thử nút “Thêm vào Nhật ký” (chạy bằng streamlit.testing)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src import journal, portfolio

journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])      # không đụng vào dữ liệu thật của người dùng
portfolio.PATH = Path(os.environ["TEST_PF"])

from views import portfolio_view

df = pd.DataFrame({
    "Ngày giao dịch": ["02/01/2026", "03/01/2026", "05/01/2026", "06/01/2026"],
    "Mã CK": ["FPT", "FPT", "FPT", "VCB"], "Loại lệnh": ["Mua", "Mua", "Bán", "Mua"],
    "Khối lượng khớp": [100, 100, 150, 10], "Giá khớp": [100_000, 110_000, 120_000, 90_000]})
rows, _, _ = portfolio.parse_file(df)
tx, _ = portfolio.transactions_from_file(df)
portfolio_view._tx_actions(tx, rows, portfolio.load(), "t")
