"""So sánh kết quả của bạn với VN-Index theo cách công bằng: "nếu cùng các khoản nạp/rút đó được bỏ vào VN-Index vào đúng ngày thì giờ có bao nhiêu?".

Mô phỏng chỉ số: mua/bán "đơn vị chỉ số" theo giá đóng cửa của ngày đó (hoặc phiên gần nhất trước đó). Không tính phí, thuế và cổ tức của chỉ số,
nên đây là mốc so sánh lý tưởng; thực tế người mua quỹ chỉ số còn chịu phí. Cần dữ liệu Tiền nạp/rút (để biết bạn bỏ tiền vào lúc nào).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

import pandas as pd


def compare(flows: pd.DataFrame, value_now: float, index_df: pd.DataFrame, as_of: Optional[date] = None) -> Dict:
    if flows is None or flows.empty:
        return {"ok": False, "reason": "Chưa có ghi chép tiền nạp/rút nên chưa so sánh được. Hãy ghi các lần nạp tiền ở mục Tiền nạp/rút."}
    if index_df is None or index_df.empty:
        return {"ok": False, "reason": "Chưa có dữ liệu VN-Index. Hãy bấm Cập nhật giá."}
    idx = index_df.assign(date=pd.to_datetime(index_df["date"]).dt.normalize()).sort_values("date").set_index("date")["close"]
    first = flows["day"].min().normalize()
    if first < idx.index.min():
        return {"ok": False, "reason": f"Dữ liệu VN-Index chỉ bắt đầu từ {idx.index.min():%d/%m/%Y}, sau lần nạp tiền đầu tiên ({first:%d/%m/%Y})."}
    last_day, last_close = idx.index.max(), float(idx.iloc[-1])
    units = 0.0
    for d, a in zip(flows["day"], flows["amount"]):
        price = float(idx.loc[:pd.Timestamp(d).normalize()].iloc[-1])
        units += float(a) / price
    index_value = units * last_close
    net_in = float(flows["amount"].sum())
    if net_in <= 0:
        return {"ok": False, "reason": "Tiền ròng đã bỏ vào không dương nên không so sánh được."}
    first_close = float(idx.loc[:first].iloc[-1])
    return {"ok": True, "your_value": float(value_now), "index_value": float(index_value), "net_in": net_in,
            "your_return": value_now / net_in - 1, "index_return": index_value / net_in - 1,
            "diff": float(value_now - index_value), "ahead": value_now >= index_value, "first_day": first, "index_as_of": last_day,
            "index_change": last_close / first_close - 1}
