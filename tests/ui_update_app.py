"""Ứng dụng nhỏ chỉ để kiểm thử nút Cập nhật giá (chạy bằng streamlit.testing, nguồn dữ liệu giả)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src import data, journal, portfolio, updater

tmp = Path(os.environ["TEST_PRICES"])
updater.CSV_DIR = tmp                                    # không đọc/ghi dữ liệu thật của người dùng
data.CSV_DIR = tmp
updater.PAUSE = 0
journal.DB_PATH = Path(os.environ["TEST_JOURNAL"])
portfolio.PATH = Path(os.environ["TEST_PF"])


def fake(symbol, start, end):
    if symbol == os.environ.get("TEST_FAIL"):
        raise RuntimeError("rate limit")
    idx = pd.bdate_range(end="2026-11-04", periods=60)
    close = 20_000.0 + np.arange(60) * 10
    df = pd.DataFrame({"date": idx, "open": close, "high": close, "low": close, "close": close, "volume": 1_000_000})
    return df[(df["date"] >= start) & (df["date"] <= end)]


updater.default_fetch = fake

from views import data_update, shared

data_update.render_compact(shared.Ctx(capital=1e7, watchlist=["FPT", "HPG"]))
