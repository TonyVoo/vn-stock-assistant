"""Báo cáo 5 tín hiệu xếp hạng giữa các mã trên dữ liệu trong data/prices/.

Chạy: python scripts/run_signals.py [--split YYYY-MM-DD] [--min-sessions 1000]
Nếu không đặt --split, ngày cắt nằm ở 55% mẫu để cả hai nửa đều đủ kỳ.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import xsection as xs  # noqa: E402
from src.data import VN30_DEFAULT, get_prices  # noqa: E402


def main():
    args = sys.argv[1:]
    get = lambda k, d: args[args.index(k) + 1] if k in args else d
    min_sessions = int(get("--min-sessions", 1000))
    prices = {}
    for s in VN30_DEFAULT:
        df, src = get_prices(s, 0)
        if src == "csv" and len(df) >= min_sessions:
            prices[s] = df
    print(f"Số mã dùng: {len(prices)}/{len(VN30_DEFAULT)} (>= {min_sessions} phiên). "
          f"Mẫu: {min(d['date'].min() for d in prices.values()):%Y-%m-%d} → "
          f"{max(d['date'].max() for d in prices.values()):%Y-%m-%d}")
    panel = xs.build_panel(prices)
    dates = panel["close"].index
    split = get("--split", f"{dates[int(len(dates) * 0.55)]:%Y-%m-%d}")
    print(f"Ngày cắt train/test: {split}\n")
    res = xs.evaluate_all(prices, split)
    show = res.copy()
    for c in ("ann_net_excess", "gross_excess_per_period", "net_excess_per_period", "hit_rate", "avg_cost"):
        show[c] = (show[c] * 100).round(2)
    show[["t_net", "placebo_p"]] = show[["t_net", "placebo_p"]].round(2)
    print(show[["signal", "part", "periods", "ann_net_excess", "gross_excess_per_period",
                "net_excess_per_period", "t_net", "hit_rate", "avg_cost", "placebo_p"]].to_string(index=False))
    print("\n(đơn vị %; ann = excess ròng quy năm so với tỷ trọng đều; p = xác suất chọn ngẫu nhiên >= thực tế, trước phí)")


if __name__ == "__main__":
    main()
