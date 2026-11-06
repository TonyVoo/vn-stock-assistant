"""Kiểm tra sức khoẻ dữ liệu khi mở app: tìm chỗ dữ liệu cũ, thiếu hoặc không khớp nhau để bạn sửa sớm.

Chỉ nêu điều có thể đo được từ dữ liệu của bạn; mỗi mục có hướng xử lý và trang để đi tới. Không có vấn đề thì trả về danh sách rỗng.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

LEVEL_RANK = {"warn": 0, "info": 1}
STALE_BDAYS_WARN = 3     # giá cũ từ 3 phiên trở lên: cảnh báo
STALE_BDAYS_INFO = 2
PORTFOLIO_OLD_DAYS = 7
BACKUP_OLD_DAYS = 3


def _item(level: str, title: str, detail: str, page: str) -> Dict:
    return {"level": level, "title": title, "detail": detail, "page": page}


def check(today: date, holdings: List[Dict], pf_cash: float, pf_as_of: Optional[str], open_trades: Optional[pd.DataFrame],
          price_dates: Dict[str, Optional[date]], has_flows: bool, capital: float, pf_total: float,
          last_backup_age_days: Optional[float], has_data: bool = True) -> List[Dict]:
    """price_dates: {mã: ngày giá mới nhất hoặc None nếu chưa có dữ liệu giá thật}."""
    out: List[Dict] = []
    held = {h["symbol"]: h for h in holdings}

    missing = [s for s in held if price_dates.get(s) is None]
    if missing:
        out.append(_item("warn", "Chưa có giá của " + ", ".join(missing),
                         "Danh mục đang tạm tính các mã này theo giá vốn. Bấm Cập nhật giá ở trang Tổng quan.", "settings"))
    dates = [d for s, d in price_dates.items() if d is not None and s in held]
    if dates:
        gap = int(np.busday_count(min(dates), today))
        if gap >= STALE_BDAYS_WARN:
            out.append(_item("warn", f"Giá đã cũ {gap} phiên", f"Giá của các mã bạn giữ mới nhất là ngày {min(dates):%d/%m/%Y}. Bấm Cập nhật giá để các con số theo kịp thị trường.", "settings"))
        elif gap >= STALE_BDAYS_INFO:
            out.append(_item("info", f"Giá chưa cập nhật {gap} phiên", f"Giá mới nhất là ngày {min(dates):%d/%m/%Y}.", "settings"))

    if pf_as_of and held:
        try:
            age = (today - pd.Timestamp(pf_as_of).date()).days
            if age >= PORTFOLIO_OLD_DAYS:
                out.append(_item("info", f"Danh mục cập nhật cách đây {age} ngày", "Nếu bạn đã mua hoặc bán thêm, hãy cập nhật lại Danh mục.", "portfolio"))
        except (ValueError, TypeError):
            pass

    if held and pf_cash <= 0 and has_flows:
        out.append(_item("warn", "Danh mục chưa ghi tiền mặt", "Bạn đã ghi tiền nạp/rút nhưng tiền mặt trong Danh mục là 0đ, nên lãi thật và so sánh với VN-Index có thể sai. Ghi tiền mặt ở tab “Nhập tay”.", "portfolio"))

    jq = open_trades.groupby("symbol")["qty"].sum().to_dict() if open_trades is not None and len(open_trades) else {}
    for sym, q in sorted(jq.items()):
        if sym in held:
            if abs(float(held[sym]["qty"]) - float(q)) > 0.5:
                out.append(_item("warn", f"{sym}: Danh mục và Nhật ký lệch số lượng",
                                 f"Danh mục ghi {held[sym]['qty']:,.0f} cổ phiếu, các lệnh đang mở trong Nhật ký cộng lại là {q:,.0f}. Một trong hai chưa cập nhật.".replace(",", "."), "journal"))
        else:
            out.append(_item("info", f"{sym}: có lệnh mở trong Nhật ký nhưng Danh mục không có mã này",
                             "Nếu bạn đã bán, hãy đóng lệnh trong Nhật ký; nếu chưa, hãy cập nhật Danh mục.", "journal"))
    for sym in sorted(set(held) - set(jq)):
        out.append(_item("info", f"{sym}: có trong Danh mục nhưng chưa có trong Nhật ký", "Thêm vào Nhật ký để theo dõi cắt lỗ, mục tiêu và ghi lý do mua.", "journal"))

    if capital and pf_total and capital + 1 < pf_total:
        out.append(_item("info", "Vốn ở Cài đặt nhỏ hơn giá trị Danh mục",
                         f"Vốn bạn đặt là {capital / 1e6:,.1f} triệu nhưng Danh mục đã ghi {pf_total / 1e6:,.1f} triệu, nên các tỷ lệ % đang tính theo số đã ghi. Cập nhật vốn nếu cần.", "settings"))

    if has_data and (last_backup_age_days is None or last_backup_age_days >= BACKUP_OLD_DAYS):
        out.append(_item("info", "Chưa có bản sao lưu gần đây", "Mở trang Cài đặt và tải một bản sao lưu về cất ở nơi khác.", "settings"))
    return sorted(out, key=lambda x: LEVEL_RANK[x["level"]])
