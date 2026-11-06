"""Cảnh báo cắt lỗ và mục tiêu cho các lệnh đang giữ trong Nhật ký.

Chỉ so sánh giá đóng cửa/tạm thời gần nhất trong dữ liệu của bạn với mức bạn đã đặt. App không đặt lệnh: bạn tự quyết định.
Mức cắt lỗ = 0 nghĩa là chưa đặt nên không cảnh báo (đã có cảnh báo riêng ở Bảng rủi ro).
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pandas as pd

from .explain import vnd

NEAR = 0.03  # coi là "gần" khi cách mức cắt lỗ/mục tiêu trong vòng 3% giá hiện tại
SEVERITY = {"hit_stop": 0, "near_stop": 1, "hit_target": 2, "near_target": 3}


def check(open_trades: Optional[pd.DataFrame], last_price: Callable[[str], Optional[float]]) -> List[Dict]:
    if open_trades is None or open_trades.empty:
        return []
    out: List[Dict] = []
    for t in open_trades.itertuples():
        p = last_price(t.symbol)
        if not p or p <= 0:
            continue
        stop = float(t.stop or 0)
        target = None if t.target is None or t.target != t.target or float(t.target) <= 0 else float(t.target)
        if stop > 0 and p <= stop:
            kind, msg = "hit_stop", f"{t.symbol} đã chạm hoặc xuống dưới mức cắt lỗ {vnd(stop)} (giá hiện tại {vnd(p)}). Theo kế hoạch của bạn là lúc cân nhắc bán."
        elif stop > 0 and p <= stop * (1 + NEAR):
            kind, msg = "near_stop", f"{t.symbol} đang gần mức cắt lỗ: giá {vnd(p)}, cắt lỗ {vnd(stop)} (cách {(p / stop - 1) * 100:.1f}%)."
        elif target and p >= target:
            kind, msg = "hit_target", f"{t.symbol} đã đạt mục tiêu {vnd(target)} (giá hiện tại {vnd(p)}). Cân nhắc chốt lời hoặc nâng mức cắt lỗ."
        elif target and p >= target * (1 - NEAR):
            kind, msg = "near_target", f"{t.symbol} sắp đạt mục tiêu: giá {vnd(p)}, mục tiêu {vnd(target)}."
        else:
            continue
        out.append({"id": int(t.id), "symbol": t.symbol, "kind": kind, "price": float(p), "message": msg})
    return sorted(out, key=lambda a: (SEVERITY[a["kind"]], a["symbol"]))


def kind_style(kind: str) -> str:
    return "bad" if kind in ("hit_stop", "near_stop") else "good"
