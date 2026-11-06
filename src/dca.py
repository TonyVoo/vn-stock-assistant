"""Kế hoạch mua dần (DCA): mỗi tháng bỏ một số tiền cố định để mua, thay vì dồn một lần.

Giả định minh bạch: giá giữ NGUYÊN như hôm nay trong cả kế hoạch (không ai biết giá tương lai). Vì vậy bảng chỉ cho biết
"mỗi tháng mua được bao nhiêu cổ phiếu, còn dư bao nhiêu tiền", KHÔNG dự báo lãi. Mua dần giúp giá vốn trung bình mượt hơn
chứ không đảm bảo có lãi. Mỗi lần mua phải theo lô 100 cổ phiếu; tiền chưa đủ mua một lô được dồn sang tháng sau.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import pandas as pd

from .risk import FEE_RATE, LOT

SPLIT, ROTATE = "chia_deu", "luan_phien"
MODE_LABEL = {SPLIT: "Chia tiền mỗi tháng cho tất cả các mã", ROTATE: "Mỗi tháng mua một mã, lần lượt luân phiên"}
MAX_MONTHS = 60
COLUMNS = ["month", "symbol", "price", "qty", "spent", "carry"]


def lots_affordable(avail: float, price: float, fee: float = FEE_RATE) -> int:
    """Số cổ phiếu (bội của 100) mua được với số tiền avail, đã tính phí mua."""
    if price <= 0 or avail <= 0:
        return 0
    return int(math.floor(avail / (price * (1 + fee)) / LOT)) * LOT


def plan(budget: float, months: int, prices: Dict[str, float], weights: Optional[Dict[str, float]] = None,
         mode: str = SPLIT, fee: float = FEE_RATE) -> Dict:
    """Lập bảng mua dần. prices: {mã: giá hiện tại (đồng)}. weights: tỷ trọng mỗi mã (mặc định chia đều)."""
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("Số tiền mỗi tháng phải lớn hơn 0.")
    if not 1 <= int(months) <= MAX_MONTHS:
        raise ValueError(f"Số tháng phải từ 1 đến {MAX_MONTHS}.")
    syms = [s for s, p in prices.items() if p and p > 0]
    if not syms:
        raise ValueError("Chưa có mã nào có giá hợp lệ.")
    if mode not in MODE_LABEL:
        raise ValueError("Cách chia không hợp lệ.")
    months = int(months)
    w = {s: float((weights or {}).get(s, 1.0)) for s in syms}
    if any(x < 0 for x in w.values()) or sum(w.values()) <= 0:
        raise ValueError("Tỷ trọng phải không âm và có ít nhất một mã lớn hơn 0.")
    tot_w = sum(w.values())
    carry = {s: 0.0 for s in syms}
    rows: List[Dict] = []
    if mode == SPLIT:
        for m in range(1, months + 1):
            for s in syms:
                if w[s] <= 0:
                    continue
                avail = carry[s] + budget * w[s] / tot_w
                q = lots_affordable(avail, prices[s], fee)
                spent = q * prices[s] * (1 + fee)
                carry[s] = avail - spent
                rows.append({"month": m, "symbol": s, "price": prices[s], "qty": q, "spent": spent, "carry": carry[s]})
    else:
        order = [s for s in syms if w[s] > 0]
        pool = 0.0
        for m in range(1, months + 1):
            s = order[(m - 1) % len(order)]
            avail = pool + budget
            q = lots_affordable(avail, prices[s], fee)
            spent = q * prices[s] * (1 + fee)
            pool = avail - spent
            rows.append({"month": m, "symbol": s, "price": prices[s], "qty": q, "spent": spent, "carry": pool})
    df = pd.DataFrame(rows, columns=COLUMNS)
    by = (df.groupby("symbol", as_index=False).agg(qty=("qty", "sum"), spent=("spent", "sum"))
          if len(df) else pd.DataFrame(columns=["symbol", "qty", "spent"]))
    by["avg_cost"] = by["spent"] / by["qty"].where(by["qty"] > 0)
    leftover = carry_total = float(sum(carry.values())) if mode == SPLIT else float(df["carry"].iloc[-1])
    invested = float(df["spent"].sum())
    notes: List[str] = []
    for s in syms:
        if w[s] > 0 and int(by.loc[by["symbol"] == s, "qty"].sum()) == 0:
            share = budget * w[s] / tot_w if mode == SPLIT else budget
            notes.append(f"{s}: một lô {LOT} cổ phiếu cần khoảng {prices[s] * LOT * (1 + fee):,.0f} đồng, "
                         f"hơn nhiều so với {share:,.0f} đồng/tháng nên kế hoạch này chưa mua được {s}. "
                         "Hãy tăng số tiền, bớt số mã, hoặc chọn mã giá thấp hơn.".replace(",", "."))
    if invested == 0 and not notes:
        notes.append("Với số tiền này chưa mua được lô nào trong thời gian đã chọn.")
    return {"schedule": df, "by_symbol": by, "invested": invested, "leftover": leftover, "months": months,
            "total_budget": budget * months, "notes": notes, "carry_total": carry_total}
