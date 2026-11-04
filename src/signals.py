"""Chỉ báo kỹ thuật và chấm điểm cổ phiếu (thuần định lượng, không dùng AI)."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

MIN_AVG_VALUE_VND = 5_000_000_000  # thanh khoản tối thiểu: 5 tỷ VND/phiên


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(loss != 0, 100.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    for n in (20, 50, 200):
        d[f"sma{n}"] = c.rolling(n).mean()
    d["rsi14"] = rsi(c)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_signal"]
    d["vol_ratio"] = d["volume"] / d["volume"].rolling(20).mean()
    d["atr14"] = atr(d)
    d["value"] = d["close"] * d["volume"]
    return d


def score_stock(df: pd.DataFrame, index_df: Optional[pd.DataFrame] = None) -> Dict:
    """Chấm điểm 0-100 + lý do + gợi ý điểm cắt lỗ theo ATR.

    Đây là bộ lọc để thu hẹp danh sách cần xem, KHÔNG phải tín hiệu mua/bán chắc chắn.
    """
    if len(df) < 60:
        return {"score": None, "reasons": ["Không đủ dữ liệu (cần >= 60 phiên)"],
                "warnings": [], "liquid": False}

    return score_indicators(add_indicators(df), index_df)


def score_indicators(d: pd.DataFrame, index_df: Optional[pd.DataFrame] = None) -> Dict:
    """Chấm điểm từ DataFrame đã có chỉ báo; phiên cuối là phiên hiện tại.

    Các chỉ báo chỉ dùng dữ liệu quá khứ nên có thể tính một lần rồi cắt lát khi backtest.
    """
    if len(d) < 60:
        return {"score": None, "reasons": [], "warnings": [], "liquid": False}
    last, prev = d.iloc[-1], d.iloc[-2]
    score, reasons, warnings = 50.0, [], []

    # Xu hướng (tối đa ±25)
    if last.close > last.sma50:
        score += 8; reasons.append("Giá trên MA50")
    else:
        score -= 8; reasons.append("Giá dưới MA50")
    if not np.isnan(last.sma200):
        if last.close > last.sma200:
            score += 7; reasons.append("Giá trên MA200 (xu hướng dài hạn tăng)")
        else:
            score -= 7; reasons.append("Giá dưới MA200 (xu hướng dài hạn giảm)")
    if last.sma20 > last.sma50:
        score += 5; reasons.append("MA20 trên MA50")
    else:
        score -= 5
    if not np.isnan(last.sma200) and last.sma50 > last.sma200:
        score += 5

    # Động lượng (tối đa ±15)
    if 50 <= last.rsi14 <= 68:
        score += 8; reasons.append(f"RSI {last.rsi14:.0f}: động lượng tốt, chưa quá mua")
    elif last.rsi14 > 75:
        score -= 8; warnings.append(f"RSI {last.rsi14:.0f}: quá mua, dễ điều chỉnh")
    elif last.rsi14 < 35:
        score -= 4; warnings.append(f"RSI {last.rsi14:.0f}: yếu/quá bán, chưa có tín hiệu đảo chiều")
    if last.macd_hist > 0 and last.macd_hist > prev.macd_hist:
        score += 7; reasons.append("MACD histogram dương và đang tăng")
    elif last.macd_hist < 0:
        score -= 5

    # Khối lượng (tối đa ±8)
    up_day = last.close > prev.close
    if last.vol_ratio >= 1.5 and up_day:
        score += 8; reasons.append(f"Tăng giá kèm khối lượng {last.vol_ratio:.1f}x trung bình")
    elif last.vol_ratio >= 1.5 and not up_day:
        score -= 8; warnings.append(f"Giảm giá kèm khối lượng {last.vol_ratio:.1f}x trung bình (bán mạnh)")

    # Sức mạnh tương đối so với VN-Index, 60 phiên (tối đa ±10)
    if index_df is not None and len(index_df) >= 61:
        r_stock = d["close"].iloc[-1] / d["close"].iloc[-61] - 1
        r_idx = index_df["close"].iloc[-1] / index_df["close"].iloc[-61] - 1
        diff = r_stock - r_idx
        if diff > 0.05:
            score += 10; reasons.append(f"Mạnh hơn VN-Index {diff*100:.1f}% trong 60 phiên")
        elif diff < -0.05:
            score -= 10; reasons.append(f"Yếu hơn VN-Index {abs(diff)*100:.1f}% trong 60 phiên")

    # Thanh khoản
    avg_value = d["value"].tail(20).mean()
    liquid = bool(avg_value >= MIN_AVG_VALUE_VND)
    if not liquid:
        warnings.append(f"Thanh khoản thấp (~{avg_value/1e9:.1f} tỷ/phiên), khó thoát lệnh")
        score -= 15

    stop = float(last.close - 2 * last.atr14)
    return {
        "score": float(np.clip(score, 0, 100)),
        "close": float(last.close),
        "rsi": float(last.rsi14),
        "vol_ratio": float(last.vol_ratio),
        "atr": float(last.atr14),
        "suggested_stop": stop,
        "stop_pct": float((last.close - stop) / last.close),
        "avg_value": float(avg_value),
        "liquid": liquid,
        "reasons": reasons,
        "warnings": warnings,
    }


def label(score: Optional[float]) -> str:
    if score is None:
        return "N/A"
    if score >= 75:
        return "Mạnh"
    if score >= 60:
        return "Khá"
    if score >= 40:
        return "Trung tính"
    return "Yếu"
