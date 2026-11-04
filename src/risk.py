"""Quản trị rủi ro theo đặc thù thị trường Việt Nam (lô 100, bước giá, phí, thuế)."""
from __future__ import annotations

import math
from typing import Dict

LOT = 100
FEE_RATE = 0.0015   # phí môi giới mỗi chiều (điều chỉnh theo công ty chứng khoán của bạn)
SELL_TAX = 0.001    # thuế bán 0,1%
LIMITS = {"HOSE": 0.07, "HNX": 0.10, "UPCOM": 0.15}


def tick_size(price: float, exchange: str = "HOSE") -> int:
    """Bước giá HOSE: <10k: 10đ; 10k-<50k: 50đ; >=50k: 100đ. HNX/UPCoM: 100đ."""
    if exchange != "HOSE":
        return 100
    if price < 10_000:
        return 10
    if price < 50_000:
        return 50
    return 100


def round_to_tick(price: float, exchange: str = "HOSE", mode: str = "nearest") -> float:
    t = tick_size(price, exchange)
    q = price / t
    q = {"down": math.floor(q), "up": math.ceil(q)}.get(mode, round(q))
    return float(q * t)


def position_size(capital: float, entry: float, stop: float,
                  risk_pct: float = 0.015, max_alloc: float = 0.30,
                  fee: float = FEE_RATE, tax: float = SELL_TAX) -> Dict:
    """Tính số cổ phiếu nên mua sao cho nếu chạm cắt lỗ thì chỉ mất ~risk_pct vốn.

    Trả về dict; nếu đầu vào không hợp lệ thì có khoá "error".
    """
    if capital <= 0 or entry <= 0 or stop <= 0:
        return {"error": "Vốn, giá vào, giá cắt lỗ phải > 0"}
    if stop >= entry:
        return {"error": "Giá cắt lỗ phải thấp hơn giá vào (chỉ có lệnh mua, không bán khống)"}

    loss_per_share = (entry - stop) + entry * fee + stop * (fee + tax)  # lỗ thực tế gồm phí/thuế
    risk_amount = capital * risk_pct
    by_risk = risk_amount / loss_per_share
    by_alloc = capital * max_alloc / (entry * (1 + fee))
    by_cash = capital / (entry * (1 + fee))
    shares = int(min(by_risk, by_alloc, by_cash) // LOT * LOT)

    if shares < LOT:
        need = int(math.ceil(entry * (1 + fee) * LOT))
        min_risk = LOT * loss_per_share / capital
        if need > capital:
            msg = f"Không đủ tiền mua 1 lô (100 cp): cần ~{need:,.0f}đ."
        elif need > capital * max_alloc:
            msg = (f"1 lô (~{need:,.0f}đ) vượt tỷ trọng tối đa {max_alloc*100:.0f}% vốn. "
                   f"Nâng tỷ trọng tối đa lên ~{need/capital*100:.0f}% hoặc chọn mã giá thấp hơn.")
        else:
            msg = (f"Với cắt lỗ này, 1 lô (100 cp) đã rủi ro ~{min_risk*100:.1f}% vốn, "
                   f"cao hơn mức {risk_pct*100:.1f}% bạn đặt. Hãy đặt cắt lỗ gần hơn, "
                   f"chọn mã giá thấp hơn, hoặc chấp nhận rủi ro ≥ {min_risk*100:.1f}%.")
        return {"shares": 0, "limited_by": "vốn", "message": msg, "lot_cost": need,
                "min_risk_pct_for_one_lot": min_risk}

    limited = min((by_risk, "rủi ro"), (by_alloc, "tỷ trọng tối đa"), (by_cash, "tiền mặt"))[1]
    cost = shares * entry * (1 + fee)
    return {
        "shares": shares,
        "lots": shares // LOT,
        "cost": cost,
        "alloc_pct": cost / capital,
        "max_loss": shares * loss_per_share,
        "max_loss_pct": shares * loss_per_share / capital,
        "breakeven": entry * (1 + fee) / (1 - fee - tax),
        "limited_by": limited,
    }


def reward_risk(entry: float, stop: float, target: float) -> float:
    if entry <= stop or target <= entry:
        return 0.0
    return (target - entry) / (entry - stop)


def price_limits(ref_price: float, exchange: str = "HOSE") -> Dict[str, float]:
    pct = LIMITS.get(exchange, 0.07)
    return {"ceiling": round_to_tick(ref_price * (1 + pct), exchange, "down"),
            "floor": round_to_tick(ref_price * (1 - pct), exchange, "up")}
