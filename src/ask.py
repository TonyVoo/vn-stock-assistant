"""Trả lời câu hỏi "giờ mua có ổn không, hay đợi giá xuống?" bằng số liệu, KHÔNG đoán giá.

Trung thực về điều không biết: không ai biết giá ngày mai. Module chỉ (1) mô tả giá đang ở đâu so với lịch sử của chính nó và so với giá vốn của bạn,
(2) cho thấy giá vốn trung bình thay đổi thế nào nếu mua một lần hay chia nhiều lần trong các kịch bản giá đi ngang, giảm, tăng,
(3) nêu cách làm thường dùng cho từng hoàn cảnh. Mua dần giảm rủi ro chọn sai thời điểm, không đảm bảo giá vốn thấp hơn.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .risk import FEE_RATE

SCENARIOS = [("Giá đi ngang", 0.0), ("Giá giảm dần 5% mỗi lần", -0.05), ("Giá tăng dần 5% mỗi lần", 0.05)]


def facts(df: pd.DataFrame) -> Optional[Dict]:
    """Giá đang ở đâu so với chính nó. Cần tối thiểu 60 phiên."""
    if df is None or len(df) < 60:
        return None
    c = df["close"].astype(float)
    last = float(c.iloc[-1])
    yr = c.tail(252)
    delta = c.diff()
    up, down = delta.clip(lower=0).rolling(14).mean().iloc[-1], (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
    rsi = float(100 - 100 / (1 + up / down)) if down > 0 else 100.0
    ma50 = float(c.tail(50).mean())
    ma200 = float(c.tail(200).mean()) if len(c) >= 200 else None
    lo, hi = float(yr.min()), float(yr.max())
    return {"price": last, "ma50": ma50, "ma200": ma200, "high": hi, "low": lo, "rsi": rsi,
            "from_high": last / hi - 1, "pos_in_range": (last - lo) / (hi - lo) if hi > lo else 0.5,
            "vs_ma50": last / ma50 - 1}


def average_scenarios(price: float, budget: float, tranches: int, held_qty: float = 0.0, held_avg: float = 0.0) -> List[Dict]:
    """Giá vốn trung bình mới (gồm số đang giữ) nếu mua một lần hôm nay hoặc chia đều `tranches` lần theo các kịch bản giá. Số cổ phiếu tính gần đúng, bỏ qua lô 100."""
    out: List[Dict] = []
    base_qty, base_cost = float(held_qty), float(held_qty) * float(held_avg)

    def run(name: str, prices: List[float]) -> Dict:
        per = budget / len(prices)
        qty = sum(per / (p * (1 + FEE_RATE)) for p in prices)
        spent = per * len(prices)
        new_avg = (base_cost + spent) / (base_qty + qty) if base_qty + qty else 0.0
        return {"name": name, "avg": new_avg, "qty": qty, "spent": spent}

    out.append(run("Mua hết một lần hôm nay", [price]))
    if tranches > 1:
        for label, step in SCENARIOS:
            out.append(run(f"Chia {tranches} lần, {label.lower()}", [price * (1 + step * i) for i in range(tranches)]))
    return out


def guidance(f: Dict, held_qty: float = 0.0, held_avg: float = 0.0, weight_after: Optional[float] = None, max_alloc: float = 0.30) -> List[Dict]:
    """Các nhận xét mô tả + cách làm thường dùng. Mỗi mục {level: info|warn, text}. Không dự đoán giá."""
    out: List[Dict] = []
    p = f["price"]
    hot = f["rsi"] > 70 or f["vs_ma50"] > 0.10
    falling = p < f["ma50"] and f["ma200"] is not None and p < f["ma200"]
    if hot:
        out.append({"level": "warn", "text": f"Giá vừa tăng khá nhanh (RSI {f['rsi']:.0f}, cao hơn đường trung bình 50 phiên {f['vs_ma50'] * 100:.0f}%). "
                                             "Mua một lần ở thời điểm này dễ gặp cảnh giá điều chỉnh ngay sau đó. Nếu muốn mua, chia nhỏ thành nhiều lần."})
    elif falling:
        out.append({"level": "warn", "text": "Giá đang nằm dưới cả đường trung bình 50 và 200 phiên, tức xu hướng đang giảm. Đợi thêm có thể mua được rẻ hơn, "
                                             "nhưng cũng có thể giá còn giảm tiếp. Nếu mua, chỉ nên mua một phần nhỏ và đặt mức cắt lỗ."})
    else:
        out.append({"level": "info", "text": "Chưa thấy dấu hiệu giá quá nóng hay đang giảm rõ rệt, nên chia 2 đến 3 lần là cách hợp lý."})
    if f["from_high"] > -0.03:
        out.append({"level": "info", "text": "Giá đang sát đỉnh 1 năm: không có nghĩa sẽ giảm, nhưng bạn đang mua ở vùng cao nhất của năm."})
    elif f["from_high"] < -0.30:
        out.append({"level": "info", "text": f"Giá thấp hơn đỉnh 1 năm {abs(f['from_high']) * 100:.0f}%. Rẻ so với trước đây không có nghĩa là rẻ về giá trị; hãy xem công ty có gì thay đổi."})
    if held_qty > 0 and held_avg > 0:
        gap = p / held_avg - 1
        if gap < -0.05:
            out.append({"level": "warn", "text": f"Giá hiện thấp hơn giá vốn của bạn {abs(gap) * 100:.0f}%. Mua thêm sẽ kéo giá vốn xuống, nhưng đó là mua thêm vào mã đang lỗ: "
                                                 "chỉ làm khi lý do mua ban đầu vẫn còn đúng, và đừng để mã chiếm quá nhiều tài sản."})
        elif gap > 0.05:
            out.append({"level": "info", "text": f"Giá hiện cao hơn giá vốn của bạn {gap * 100:.0f}%. Mua thêm sẽ kéo giá vốn trung bình lên."})
    if weight_after is not None and weight_after > max_alloc:
        out.append({"level": "warn", "text": f"Sau khi mua, mã này chiếm {weight_after * 100:.0f}% tổng tài sản, vượt mức {max_alloc * 100:.0f}% bạn đặt."})
    out.append({"level": "info", "text": "Không ai biết giá ngày mai. Đợi giá xuống có thể bỏ lỡ nếu giá tăng; mua một lần có thể mua đúng đỉnh. "
                                         "Mua dần giúp giảm rủi ro chọn sai thời điểm, nhưng không đảm bảo giá vốn thấp hơn."})
    return out
