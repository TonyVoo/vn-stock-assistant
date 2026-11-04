"""Cập nhật giá bằng một nút: lấy phần mới từ vnstock và gộp vào file CSV trong data/prices/.

An toàn cho dữ liệu của bạn:
- Cập nhật TĂNG DẦN: chỉ lấy từ vài ngày trước ngày cuối của file (chồng lấn để sửa nến hôm trước còn dở dang), gộp theo ngày, bản mới thắng.
- KHÔNG BAO GIỜ làm file ngắn đi: gộp luôn là hợp của cũ và mới. Lỗi mạng/khoá/giới hạn tốc độ thì file giữ nguyên.
- Phát hiện giá lịch sử bị ĐIỀU CHỈNH (chia tách, cổ tức): nếu phần chồng lấn lệch nhau đáng kể thì tải lại toàn bộ; nhưng nếu nguồn trả ít phiên hơn
  file hiện có (ví dụ tài khoản Khách chỉ có 365 ngày) thì GIỮ file cũ và báo, để không mất lịch sử.
- Ghi nguyên tử (file tạm rồi thay thế), không để lại file nửa chừng.
"""
from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import data

COLUMNS = ["date", "open", "high", "low", "close", "volume"]
OVERLAP_DAYS = 7          # lấy chồng lấn để sửa nến chưa đóng cửa của lần trước
YEARS_FULL = 8            # số năm lấy cho mã chưa có file
ADJUST_TOLERANCE = 0.02   # lệch trung bình > 2% trên phần chồng lấn => giá lịch sử đã bị điều chỉnh
PAUSE = 3.0               # giây nghỉ giữa các lần gọi, tránh giới hạn tốc độ
CSV_DIR: Optional[Path] = None  # đặt khi kiểm thử; mặc định dùng data.CSV_DIR


def csv_dir() -> Path:
    return Path(CSV_DIR or data.CSV_DIR)


def default_fetch(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Lấy giá ngày đã chuẩn hoá về đồng (cần vnstock >= 5). Tra cứu lúc gọi để kiểm thử thay thế được."""
    return data.fetch_vnstock(symbol, start, end)


def read_csv(symbol: str) -> Optional[pd.DataFrame]:
    p = csv_dir() / f"{symbol}.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, parse_dates=["date"])
        return df[COLUMNS].dropna().sort_values("date").reset_index(drop=True)
    except Exception:  # noqa: BLE001
        return None


def merge_prices(old: Optional[pd.DataFrame], new: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Hợp theo ngày; khi trùng ngày thì bản mới thắng."""
    frames = [f[COLUMNS] for f in (old, new) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    allp = pd.concat(frames, ignore_index=True)
    allp["date"] = pd.to_datetime(allp["date"]).dt.tz_localize(None).dt.normalize()
    return allp.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def is_adjusted(old: pd.DataFrame, new: pd.DataFrame) -> bool:
    """Phần chồng lấn lệch nhau đáng kể => giá lịch sử đã được điều chỉnh sau khi bạn tải."""
    o = old.assign(date=pd.to_datetime(old["date"]).dt.normalize()).set_index("date")["close"]
    n = new.assign(date=pd.to_datetime(new["date"]).dt.tz_localize(None).dt.normalize()).set_index("date")["close"]
    both = o.index.intersection(n.index)
    if len(both) < 3:
        return False
    return float((n.loc[both] / o.loc[both] - 1).abs().median()) > ADJUST_TOLERANCE


def _write(symbol: str, df: pd.DataFrame) -> None:
    d = csv_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{symbol}.csv.tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, d / f"{symbol}.csv")


def update_symbol(symbol: str, fetch: Optional[Callable] = None, years_full: int = YEARS_FULL,
                  overlap_days: int = OVERLAP_DAYS, today: Optional[date] = None) -> Dict:
    fetch = fetch or default_fetch
    sym = symbol.upper().strip()
    today_ts = pd.Timestamp(today or date.today()).normalize()
    old = read_csv(sym)
    res = {"symbol": sym, "status": "ok", "added": 0, "last_date": None, "note": ""}
    base = old
    try:
        if old is None or old.empty:
            start = today_ts - pd.DateOffset(years=years_full)
            new = fetch(sym, f"{start:%Y-%m-%d}", f"{today_ts:%Y-%m-%d}")
            base = None
        else:
            start = old["date"].max() - pd.Timedelta(days=overlap_days)
            new = fetch(sym, f"{start:%Y-%m-%d}", f"{today_ts:%Y-%m-%d}")
            if new is not None and len(new) and is_adjusted(old, new):
                first = old["date"].min()
                full = fetch(sym, f"{first:%Y-%m-%d}", f"{today_ts:%Y-%m-%d}")
                if full is not None and len(full) >= 0.9 * len(old):
                    new, base = full, None
                    res["note"] = "Giá lịch sử đã được điều chỉnh (chia tách/cổ tức): đã tải lại toàn bộ."
                else:
                    res.update(status="giữ file cũ",
                               note="Giá lịch sử đã được điều chỉnh nhưng nguồn chỉ trả ít phiên hơn file hiện có (gói Khách giới hạn 365 ngày). "
                                    "Đã GIỮ file cũ, giá cũ có thể lệch; chạy `vnstock register` để có đủ lịch sử rồi cập nhật lại.")
                    res["last_date"] = old["date"].max()
                    return res
    except ImportError:
        res.update(status="thiếu vnstock", note="Chưa cài vnstock (xem trang Hướng dẫn).")
        return res
    except Exception as e:  # noqa: BLE001
        res.update(status="lỗi", note=f"{type(e).__name__}: {str(e)[:120]}")
        res["last_date"] = old["date"].max() if old is not None and len(old) else None
        return res
    if new is None or len(new) == 0:
        res.update(status="không có dữ liệu mới" if old is not None else "không lấy được")
        res["last_date"] = old["date"].max() if old is not None and len(old) else None
        return res
    merged = merge_prices(base, new)
    before = len(old) if old is not None else 0
    if base is None and old is not None and len(merged) < before:  # phòng hờ: không bao giờ làm ngắn file
        res.update(status="giữ file cũ", note="Dữ liệu mới ít phiên hơn file hiện có nên giữ nguyên.")
        res["last_date"] = old["date"].max()
        return res
    _write(sym, merged)
    res["added"] = max(len(merged) - before, 0)
    res["last_date"] = merged["date"].max()
    return res


def update_many(symbols: List[str], fetch: Optional[Callable] = None, progress: Optional[Callable] = None,
                pause: Optional[float] = None, sleeper: Callable = time.sleep, **kw) -> List[Dict]:
    """Cập nhật lần lượt; một mã lỗi không làm dừng các mã khác (trừ khi thiếu vnstock: dừng ngay)."""
    pause = PAUSE if pause is None else pause
    seen, order = set(), []
    for s in symbols:
        s = s.upper().strip()
        if s and s not in seen:
            seen.add(s)
            order.append(s)
    out: List[Dict] = []
    for i, sym in enumerate(order):
        r = update_symbol(sym, fetch, **kw)
        out.append(r)
        if progress:
            progress(i + 1, len(order), r)
        if r["status"] == "thiếu vnstock":
            out += [{"symbol": s, "status": "bỏ qua", "added": 0, "last_date": None, "note": "Thiếu vnstock."} for s in order[i + 1:]]
            break
        if i < len(order) - 1:
            sleeper(pause)
    return out


def last_data_date(symbols: List[str]) -> Optional[pd.Timestamp]:
    """Ngày giao dịch mới nhất trong các file (dùng hiển thị “dữ liệu đến ngày”)."""
    dates = []
    for s in symbols:
        df = read_csv(s)
        if df is not None and len(df):
            dates.append(df["date"].max())
    return max(dates) if dates else None
