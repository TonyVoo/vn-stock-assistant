"""Tiền nạp/rút: để tách LÃI THẬT do đầu tư khỏi phần tiền bạn bỏ thêm vào.

Quy ước: số tiền dương = nạp vào tài khoản đầu tư, số tiền âm = rút ra. Dữ liệu nằm trong data/cashflows.db (chỉ trên máy bạn).

Lãi thật = tổng tài sản hiện tại (cổ phiếu + tiền mặt) − tiền ròng đã bỏ vào (nạp − rút).
Tỷ suất quy năm (XIRR) có tính NGÀY của từng lần nạp/rút: nạp sớm thì được tính thời gian dài hơn. Chỉ hiển thị khi đã đủ dài
(>= 60 ngày), vì quy năm một khoảng ngắn cho con số rất lệch.
"""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

DB_PATH = Path(os.getenv("CASHFLOW_PATH") or Path(__file__).resolve().parent.parent / "data" / "cashflows.db")
MIN_DAYS_FOR_ANNUAL = 60
SCHEMA = """
CREATE TABLE IF NOT EXISTS flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT
)
"""


def _conn(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def add(day, amount: float, note: str = "", path: Optional[Path] = None) -> int:
    d = pd.Timestamp(day).date()
    if d > date.today():
        raise ValueError("Ngày không được ở tương lai.")
    a = float(amount)
    if not math.isfinite(a) or a == 0 or abs(a) > 1e13:
        raise ValueError("Số tiền phải khác 0 và hợp lệ.")
    with _conn(path) as c:
        cur = c.execute("INSERT INTO flows(day, amount, note) VALUES (?,?,?)", (d.isoformat(), a, (note or "").strip()[:200]))
        return int(cur.lastrowid)


def delete(flow_id: int, path: Optional[Path] = None) -> None:
    with _conn(path) as c:
        c.execute("DELETE FROM flows WHERE id=?", (int(flow_id),))


def list_flows(path: Optional[Path] = None) -> pd.DataFrame:
    with _conn(path) as c:
        df = pd.read_sql_query("SELECT * FROM flows ORDER BY day, id", c)
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df


def xirr(flows: List[tuple], value_now: float, as_of: date) -> Optional[float]:
    """Tỷ suất quy năm. flows: [(ngày, số tiền)] dương = nạp. Giá trị hiện tại coi như rút hết vào ngày as_of.
    Trả về None nếu không giải được (ví dụ chưa có nạp tiền, hoặc không có nghiệm hợp lý)."""
    if not flows:
        return None
    d0 = min(d for d, _ in flows)
    cfs = [(((d - d0).days) / 365.0, -a) for d, a in flows] + [(((as_of - d0).days) / 365.0, value_now)]

    def f(r: float) -> float:
        return sum(cf / (1.0 + r) ** t for t, cf in cfs)

    lo, hi = -0.99, 50.0
    flo, fhi = f(lo), f(hi)
    if not (math.isfinite(flo) and math.isfinite(fhi)) or flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def summary(flows: pd.DataFrame, value_now: float, as_of: Optional[date] = None) -> Dict:
    as_of = as_of or date.today()
    if flows is None or flows.empty:
        return {"n": 0}
    dep = float(flows.loc[flows["amount"] > 0, "amount"].sum())
    wd = abs(float(flows.loc[flows["amount"] < 0, "amount"].sum()))  # abs: tránh “-0.0” khi chưa rút đồng nào
    net = dep - wd
    pnl = value_now - net
    first = flows["day"].min().date()
    days = (as_of - first).days
    annual = None
    if days >= MIN_DAYS_FOR_ANNUAL:
        annual = xirr([(d.date(), float(a)) for d, a in zip(flows["day"], flows["amount"])], value_now, as_of)
    return {"n": int(len(flows)), "deposited": dep, "withdrawn": wd, "net_in": net, "value": value_now, "pnl": pnl,
            "pnl_pct": (pnl / net) if net > 0 else None, "first_day": first, "days": days, "annual": annual}
