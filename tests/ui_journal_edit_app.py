"""Ứng dụng nhỏ chỉ để kiểm thử trang Nhật ký (chạy bằng streamlit.testing)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import journal

journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])      # không đọc/ghi dữ liệu thật của người dùng

from views import journal_view, shared

journal_view.render(shared.Ctx(capital=10_000_000.0, watchlist=["FPT"]))
