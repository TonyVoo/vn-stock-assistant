"""Theo dõi cổ tức: tiền mặt và cổ phiếu thưởng. Dữ liệu nằm trong data/dividends.db (chỉ trên máy bạn).

Mỗi ghi chép có thể được ÁP DỤNG vào Danh mục:
- Cổ tức tiền mặt: cộng vào tiền mặt trong Danh mục, nên tổng tài sản và LÃI THẬT đã gồm khoản này.
- Cổ phiếu thưởng: tăng số lượng; giá vốn bình quân giảm tương ứng (tổng giá vốn giữ nguyên, vì cổ phiếu thưởng không tốn tiền).
Việc kiểm tra và áp dụng làm TRƯỚC khi ghi, nên không bao giờ ghi một nửa (có ghi chép mà Danh mục không đổi, hoặc ngược lại).
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from . import portfolio

DB_PATH = Path(os.getenv("DIVIDEND_PATH") or Path(__file__).resolve().parent.parent / "data" / "dividends.db")
CASH, BONUS = "tien", "co_phieu"
LABEL = {CASH: "Cổ tức tiền mặt", BONUS: "Cổ phiếu thưởng"}
_SYM = re.compile(r"^[A-Z0-9]{2,6}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS dividends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    applied INTEGER NOT NULL DEFAULT 0
)
"""


def _conn(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def _validate(day, symbol: str, kind: str, amount: float):
    d = pd.Timestamp(day).date()
    if d > date.today():
        raise ValueError("Ngày không được ở tương lai.")
    sym = str(symbol).upper().strip()
    if not _SYM.match(sym):
        raise ValueError("Mã cổ phiếu không hợp lệ.")
    if kind not in LABEL:
        raise ValueError("Loại phải là cổ tức tiền mặt hoặc cổ phiếu thưởng.")
    a = float(amount)
    if not math.isfinite(a) or a <= 0 or a > 1e13:
        raise ValueError("Số tiền/số cổ phiếu phải lớn hơn 0.")
    if kind == BONUS and a != int(a):
        raise ValueError("Số cổ phiếu thưởng phải là số nguyên.")
    return d, sym, a


def _apply(pf: Dict, sym: str, kind: str, amount: float) -> Dict:
    """Trả về danh mục mới sau khi áp dụng (KHÔNG ghi). Lỗi nếu không thể áp dụng."""
    holdings = [dict(h) for h in pf["holdings"]]
    if kind == CASH:
        return {"holdings": holdings, "cash": pf["cash"] + amount}
    for h in holdings:
        if h["symbol"] == sym:
            total_cost = h["avg_cost"] * h["qty"]
            h["qty"] = h["qty"] + int(amount)
            h["avg_cost"] = total_cost / h["qty"]
            h["market_value"] = None  # giá trị TCBS báo trước đó không còn đúng với số lượng mới
            return {"holdings": holdings, "cash": pf["cash"]}
    raise ValueError(f"Danh mục chưa có {sym} nên không thể cộng cổ phiếu thưởng. Hãy thêm mã này vào Danh mục trước, hoặc bỏ chọn “Cập nhật Danh mục”.")


def add(day, symbol: str, kind: str, amount: float, note: str = "", apply_to_portfolio: bool = False,
        path: Optional[Path] = None, pf_path: Optional[Path] = None) -> int:
    d, sym, a = _validate(day, symbol, kind, amount)
    if apply_to_portfolio:
        pf = portfolio.load(pf_path)
        new_pf = _apply(pf, sym, kind, a)  # lỗi thì dừng ở đây, chưa ghi gì
        portfolio.save(new_pf, pf.get("source") or "manual", pf_path)
    with _conn(path) as c:
        cur = c.execute("INSERT INTO dividends(day, symbol, kind, amount, note, applied) VALUES (?,?,?,?,?,?)",
                        (d.isoformat(), sym, kind, a, (note or "").strip()[:200], int(bool(apply_to_portfolio))))
        return int(cur.lastrowid)


def delete(div_id: int, path: Optional[Path] = None) -> None:
    """Xoá ghi chép. KHÔNG hoàn lại thay đổi đã áp dụng vào Danh mục (giao diện có cảnh báo)."""
    with _conn(path) as c:
        c.execute("DELETE FROM dividends WHERE id=?", (int(div_id),))


def list_all(path: Optional[Path] = None) -> pd.DataFrame:
    with _conn(path) as c:
        df = pd.read_sql_query("SELECT * FROM dividends ORDER BY day DESC, id DESC", c)
    if not df.empty:
        df["day"] = pd.to_datetime(df["day"])
    return df


def summary(df: pd.DataFrame, holdings_cost: float = 0.0, today: Optional[date] = None) -> Dict:
    """Tổng cổ tức tiền mặt (tất cả, 12 tháng gần nhất), cổ tức đã cộng vào tiền mặt Danh mục, tỷ suất trên giá vốn."""
    today = today or date.today()
    if df is None or df.empty:
        return {"n": 0, "cash_total": 0.0, "cash_12m": 0.0, "cash_applied": 0.0, "yield_on_cost": None, "bonus_total": 0, "by_symbol": pd.DataFrame()}
    cash = df[df["kind"] == CASH]
    last12 = cash[cash["day"] >= pd.Timestamp(today) - pd.Timedelta(days=365)]
    by = (df.assign(cash=df["amount"].where(df["kind"] == CASH, 0.0), shares=df["amount"].where(df["kind"] == BONUS, 0.0))
          .groupby("symbol", as_index=False)[["cash", "shares"]].sum().sort_values("cash", ascending=False))
    return {"n": int(len(df)), "cash_total": float(cash["amount"].sum()), "cash_12m": float(last12["amount"].sum()),
            "cash_applied": float(cash.loc[cash["applied"] == 1, "amount"].sum()),
            "yield_on_cost": (float(last12["amount"].sum()) / holdings_cost) if holdings_cost > 0 else None,
            "bonus_total": int(df.loc[df["kind"] == BONUS, "amount"].sum()), "by_symbol": by}
