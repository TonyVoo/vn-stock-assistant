"""Nhật ký giao dịch (SQLite). Dữ liệu nằm trong data/journal.db, chỉ trên máy bạn."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

DB_PATH = Path(os.getenv("JOURNAL_PATH") or Path(__file__).resolve().parent.parent / "data" / "journal.db")
_IMPORT_KEY = re.compile(r"\[sao kê ([0-9a-f]{10})\]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty INTEGER NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL,
    reason TEXT,
    closed TEXT,
    exit_price REAL,
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


def add_trade(symbol: str, qty: int, entry: float, stop: float, target: Optional[float],
              reason: str, opened: str, path: Optional[Path] = None) -> int:
    if entry <= 0 or qty <= 0 or stop < 0:
        raise ValueError("Giá vào, số lượng phải > 0 và cắt lỗ không âm")
    if stop >= entry:  # stop = 0 nghĩa là “chưa đặt mức cắt lỗ” (dùng cho lệnh nhập từ sao kê)
        raise ValueError("Cắt lỗ phải thấp hơn giá vào")
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO trades(opened,symbol,qty,entry,stop,target,reason) VALUES (?,?,?,?,?,?,?)",
            (opened, symbol.upper(), qty, entry, stop, target, reason))
        return int(cur.lastrowid)


def close_trade(trade_id: int, exit_price: float, closed: str, note: str = "",
                path: Optional[Path] = None) -> None:
    with _conn(path) as c:
        c.execute("UPDATE trades SET closed=?, exit_price=?, note=? WHERE id=?",
                  (closed, exit_price, note, trade_id))


_EDITABLE = {"symbol", "qty", "entry", "stop", "target", "opened", "reason", "closed", "exit_price", "note"}
_SYM_RE = re.compile(r"^[A-Z0-9]{2,6}$")
UNKNOWN_DATE = "Không rõ"
PLACEHOLDER_REASON = "Nhập từ sao kê"


def get_trade(trade_id: int, path: Optional[Path] = None) -> Optional[Dict]:
    with _conn(path) as c:
        r = c.execute("SELECT * FROM trades WHERE id=?", (int(trade_id),)).fetchone()
    return dict(r) if r else None


def _norm_date(v, label: str) -> str:
    s = str(v or "").strip()
    if s.lower() in ("", "không rõ", "khong ro"):
        return UNKNOWN_DATE
    try:
        return pd.Timestamp(s).date().isoformat()
    except (ValueError, TypeError):
        raise ValueError(f"{label} phải có dạng YYYY-MM-DD (ví dụ 2026-11-04) hoặc “Không rõ”.") from None


def update_trade(trade_id: int, path: Optional[Path] = None, **fields) -> None:
    """Sửa một lệnh. Kiểm tra hợp lệ trên toàn bộ lệnh sau khi sửa. Lệnh nhập từ sao kê giữ nguyên khoá nhận diện khi sửa lý do."""
    unknown = set(fields) - _EDITABLE
    if unknown:
        raise ValueError("Không được sửa trường: " + ", ".join(sorted(unknown)))
    cur = get_trade(trade_id, path)
    if cur is None:
        raise ValueError("Không tìm thấy lệnh này.")
    new = {**cur, **fields}
    sym = str(new["symbol"]).upper().strip()
    if not _SYM_RE.match(sym):
        raise ValueError("Mã cổ phiếu không hợp lệ.")
    try:
        qty = int(round(float(new["qty"])))
        entry, stop = float(new["entry"]), float(new["stop"] or 0)
    except (TypeError, ValueError):
        raise ValueError("Số lượng và giá phải là số.") from None
    if qty <= 0 or entry <= 0:
        raise ValueError("Số lượng và giá mua phải lớn hơn 0.")
    if stop < 0:
        raise ValueError("Giá cắt lỗ không được âm (để 0 nếu chưa đặt).")
    # Cho phép cắt lỗ >= giá mua khi SỬA lệnh: giá đã tăng thì kéo cắt lỗ lên trên giá mua để giữ lại lãi (trailing stop).
    target = new["target"]
    target = None if target in (None, 0, 0.0) or (isinstance(target, float) and target != target) else float(target)
    if target is not None and target <= entry:
        raise ValueError("Giá mục tiêu phải cao hơn giá mua (hoặc để 0 nếu bỏ trống).")
    opened = _norm_date(new["opened"], "Ngày mua")
    exit_price, closed = new["exit_price"], new["closed"]
    if exit_price is not None and exit_price == exit_price:
        exit_price = float(exit_price)
        if exit_price <= 0:
            raise ValueError("Giá bán phải lớn hơn 0.")
        closed = _norm_date(closed, "Ngày bán")
        if opened != UNKNOWN_DATE and closed != UNKNOWN_DATE and closed < opened:
            raise ValueError("Ngày bán không được trước ngày mua.")
    else:
        exit_price, closed = None, None
    reason = new["reason"]
    if "reason" in fields:
        text = str(fields["reason"] or "").strip()
        m = _IMPORT_KEY.search(cur["reason"] or "")
        reason = (f"[sao kê {m.group(1)}] " if m else "") + text  # giữ khoá nhận diện để nhập lại file không bị trùng
    with _conn(path) as c:
        c.execute("UPDATE trades SET symbol=?, qty=?, entry=?, stop=?, target=?, opened=?, reason=?, closed=?, exit_price=?, note=? WHERE id=?",
                  (sym, qty, entry, stop, target, opened, reason, closed, exit_price, new["note"], int(trade_id)))


def reopen_trade(trade_id: int, path: Optional[Path] = None) -> None:
    """Mở lại lệnh đã bán (xoá thông tin bán), ví dụ khi bấm bán nhầm."""
    with _conn(path) as c:
        c.execute("UPDATE trades SET closed=NULL, exit_price=NULL, note=NULL WHERE id=?", (int(trade_id),))


def delete_trade(trade_id: int, path: Optional[Path] = None) -> None:
    with _conn(path) as c:
        c.execute("DELETE FROM trades WHERE id=?", (int(trade_id),))


def list_trades(path: Optional[Path] = None) -> pd.DataFrame:
    with _conn(path) as c:
        df = pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", c)
    if df.empty:
        return df
    from .risk import FEE_RATE, SELL_TAX
    closed = df["exit_price"].notna()
    gross = (df["exit_price"] - df["entry"]) * df["qty"]
    costs = df["qty"] * (df["entry"] * FEE_RATE + df["exit_price"] * (FEE_RATE + SELL_TAX))
    df["pnl"] = (gross - costs).where(closed)
    # R chỉ có nghĩa khi đã đặt cắt lỗ VÀ cắt lỗ thấp hơn giá mua (rủi ro dương); cắt lỗ chưa đặt hoặc đã kéo lên trên giá mua -> không tính R
    risk = ((df["entry"] - df["stop"]) * df["qty"]).where((df["stop"] > 0) & (df["stop"] < df["entry"]))
    df["r_multiple"] = (df["pnl"] / risk).where(closed)
    return df


def stats(df: pd.DataFrame) -> Dict:
    done = df[df["pnl"].notna()] if not df.empty else df
    if done is None or done.empty:
        return {"closed": 0}
    wins = done[done["pnl"] > 0]
    return {
        "closed": int(len(done)),
        "win_rate": float(len(wins) / len(done)),
        "total_pnl": float(done["pnl"].sum()),
        "avg_r": (None if done["r_multiple"].notna().sum() == 0 else float(done["r_multiple"].mean())),
    }


def import_keys(path: Optional[Path] = None) -> set:
    """Các khoá lệnh đã nhập từ sao kê (để không nhập trùng)."""
    with _conn(path) as c:
        rows = c.execute("SELECT reason FROM trades WHERE reason LIKE '%[sao kê %'").fetchall()
    return {m.group(1) for r in rows for m in [_IMPORT_KEY.search(r["reason"] or "")] if m}
