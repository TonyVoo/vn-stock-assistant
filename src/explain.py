"""Diễn đạt số liệu kỹ thuật bằng tiếng Việt đơn giản + định dạng số kiểu Việt Nam (1.234.567 / 12,5%)."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def vi_date(d) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d:%d/%m/%Y}"


def is_partial_session(last_date, now: Optional[dt.datetime] = None) -> bool:
    """Nến cuối là của hôm nay và phiên chưa đóng cửa (trước ~15:05) -> giá/khối lượng chỉ là tạm thời."""
    now = now or dt.datetime.now(VN_TZ)
    return (pd.Timestamp(last_date).date() == now.date() and now.weekday() < 5
            and now.time() < dt.time(15, 5))


# ---------- định dạng số kiểu Việt Nam ----------
def _vn(s: str) -> str:
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def num(x: float, decimals: int = 0) -> str:
    return _vn(f"{x:,.{decimals}f}")


def vnd(x: float) -> str:
    return num(x) + "đ"


def pct(x: float, decimals: int = 1, signed: bool = True) -> str:
    s = f"{x * 100:+,.{decimals}f}%" if signed else f"{x * 100:,.{decimals}f}%"
    return _vn(s)


def money_short(x: float) -> str:
    """10.000.000 -> '10 triệu'; 2.500.000 -> '2,5 triệu'; 1.200.000.000 -> '1,2 tỷ'."""
    a = abs(x)
    if a >= 1e9:
        v, unit = x / 1e9, " tỷ"
    elif a >= 1e6:
        v, unit = x / 1e6, " triệu"
    else:
        return vnd(x)
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return _vn(s) + unit


# ---------- diễn đạt trạng thái cổ phiếu ----------
def trend(score: Optional[float]) -> Tuple[str, str, str]:
    """(nhãn, loại màu, giải thích). Mô tả hiện trạng, KHÔNG dự đoán tương lai."""
    if score is None:
        return "Chưa đủ dữ liệu", "muted", "Cần ít nhất 60 phiên giao dịch để đánh giá."
    if score >= 60:
        return "Đang tăng", "up", "Giá nằm trên các đường trung bình và đang có đà đi lên."
    if score >= 40:
        return "Đi ngang", "flat", "Chưa có xu hướng rõ, giá dao động quanh mức hiện tại."
    return "Đang giảm", "down", "Giá nằm dưới các đường trung bình, xu hướng đang yếu."


def heat(rsi: Optional[float]) -> Tuple[str, str, str]:
    if rsi is None:
        return "—", "muted", ""
    if rsi >= 70:
        return "Tăng nóng", "flat", "Giá đã tăng khá nhanh gần đây, dễ có nhịp nghỉ hoặc điều chỉnh."
    if rsi <= 30:
        return "Giảm sâu", "flat", "Giá đã giảm mạnh gần đây; chưa chắc đã dừng giảm."
    return "Bình thường", "muted", "Đà tăng/giảm gần đây ở mức thông thường."


def activity(ratio: Optional[float], partial: bool = False) -> Tuple[str, str, str]:
    if partial:
        return "Đang cập nhật", "muted", "Phiên hôm nay chưa đóng cửa nên chưa so sánh được khối lượng."
    if ratio is None or ratio != ratio:
        return "—", "muted", ""
    if ratio >= 1.5:
        return "Sôi động", "info", "Khối lượng giao dịch cao hơn hẳn mức bình thường."
    if ratio < 0.6:
        return "Ế ẩm", "muted", "Khối lượng thấp hơn nhiều so với bình thường."
    return "Bình thường", "muted", "Khối lượng giao dịch ở mức thông thường."


def risk_level(stop_pct: Optional[float]) -> Tuple[str, str]:
    """Biên cắt lỗ càng rộng thì mỗi cổ phiếu càng 'dao động mạnh'."""
    if stop_pct is None:
        return "—", "muted"
    if stop_pct < 0.04:
        return "Biến động nhẹ", "up"
    if stop_pct < 0.07:
        return "Biến động vừa", "flat"
    return "Biến động mạnh", "down"


def plain_summary(symbol: str, s: dict) -> str:
    """Một đoạn văn ngắn cho người không biết gì về chứng khoán. Chỉ mô tả hiện trạng, không khuyên mua/bán."""
    t_label, t_kind, _ = trend(s.get("score"))
    parts = []
    if s.get("score") is None:
        return f"{symbol}: chưa đủ dữ liệu lịch sử để đánh giá."
    parts.append({"up": f"{symbol} đang trong xu hướng tăng.",
                  "flat": f"{symbol} đang đi ngang, chưa có xu hướng rõ.",
                  "down": f"{symbol} đang trong xu hướng giảm."}[t_kind])
    h_label, _, _ = heat(s.get("rsi"))
    if h_label == "Tăng nóng":
        parts.append("Giá đã tăng khá nhanh gần đây nên có thể sẽ nghỉ hoặc điều chỉnh.")
    elif h_label == "Giảm sâu":
        parts.append("Giá đã giảm mạnh gần đây, chưa chắc đã dừng giảm.")
    if not s.get("liquid", True):
        parts.append("Mã này ít người giao dịch, có thể khó bán khi bạn cần.")
    if s.get("stop") and s.get("stop_pct") is not None:
        parts.append(f"Nếu bạn quyết định mua, nên đặt sẵn mức bán để tránh lỗ nặng quanh {vnd(s['stop'])} "
                     f"(thấp hơn giá hiện tại {pct(s['stop_pct'], 1, signed=False)}).")
    parts.append("Đây chỉ là mô tả tình hình hiện tại, không phải lời khuyên mua hay bán.")
    return " ".join(parts)


import re  # noqa: E402

_RULES = [  # (regex, mẫu thay thế, '+' thuận lợi / '-' cần lưu ý)
    (r"^Giá trên MA50", "Giá đang cao hơn mức trung bình 50 phiên gần nhất", "+"),
    (r"^Giá dưới MA50", "Giá đang thấp hơn mức trung bình 50 phiên gần nhất", "-"),
    (r"^Giá trên MA200", "Giá cao hơn mức trung bình 200 phiên (xu hướng dài hạn tốt)", "+"),
    (r"^Giá dưới MA200", "Giá thấp hơn mức trung bình 200 phiên (xu hướng dài hạn yếu)", "-"),
    (r"^MA20 trên MA50", "Xu hướng ngắn hạn đang mạnh hơn xu hướng trung hạn", "+"),
    (r"^RSI [\d.]+: động lượng tốt", "Đà tăng tốt và chưa quá nóng", "+"),
    (r"^MACD histogram dương", "Đà tăng ngắn hạn đang mạnh lên", "+"),
    (r"^Tăng giá kèm khối lượng", "Giá tăng cùng lượng giao dịch cao hơn bình thường", "+"),
    (r"^Mạnh hơn VN-Index ([\d.]+)%", r"Tăng tốt hơn thị trường chung (hơn \1% trong khoảng 3 tháng)", "+"),
    (r"^Yếu hơn VN-Index ([\d.]+)%", r"Kém hơn thị trường chung (kém \1% trong khoảng 3 tháng)", "-"),
    (r"^RSI [\d.]+: quá mua", "Giá đã tăng nóng, dễ có nhịp điều chỉnh", "-"),
    (r"^RSI [\d.]+: yếu/quá bán", "Giá đã giảm sâu nhưng chưa có dấu hiệu quay đầu", "-"),
    (r"^Giảm giá kèm khối lượng", "Giá giảm cùng lượng giao dịch lớn (đang bị bán mạnh)", "-"),
    (r"^Thanh khoản thấp \(~([\d.]+) tỷ", r"Ít người giao dịch (~\1 tỷ đồng/phiên), có thể khó bán khi cần", "-"),
]


def plainify(text: str) -> Tuple[str, str]:
    """Dịch một lý do/cảnh báo kỹ thuật sang lời thường. Trả về (câu, '+' hoặc '-')."""
    for pat, repl, pol in _RULES:
        if re.search(pat, text):
            out = re.sub(pat + r".*", repl, text, flags=re.S)
            return re.sub(r"(\d)\.(\d)", r"\1,\2", out), pol
    return text, "-"
