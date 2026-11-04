"""Tải giá lịch sử bằng vnstock (Python >= 3.10) và lưu vào data/prices/<MÃ>.csv.

Chạy:  python scripts/download_prices.py                    # VN30 + VNINDEX, 4 năm
       python scripts/download_prices.py FPT HPG            # chỉ các mã chỉ định
       python scripts/download_prices.py --years 10         # 10 năm (nếu gói của bạn cho phép)

Không ghi đè file cũ nếu dữ liệu mới có ÍT dòng hơn file đang có.
"""
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.data import VN30_DEFAULT  # noqa: E402

OUT = ROOT / "data" / "prices"
YEARS = 4  # có thể đổi bằng --years N
PAUSE = 3.5  # giây giữa các lần gọi, tránh bị giới hạn tốc độ (gói miễn phí ~20 lần/phút)


def main(symbols, years=YEARS):
    try:
        from src.data import fetch_vnstock
    except ImportError:
        sys.exit("Chưa cài vnstock >= 5 hoặc Python < 3.10. Xem hướng dẫn trong README.")

    OUT.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years)
    ok, failed = [], []
    for i, sym in enumerate(symbols, 1):
        try:
            df = fetch_vnstock(sym, f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}")
            if len(df) < 100:
                raise ValueError(f"chỉ có {len(df)} dòng")
            f = OUT / f"{sym}.csv"
            old = len(pd.read_csv(f)) if f.exists() else 0
            if len(df) < old:
                raise ValueError(f"dữ liệu mới ({len(df)} dòng) ít hơn file hiện có ({old}); giữ nguyên file cũ")
            df.to_csv(f, index=False)
            ok.append(sym)
            print(f"[{i}/{len(symbols)}] {sym}: {len(df)} phiên ({df['date'].min():%Y-%m-%d} → {df['date'].max():%Y-%m-%d})")
        except Exception as e:  # noqa: BLE001
            failed.append(sym)
            print(f"[{i}/{len(symbols)}] {sym}: LỖI {type(e).__name__}: {str(e)[:120]}")
        time.sleep(PAUSE)
    print(f"\nXong: {len(ok)} mã thành công, {len(failed)} lỗi {failed if failed else ''}")
    if ok:
        n = min(pd.read_csv(OUT / f"{s}.csv").shape[0] for s in ok)
        if n < 400:
            print(f"⚠️ Mã ít dữ liệu nhất chỉ có {n} phiên. Backtest cần > 400 phiên. "
                  "Tài khoản Khách chỉ có 365 ngày: chạy `vnstock register` (miễn phí) để có hạn mức cộng đồng.")


if __name__ == "__main__":
    args = sys.argv[1:]
    years = YEARS
    if "--years" in args:
        k = args.index("--years")
        years = int(args[k + 1])
        args = args[:k] + args[k + 2:]
    main([s.upper() for s in args] or ["VNINDEX"] + VN30_DEFAULT, years)
