"""Kiểm tra trước khi mua ("đèn giao thông"): xanh = ổn, vàng = cần cân nhắc, đỏ = vi phạm quy tắc của chính bạn.

Không khuyên mua hay không mua. Chỉ chặn các sai lầm kinh điển: cắt lỗ vô lý, dồn quá nhiều vào một mã, hết tiền mặt dự phòng,
mua mã khó bán, lãi tiềm năng không đáng so với rủi ro. Mọi ngưỡng đều hiển thị trong câu giải thích.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .risk import FEE_RATE, SELL_TAX

OK, WARN, BAD = "ok", "warn", "bad"
_RANK = {OK: 0, WARN: 1, BAD: 2}
MIN_CASH_AFTER = 0.10     # nên còn tối thiểu 10% tổng tài sản là tiền mặt sau khi mua
LIQ_WARN, LIQ_BAD = 5e9, 1e9  # giá trị giao dịch trung bình mỗi phiên (đồng)


def _vnd(x: float) -> str:
    return f"{x:,.0f}đ".replace(",", ".")


def check(entry: float, stop: float, target: Optional[float], shares: int, total_assets: float, cash: Optional[float],
          existing_value: float = 0.0, risk_pct: float = 0.02, max_alloc: float = 0.30, avg_value: Optional[float] = None) -> Dict:
    """cash=None nghĩa là chưa có Danh mục (bỏ qua các kiểm tra tiền mặt). existing_value: giá trị đang giữ của chính mã này."""
    items: List[Dict] = []

    def add(label: str, level: str, text: str) -> None:
        items.append({"label": label, "level": level, "text": text})

    if entry <= 0 or shares <= 0 or total_assets <= 0:
        return {"level": BAD, "items": [{"label": "Dữ liệu", "level": BAD, "text": "Giá, số lượng và tổng tài sản phải lớn hơn 0."}]}
    cost = shares * entry * (1 + FEE_RATE)

    # 1. Mức cắt lỗ
    if stop <= 0 or stop >= entry:
        add("Mức cắt lỗ", BAD, "Chưa có mức cắt lỗ hợp lệ (phải thấp hơn giá mua). Không có cắt lỗ thì không biết mình có thể mất tối đa bao nhiêu.")
    else:
        gap = 1 - stop / entry
        if gap > 0.15:
            add("Mức cắt lỗ", WARN, f"Cắt lỗ cách giá mua {gap * 100:.0f}%: khi chạm, bạn đã mất khá nhiều. Cân nhắc đặt gần hơn hoặc mua ít hơn.")
        elif gap < 0.01:
            add("Mức cắt lỗ", WARN, f"Cắt lỗ chỉ cách giá mua {gap * 100:.1f}%: biến động bình thường trong ngày cũng có thể quét trúng.")
        else:
            add("Mức cắt lỗ", OK, f"Cắt lỗ cách giá mua {gap * 100:.0f}%: hợp lý.")
        loss = shares * ((entry - stop) + entry * FEE_RATE + stop * (FEE_RATE + SELL_TAX))
        lim = total_assets * risk_pct
        if loss > lim * 1.001:
            add("Mất nếu sai", BAD, f"Nếu chạm cắt lỗ bạn mất khoảng {_vnd(loss)} ({loss / total_assets * 100:.1f}% tổng tài sản), vượt mức {risk_pct * 100:.1f}% bạn đã đặt.")
        else:
            add("Mất nếu sai", OK, f"Nếu chạm cắt lỗ bạn mất khoảng {_vnd(loss)} ({loss / total_assets * 100:.1f}% tổng tài sản), trong mức {risk_pct * 100:.1f}% bạn chấp nhận.")

    # 2. Tỷ trọng một mã
    w = (existing_value + cost) / total_assets
    if w > max_alloc * 1.001:
        add("Dồn vào một mã", BAD, f"Sau khi mua, mã này chiếm {w * 100:.0f}% tổng tài sản, vượt mức {max_alloc * 100:.0f}% bạn đặt cho một mã.")
    elif w > max_alloc * 0.8:
        add("Dồn vào một mã", WARN, f"Sau khi mua, mã này chiếm {w * 100:.0f}% tổng tài sản, sát mức tối đa {max_alloc * 100:.0f}%.")
    else:
        add("Dồn vào một mã", OK, f"Sau khi mua, mã này chiếm {w * 100:.0f}% tổng tài sản (mức tối đa bạn đặt: {max_alloc * 100:.0f}%).")

    # 3. Tiền mặt
    if cash is not None:
        if cost > cash:
            add("Tiền mặt", BAD, f"Cần khoảng {_vnd(cost)} nhưng tiền mặt trong Danh mục chỉ có {_vnd(cash)}.")
        else:
            left = (cash - cost) / total_assets
            if left < MIN_CASH_AFTER:
                add("Tiền mặt dự phòng", WARN, f"Mua xong chỉ còn {left * 100:.0f}% tài sản là tiền mặt (nên giữ tối thiểu {MIN_CASH_AFTER * 100:.0f}%) để có chỗ xoay xở khi giá giảm.")
            else:
                add("Tiền mặt dự phòng", OK, f"Mua xong vẫn còn {left * 100:.0f}% tài sản là tiền mặt dự phòng.")

    # 4. Lãi tiềm năng so với rủi ro
    if target and target > entry and 0 < stop < entry:
        rr = (target - entry) / (entry - stop)
        if rr < 1:
            add("Lãi so với lỗ", BAD, f"Lãi tiềm năng chỉ bằng {rr:.1f} lần lỗ tiềm năng: thắng đủ lần mới hòa, không đáng rủi ro.")
        elif rr < 1.5:
            add("Lãi so với lỗ", WARN, f"Lãi tiềm năng bằng {rr:.1f} lần lỗ tiềm năng. Người kỷ luật thường chỉ vào lệnh khi từ 2 lần trở lên.")
        else:
            add("Lãi so với lỗ", OK, f"Lãi tiềm năng bằng {rr:.1f} lần lỗ tiềm năng.")
    else:
        add("Lãi so với lỗ", WARN, "Chưa có giá mục tiêu hợp lệ nên chưa biết lãi tiềm năng có đáng so với rủi ro không.")

    # 5. Thanh khoản
    if avg_value is not None:
        if avg_value < LIQ_BAD:
            add("Dễ bán", BAD, f"Mỗi phiên chỉ giao dịch khoảng {_vnd(avg_value)}: rất khó bán nhanh khi cần, có thể phải bán rẻ.")
        elif avg_value < LIQ_WARN:
            add("Dễ bán", WARN, f"Mỗi phiên giao dịch khoảng {_vnd(avg_value)}: thanh khoản thấp, khi giảm mạnh có thể khó bán.")
        else:
            add("Dễ bán", OK, f"Mỗi phiên giao dịch khoảng {_vnd(avg_value)}: bán dễ.")
    level = max((i["level"] for i in items), key=_RANK.get)
    return {"level": level, "items": items}


TITLE = {OK: ("Đèn xanh", "Không thấy vi phạm quy tắc nào. Đây không phải lời khuyên mua; quyết định vẫn là của bạn."),
         WARN: ("Đèn vàng", "Có điểm cần cân nhắc kỹ trước khi mua."),
         BAD: ("Đèn đỏ", "Lệnh này vi phạm quy tắc an toàn của chính bạn. Nên chỉnh lại trước khi mua.")}
