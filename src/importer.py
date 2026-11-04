"""Nhập lịch sử giao dịch (sao kê) vào Nhật ký giao dịch: ghép lệnh mua với lệnh bán theo nguyên tắc vào trước ra trước (FIFO).

Mỗi lô mua thành một lệnh trong Nhật ký. Lô đã bán (một phần hoặc hết) thành lệnh đã chốt với giá bán, phần còn lại là lệnh đang giữ.
Mức cắt lỗ chưa biết nên để 0 (= “chưa đặt”). Mỗi lệnh có khoá nhận diện trong cột lý do để nhập lại cùng file không bị trùng.
Phí và thuế KHÔNG có trong sao kê lệnh khớp; app trừ phí/thuế ước tính khi tính lãi/lỗ.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import journal

UNKNOWN_DATE = "Không rõ"


def _d(when) -> str:
    return pd.Timestamp(when).date().isoformat() if pd.notna(when) else UNKNOWN_DATE


def _key(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:10]


def fifo_trades(tx: List[tuple]) -> Tuple[List[Dict], List[str]]:
    """tx: [(ngày, thứ tự, mã, chiều, khối lượng, giá)] đã sắp theo thời gian. Trả về (danh sách lệnh, ghi chú)."""
    notes: List[str] = []
    lots: Dict[str, deque] = defaultdict(deque)
    seen: Dict[tuple, int] = defaultdict(int)
    out: List[Dict] = []
    oversold = set()
    for when, _, sym, side, qty, price in tx:
        qty = int(round(qty))
        if side > 0:
            ident = (sym, _d(when), price, qty)
            seen[ident] += 1  # phân biệt hai lệnh giống hệt nhau trong cùng ngày
            lots[sym].append({"sym": sym, "date": _d(when), "price": price, "qty": qty, "ident": ident, "n": seen[ident], "pieces": 0})
            continue
        left = qty
        while left > 0 and lots[sym]:
            lot = lots[sym][0]
            take = min(left, lot["qty"])
            lot["pieces"] += 1
            out.append({"symbol": sym, "qty": take, "entry": lot["price"], "opened": lot["date"], "exit": price, "closed": _d(when),
                        "key": _key("closed", *lot["ident"], lot["n"], lot["pieces"], _d(when), price, take)})
            lot["qty"] -= take
            left -= take
            if lot["qty"] == 0:
                lots[sym].popleft()
        if left > 0:
            oversold.add(sym)
    for sym, q in lots.items():
        for lot in q:
            out.append({"symbol": sym, "qty": lot["qty"], "entry": lot["price"], "opened": lot["date"], "exit": None, "closed": None,
                        "key": _key("open", *lot["ident"], lot["n"], lot["pieces"], lot["qty"])})
    if oversold:
        notes.append("Bán nhiều hơn số đã mua ở " + ", ".join(sorted(oversold)) + ": file thiếu lịch sử mua trước đó, phần bán dư bị bỏ qua.")
    out.sort(key=lambda t: (t["opened"] == UNKNOWN_DATE, t["opened"], t["symbol"]))
    return out, notes


def open_symbols(path: Optional[Path] = None) -> set:
    """Các mã đã có lệnh ĐANG GIỮ trong Nhật ký (kể cả lệnh bạn tự ghi)."""
    t = journal.list_trades(path)
    return set() if t.empty else set(t[t["exit_price"].isna()]["symbol"])


def holdings_to_trades(rows: List[Dict], skip_symbols=()) -> List[Dict]:
    """File danh mục đang giữ -> các lệnh đang giữ (giá mua = giá vốn bình quân, ngày mua không rõ).
    Bỏ qua mã đã có lệnh đang giữ trong Nhật ký để không ghi đôi."""
    out = []
    for h in rows:
        if h["symbol"] in skip_symbols:
            continue
        if h["avg_cost"] and h["avg_cost"] > 0 and h["qty"] > 0:
            out.append({"symbol": h["symbol"], "qty": int(round(h["qty"])), "entry": h["avg_cost"], "opened": UNKNOWN_DATE,
                        "exit": None, "closed": None, "key": _key("holding", h["symbol"], int(round(h["qty"])), round(h["avg_cost"]))})
    return out


def preview(trades: List[Dict], path: Optional[Path] = None) -> Dict:
    have = journal.import_keys(path)
    new = [t for t in trades if t["key"] not in have]
    return {"total": len(trades), "new": len(new), "skipped": len(trades) - len(new),
            "open": sum(1 for t in new if t["exit"] is None), "closed": sum(1 for t in new if t["exit"] is not None)}


def to_journal(trades: List[Dict], path: Optional[Path] = None) -> Dict:
    """Ghi vào Nhật ký, bỏ qua lệnh đã nhập trước đó. Trả về thống kê."""
    have = journal.import_keys(path)
    added_open = added_closed = 0
    for t in trades:
        if t["key"] in have or t["qty"] <= 0 or t["entry"] <= 0:
            continue
        reason = f"[sao kê {t['key']}] Nhập từ sao kê giao dịch (chưa ghi lý do mua)"
        tid = journal.add_trade(t["symbol"], t["qty"], float(t["entry"]), 0.0, None, reason, t["opened"], path)
        if t["exit"] is not None:
            journal.close_trade(tid, float(t["exit"]), t["closed"], "Nhập từ sao kê", path)
            added_closed += 1
        else:
            added_open += 1
        have.add(t["key"])
    return {"open": added_open, "closed": added_closed}
