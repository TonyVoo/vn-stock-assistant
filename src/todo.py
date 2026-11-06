"""“Hôm nay bạn cần làm gì”: tối đa 3 việc, xếp theo mức khẩn, viết bằng tiếng thường. Không có việc thì nói thẳng là không cần làm gì."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

from . import journal

MAX_ITEMS = 3
STALE_DAYS = 3


def build(alert_items: List[Dict], open_trades: Optional[pd.DataFrame], last_data: Optional[date], today: date,
          valuation_summary: Optional[Dict], weights: Optional[Dict[str, float]], max_alloc: float, has_holdings: bool,
          has_cashflow: bool, market_closed_now: bool = False) -> List[Dict]:
    """Mỗi việc: {level: bad|warn|info, title, detail, page}. page là khoá trang để bấm đi tới."""
    out: List[Dict] = []
    for a in alert_items:
        if a["kind"] in ("hit_stop", "near_stop"):
            out.append({"level": "bad" if a["kind"] == "hit_stop" else "warn", "title": f"{a['symbol']}: " + ("đã chạm mức cắt lỗ" if a["kind"] == "hit_stop" else "sắp chạm mức cắt lỗ"),
                        "detail": a["message"], "page": "journal"})
        elif a["kind"] == "hit_target":
            out.append({"level": "info", "title": f"{a['symbol']}: đã đạt giá mục tiêu", "detail": a["message"], "page": "journal"})
    if open_trades is not None and not open_trades.empty:
        no_stop = list(open_trades.loc[open_trades["stop"].fillna(0) <= 0, "symbol"])
        if no_stop:
            out.append({"level": "warn", "title": "Đặt mức cắt lỗ cho " + ", ".join(dict.fromkeys(no_stop)),
                        "detail": "Chưa có mức cắt lỗ thì không biết mình có thể mất tối đa bao nhiêu. Vào Nhật ký giao dịch, sửa lệnh và nhập giá cắt lỗ.", "page": "journal"})
        reasons = open_trades["reason"].fillna("").astype(str)
        no_reason = list(open_trades.loc[reasons.str.replace(r"^\[sao kê [0-9a-f]{10}\]\s*", "", regex=True).str.strip().isin(["", journal.PLACEHOLDER_REASON]), "symbol"])
        if no_reason:
            out.append({"level": "info", "title": "Ghi lý do mua cho " + ", ".join(dict.fromkeys(no_reason)),
                        "detail": "Biết vì sao mình mua giúp bạn quyết định đúng khi giá biến động và học được từ lệnh sau này.", "page": "journal"})
    if last_data is not None:
        gap = (today - last_data).days
        if gap >= STALE_DAYS or (market_closed_now and today.weekday() < 5 and last_data < today):
            out.append({"level": "info", "title": "Cập nhật giá",
                        "detail": f"Dữ liệu giá mới nhất là ngày {last_data:%d/%m/%Y}. Bấm “Cập nhật giá” để mọi con số theo kịp thị trường.", "page": "settings"})
    if has_holdings and weights:
        top = max(weights.items(), key=lambda kv: kv[1])
        if top[1] > max_alloc:
            out.append({"level": "warn", "title": f"{top[0]} đang chiếm quá nhiều",
                        "detail": f"{top[0]} chiếm {top[1] * 100:.0f}% tổng tài sản, vượt mức {max_alloc * 100:.0f}% bạn đặt. Cân nhắc không mua thêm mã này.", "page": "portfolio"})
    if valuation_summary and has_holdings and valuation_summary.get("total"):
        base = valuation_summary.get("base") or valuation_summary["total"]
        if (valuation_summary["cash"] + valuation_summary.get("assumed_cash", 0.0)) / base < 0.05:
            out.append({"level": "warn", "title": "Tiền mặt dự phòng gần hết",
                        "detail": "Tiền mặt dưới 5% tổng tài sản: gần như không còn chỗ xoay xở khi giá giảm.", "page": "portfolio"})
    if has_holdings and not has_cashflow:
        out.append({"level": "info", "title": "Ghi số tiền bạn đã bỏ vào",
                    "detail": "Có ghi tiền nạp/rút thì app mới tính được lãi thật và so được với VN-Index.", "page": "portfolio"})
    rank = {"bad": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda x: rank[x["level"]])[:MAX_ITEMS]
