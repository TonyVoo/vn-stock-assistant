"""Đọc câu tiếng Việt kiểu “hôm nay mua 100 FPT giá 120k, cắt lỗ 112k, mục tiêu 140k vì báo cáo tốt” thành BẢN NHÁP lệnh.

Dùng quy tắc cố định (không để AI đoán số, vì AI có thể hiểu sai). Câu hỏi (“có nên mua 100 FPT không?”) không bao giờ bị coi là lệnh.
Giá ghi tắt “k”/“nghìn” = x1.000; số nhỏ hơn 1.000 không đơn vị được hiểu là nghìn đồng và được ghi chú để bạn kiểm tra. Mọi thứ đều phải qua bước bạn duyệt.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

QUESTION_MARKERS = ("?", "có nên", "nên ", "có ổn", "liệu", "bao nhiêu", "được không", "ổn không", "thế nào", "như thế nào", "có đáng", "hay không", "tại sao", "vì sao")
STOP_WORDS = {"CP", "CL", "TP", "SL", "K", "TR", "LO", "ATO", "ATC", "VND", "HOSE", "HNX", "ĐỒNG"}
_NUM = r"\d[\d.,]*"
_UNIT = r"(?:\s*(k|nghìn|ngàn|tr|triệu)\b)?"
_AFTER = r"\s*(?:ở|tại|giá|là|:|@)?\s*(?:giá)?\s*"


def parse_number(s: str, unit: Optional[str] = None) -> Optional[float]:
    """“120.000” -> 120000; “28,5” -> 28,5; “28,5k” -> 28500; “1,2tr” -> 1.200.000. Không đọc được thì None."""
    s = (s or "").strip().strip(".,")
    if not s:
        return None
    try:
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):
            v = float(re.sub(r"[.,]", "", s))
        elif s.count(".") > 1 or s.count(",") > 1:
            v = float(re.sub(r"[.,]", "", s))
        else:
            v = float(s.replace(",", "."))
    except ValueError:
        return None
    u = (unit or "").lower()
    if u in ("k", "nghìn", "ngàn"):
        v *= 1000
    elif u in ("tr", "triệu"):
        v *= 1_000_000
    return v


def _grab(pattern: str, text: str):
    m = re.search(pattern, text, re.I)
    if not m:
        return None, text
    return m, (text[:m.start()] + " " + text[m.end():])


def _price(m) -> Optional[float]:
    return parse_number(m.group(1), m.group(2)) if m else None


def _date(text: str, today: date):
    low = text.lower()
    if "hôm qua" in low:
        return today - timedelta(days=1), re.sub(r"hôm qua", " ", text, flags=re.I)
    if "hôm nay" in low:
        return today, re.sub(r"hôm nay", " ", text, flags=re.I)
    m = re.search(r"(?:ngày\s*)?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", text, re.I)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y += 2000 if y < 100 else 0
        try:
            return date(y, mo, d), text[:m.start()] + " " + text[m.end():]
        except ValueError:
            return None, text
    return None, text


def is_question(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in QUESTION_MARKERS)


def parse(text: str, today: date, known: Iterable[str] = ()) -> Optional[Dict]:
    """Trả về bản nháp {side, symbol, qty, price, stop, target, date, reason, notes} hoặc None nếu không giống một câu ghi lệnh."""
    t = (text or "").strip()
    if not t or is_question(t):
        return None
    side_m = re.search(r"\b(mua|bán)\b", t, re.I)
    if not side_m:
        return None
    side = "buy" if side_m.group(1).lower() == "mua" else "sell"
    notes: List[str] = []

    reason = ""
    rm, t = _grab(r"(?:\bvì\b|\bdo\b|lý do:?)\s+(.+)$", t)
    if rm:
        reason = rm.group(1).strip()
    sm, t = _grab(rf"(?:cắt lỗ|\bcl\b|stop(?: loss)?|\bsl\b){_AFTER}({_NUM}){_UNIT}", t)
    tm, t = _grab(rf"(?:mục tiêu|chốt lời|target|\btp\b){_AFTER}({_NUM}){_UNIT}", t)
    when, t = _date(t, today)
    pm, t = _grab(rf"(?:\bgiá\b|@|\btại\b|\bở\b){_AFTER}({_NUM}){_UNIT}", t)

    price = _price(pm)
    if pm and not pm.group(2) and price is not None and price < 1000:
        notes.append(f"Mình hiểu giá {pm.group(1)} là {price * 1000:,.0f}đ (nghìn đồng). Sửa lại nếu sai.".replace(",", "."))
        price *= 1000
    stop, target = _price(sm), _price(tm)
    for nm, m, v in (("cắt lỗ", sm, stop), ("mục tiêu", tm, target)):
        if m and not m.group(2) and v is not None and v < 1000:
            notes.append(f"Mình hiểu {nm} {m.group(1)} là {v * 1000:,.0f}đ (nghìn đồng).".replace(",", "."))
    if stop is not None and stop < 1000:
        stop *= 1000
    if target is not None and target < 1000:
        target *= 1000

    side2 = re.search(r"\b(mua|bán)\b", t, re.I)  # tìm lại vì chuỗi đã bị cắt bớt các phần (lý do, giá, ngày...)
    rest = re.sub(r"\b(mua|bán)\b", " ", t[side2.start():] if side2 else t, count=1, flags=re.I)
    kn = {k.upper() for k in known}
    symbol, sym_span = None, None
    for m in re.finditer(r"\b[A-Za-z][A-Za-z0-9]{1,5}\b", rest):
        w = m.group(0)
        if w.upper() in STOP_WORDS:
            continue
        if (w.isupper() and 3 <= len(w) <= 4) or (w.upper() in kn and w.upper() not in STOP_WORDS and len(w) >= 3):
            symbol, sym_span = w.upper(), m.span()
            break
    if not symbol:
        return None
    rest = rest[:sym_span[0]] + " " + rest[sym_span[1]:]
    qm = re.search(rf"({_NUM})\s*(cp|cổ phiếu|cổ|lô|cphieu)?", rest, re.I)
    if not qm:
        return None
    qty = parse_number(qm.group(1))
    if qty is None or qty <= 0 or qty != int(qty):
        return None
    qty = int(qty)
    if (qm.group(2) or "").lower() == "lô":
        qty *= 100
        notes.append("1 lô = 100 cổ phiếu.")

    if when and when > today:
        notes.append("Ngày bạn nhập ở tương lai nên mình đặt là hôm nay.")
        when = today
    return {"side": side, "symbol": symbol, "qty": qty, "price": price, "stop": stop, "target": target, "date": when or today,
            "reason": reason, "notes": notes}
