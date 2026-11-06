"""Ứng dụng nhỏ chỉ để kiểm thử trang Mua dần."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import portfolio

portfolio.PATH = Path(os.environ["TEST_PF"])

from views import dca_view
from views.shared import Ctx

dca_view.render(Ctx(capital=10_000_000.0, watchlist=["FPT", "VNM"]))
