"""Lấy dữ liệu giá lịch sử. Giá luôn được chuẩn hoá về đơn vị VND.

Thứ tự thử nguồn: vnstock (nếu cài) -> VNDirect dchart -> dữ liệu giả lập (demo).
Kết quả được cache theo ngày trong data/cache để không gọi lại nhiều lần.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import requests

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_MAX_AGE = 15 * 60  # giây
CSV_DIR = Path(os.getenv("PRICES_DIR") or Path(__file__).resolve().parent.parent / "data" / "prices")  # PRICES_DIR: đổi thư mục giá khi thử
COLUMNS = ["date", "open", "high", "low", "close", "volume"]

VN30_DEFAULT = ["ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
                "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
                "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"]


def _normalize(df: pd.DataFrame, scale: bool = True) -> pd.DataFrame:
    df = df[COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)
    # Nhiều nguồn trả giá theo nghìn đồng (vd 65.5) -> đưa về VND
    if scale and len(df) and df["close"].median() < 1000:
        for c in ("open", "high", "low", "close"):
            df[c] = df[c] * 1000
    return df


INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPCOMINDEX"}


def fetch_vnstock(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Lấy giá ngày bằng vnstock >= 5 (cài từ https://vnstocks.com, xem README). Có thể raise lỗi.

    Tài khoản Khách chỉ trả 365 ngày gần nhất; đăng ký key miễn phí (lệnh `vnstock register`) để có nhiều hơn.
    """
    import warnings

    from vnstock import Market  # type: ignore

    is_index = symbol in INDEX_SYMBOLS
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = Market()
        node = m.index(symbol) if is_index else m.equity(symbol)
        raw = node.ohlcv(start=start, end=end)
    raw = raw.rename(columns={"time": "date"})
    return _normalize(raw, scale=not is_index)


def _from_vnstock(symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    try:
        return fetch_vnstock(symbol, start, end)
    except Exception:
        return None


def _from_vndirect(symbol: str, days: int) -> Optional[pd.DataFrame]:
    now = int(time.time())
    try:
        r = requests.get(
            "https://dchart-api.vndirect.com.vn/dchart/history",
            params={"symbol": symbol, "resolution": "D",
                    "from": now - days * 86400, "to": now},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get("s") != "ok" or not j.get("t"):
            return None
        df = pd.DataFrame({
            "date": pd.to_datetime(j["t"], unit="s"),
            "open": j["o"], "high": j["h"], "low": j["l"], "close": j["c"],
            "volume": j["v"],
        })
        return _normalize(df)
    except Exception:
        return None


def demo_prices(symbol: str, days: int = 400) -> pd.DataFrame:
    """Dữ liệu giả lập (random walk có seed theo mã) — CHỈ để thử giao diện."""
    seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    n = days
    drift = rng.uniform(-0.0003, 0.0009)
    rets = rng.normal(drift, 0.017, n)
    close = rng.uniform(15000, 90000) * np.exp(np.cumsum(rets))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.integers(300_000, 5_000_000, n)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": vol})


def _from_csv(symbol: str) -> Optional[pd.DataFrame]:
    """Đọc data/prices/<MÃ>.csv do người dùng tự cung cấp.

    Cột bắt buộc (không phân biệt hoa thường): date, open, high, low, close, volume.
    Chấp nhận thêm tên cột tiếng Anh phổ biến như time, Date, Close...
    """
    f = CSV_DIR / f"{symbol}.csv"
    if not f.exists():
        return None
    try:
        df = pd.read_csv(f)
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.rename(columns={"time": "date", "tradingdate": "date", "vol": "volume"})
        return _normalize(df)
    except Exception:
        return None


def get_prices(symbol: str, days: int = 400) -> Tuple[pd.DataFrame, str]:
    """Trả về (DataFrame giá, tên nguồn). Nguồn: vnstock | vndirect | demo."""
    symbol = symbol.upper().strip()
    csv = _from_csv(symbol)
    if csv is not None and not csv.empty:
        return csv.tail(days) if days else csv, "csv"
    if os.getenv("DEMO_MODE") == "1":
        return demo_prices(symbol, days), "demo"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{symbol}_{pd.Timestamp.today():%Y%m%d}.csv"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_MAX_AGE:  # bộ nhớ đệm cho mã chưa có file CSV: chỉ 15 phút, không cả ngày
        df = pd.read_csv(cache, parse_dates=["date"])
        return df, "cache"

    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=days)
    df = _from_vnstock(symbol, f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}")
    source = "vnstock"
    if df is None or df.empty:
        df, source = _from_vndirect(symbol, days), "vndirect"
    if df is None or df.empty:
        return demo_prices(symbol, days), "demo"
    df.to_csv(cache, index=False)
    return df, source
