"""Bộ lọc cổ phiếu theo tiêu chí do bạn chọn (thanh khoản, xu hướng, biến động...).

Mục đích duy nhất: THU HẸP danh sách cần xem. Nghiên cứu của app chưa tìm thấy lợi thế đáng tin từ tín hiệu kỹ thuật, nên một mã
qua được bộ lọc KHÔNG có nghĩa là nên mua. Mọi số liệu chỉ dùng dữ liệu quá khứ đến phiên gần nhất.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

TREND_ANY, TREND_MA50, TREND_BOTH = "Bất kỳ", "Giá trên đường trung bình 50 phiên", "Giá trên cả đường 50 và 200 phiên"
TRENDS = [TREND_ANY, TREND_MA50, TREND_BOTH]
COLUMNS = ["symbol", "close", "avg_value", "above50", "above200", "ret60", "from_high", "vol", "rsi"]


def metrics(symbol: str, df: pd.DataFrame) -> Optional[Dict]:
    """Chỉ số của một mã từ bảng giá (date, close, volume). Trả None nếu dưới 60 phiên."""
    if df is None or len(df) < 60:
        return None
    c = df["close"].astype(float)
    delta = c.diff()
    up, down = delta.clip(lower=0).rolling(14).mean(), (-delta.clip(upper=0)).rolling(14).mean()
    rsi = float(100 - 100 / (1 + up.iloc[-1] / down.iloc[-1])) if down.iloc[-1] > 0 else 100.0
    sma50 = float(c.tail(50).mean())
    sma200 = float(c.tail(200).mean()) if len(c) >= 200 else np.nan
    return {"symbol": symbol, "close": float(c.iloc[-1]),
            "avg_value": float((c * df["volume"].astype(float)).tail(20).mean()),
            "above50": bool(c.iloc[-1] > sma50), "above200": (bool(c.iloc[-1] > sma200) if not np.isnan(sma200) else None),
            "ret60": float(c.iloc[-1] / c.iloc[-61] - 1) if len(c) >= 61 else np.nan,
            "from_high": float(c.iloc[-1] / c.tail(252).max() - 1),
            "vol": float(c.pct_change().tail(20).std()), "rsi": rsi}


def screen(m: pd.DataFrame, min_value: float = 0.0, trend: str = TREND_ANY, max_vol: Optional[float] = None,
           max_rsi: Optional[float] = None, max_from_high: Optional[float] = None) -> pd.DataFrame:
    """Giữ mã thoả TẤT CẢ tiêu chí đã đặt. max_from_high: cách đỉnh 1 năm tối đa (0,2 = 20%). Thiếu dữ liệu cho tiêu chí nào thì mã bị loại (không đoán)."""
    if m is None or m.empty:
        return pd.DataFrame(columns=COLUMNS)
    keep = m["avg_value"] >= min_value
    if trend in (TREND_MA50, TREND_BOTH):
        keep &= m["above50"].fillna(False).astype(bool)
    if trend == TREND_BOTH:
        keep &= m["above200"].fillna(False).astype(bool)
    if max_vol is not None:
        keep &= m["vol"] <= max_vol
    if max_rsi is not None:
        keep &= m["rsi"] <= max_rsi
    if max_from_high is not None:
        keep &= m["from_high"] >= -max_from_high
    return m[keep].sort_values("avg_value", ascending=False).reset_index(drop=True)
