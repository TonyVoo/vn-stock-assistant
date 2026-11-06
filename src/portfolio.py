"""Danh mục đang nắm giữ: lưu trên máy, nhập từ file/nhật ký/TCBS (chỉ đọc), định giá và cảnh báo tập trung.

Dữ liệu nằm trong data/portfolio.json (chỉ trên máy bạn). Giá đơn vị luôn là đồng/cổ phiếu.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .risk import FEE_RATE, SELL_TAX

PATH = Path(os.getenv("PORTFOLIO_PATH") or Path(__file__).resolve().parent.parent / "data" / "portfolio.json")
_SYM = re.compile(r"^[A-Z0-9]{2,6}$")
EMPTY = {"holdings": [], "cash": 0.0, "source": None, "as_of": None}


# ---------------------------------------------------------------- lưu / nạp
def clean_holdings(rows: List[Dict]) -> List[Dict]:
    """Chuẩn hoá: mã hợp lệ, số lượng nguyên > 0, giá vốn >= 0; gộp mã trùng (giá vốn bình quân gia quyền)."""
    acc: Dict[str, Dict] = {}
    for r in rows or []:
        sym = str(r.get("symbol", "")).upper().strip()
        try:
            qty = int(round(float(r.get("qty", 0))))
            avg = float(r.get("avg_cost", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not _SYM.match(sym) or qty <= 0 or avg < 0 or not np.isfinite(avg):
            continue
        mv = r.get("market_value")
        mv = float(mv) if mv not in (None, "") and np.isfinite(float(mv)) else None
        if sym in acc:
            a = acc[sym]
            tot = a["qty"] + qty
            a["avg_cost"] = (a["avg_cost"] * a["qty"] + avg * qty) / tot
            a["qty"] = tot
            a["market_value"] = (a["market_value"] or 0) + mv if (mv is not None and a["market_value"] is not None) else None
        else:
            acc[sym] = {"symbol": sym, "qty": qty, "avg_cost": avg, "market_value": mv}
    return sorted(acc.values(), key=lambda h: h["symbol"])


def clean(pf: Dict) -> Dict:
    try:
        cash = max(float(pf.get("cash", 0) or 0), 0.0)
    except (TypeError, ValueError):
        cash = 0.0
    return {"holdings": clean_holdings(pf.get("holdings", [])), "cash": cash,
            "source": pf.get("source"), "as_of": pf.get("as_of")}


def load(path: Optional[Path] = None) -> Dict:
    try:
        return clean(json.loads(Path(path or PATH).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return dict(EMPTY)


def save(pf: Dict, source: str, path: Optional[Path] = None) -> Dict:
    p = Path(path or PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = clean(pf)
    data["source"] = source
    data["as_of"] = datetime.now().isoformat(timespec="seconds")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)  # ghi nguyên tử
    return data


# ---------------------------------------------------------------- từ nhật ký
def from_journal(trades: pd.DataFrame) -> List[Dict]:
    """Các lệnh chưa bán trong nhật ký -> danh mục (giá vốn = giá mua)."""
    if trades is None or trades.empty:
        return []
    op = trades[trades["exit_price"].isna()]
    return clean_holdings([{"symbol": t.symbol, "qty": t.qty, "avg_cost": t.entry} for t in op.itertuples()])


# ---------------------------------------------------------------- nhập từ file
def _fold(s: str) -> str:
    """Bỏ dấu, chữ thường, bỏ phần trong ngoặc (đơn vị như “(đ)”, “(VND)”, “(nghìn đồng)”)."""
    s = re.sub(r"[\(\[].*?[\)\]]", " ", str(s))
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


SYNONYMS = {
    "symbol": {"ma ck", "ma", "symbol", "ticker", "ma chung khoan", "ma cp", "cp", "stock"},
    "qty": {"khoi luong", "so luong", "sl", "quantity", "qty", "tong kl", "kl", "khoi luong nam giu", "so cp"},
    "avg_cost": {"gia von", "gia mua", "gia von tb", "gia von trung binh", "avgprice", "avg price", "gia binh quan",
                 "gia tb", "avg cost", "gia mua tb", "gia von binh quan", "gia mua binh quan", "gia von hien tai"},
}


def to_number(x) -> Optional[float]:
    """Đọc số kiểu Việt (1.234.567,5) hoặc kiểu Anh (1,234,567.5); trả None nếu không đọc được."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = re.sub(r"[\sđ%]", "", str(x).replace("VND", "").replace("vnd", ""))
    if not s:
        return None
    try:
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):
            return float(s.replace(".", "").replace(",", "."))
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
            return float(s.replace(",", ""))
        if "," in s and "." not in s:
            return float(s.replace(",", ".")) if re.fullmatch(r"-?\d+,\d{1,2}", s) else float(s.replace(",", ""))
        return float(s)
    except ValueError:
        return None


def _fuzzy_rank(f: str, key: str) -> Optional[int]:
    """Khớp gần đúng tên cột đã bỏ dấu. Số nhỏ = ưu tiên hơn; None = không khớp."""
    if key == "symbol":
        if any(w in f for w in ("tai khoan", "luu ky", "lenh", "ten ")):
            return None
        return 0 if (f in ("ck", "ma", "cp") or f.startswith("ma ") or f.endswith(" ma") or "chung khoan" in f) else None
    if key == "qty":
        if not (any(w in f for w in ("khoi luong", "so luong", "tong kl", "tong sl")) or f.split(" ")[0] in ("kl", "sl")):
            return None
        if any(w in f for w in ("cho", "phong toa", "dat", "ban", "mua")):
            return 3
        if "kha dung" in f:
            return 2
        return 0 if "tong" in f else 1
    if key == "avg_cost":
        if any(w in f for w in ("gia von", "gia mua", "binh quan", "gia tb")):
            return 0 if "von" in f else 1
    return None


def _map_columns(cols) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for c in cols:
        f = _fold(c)
        for key, syn in SYNONYMS.items():
            if key not in found and f in syn:
                found[key] = c
    for key in SYNONYMS:  # khớp gần đúng cho khoá nào chưa tìm được
        if key in found:
            continue
        ranked = [(r, i, c) for i, c in enumerate(cols) if (r := _fuzzy_rank(_fold(c), key)) is not None and c not in found.values()]
        if ranked:
            found[key] = min(ranked, key=lambda t: (t[0], t[1]))[2]
    return found


def _holdings_from(df: pd.DataFrame, mapping: Dict[str, str]) -> Tuple[List[Dict], List[str]]:
    notes: List[str] = []
    rows = []
    for _, r in df.iterrows():
        sym = str(r[mapping["symbol"]]).upper().strip()
        qty = to_number(r[mapping["qty"]])
        avg = to_number(r[mapping["avg_cost"]]) if mapping.get("avg_cost") else None
        if _SYM.match(sym) and qty and qty > 0:
            rows.append({"symbol": sym, "qty": qty, "avg_cost": avg if avg is not None else 0.0})
    if not mapping.get("avg_cost"):
        notes.append("File không có cột giá vốn: lãi/lỗ sẽ chưa tính được. Bạn có thể bổ sung ở bảng nhập tay.")
    costs = [r["avg_cost"] for r in rows if r["avg_cost"] > 0]
    if costs and max(costs) < 1000:  # giá tính theo nghìn đồng -> đổi sang đồng
        for r in rows:
            r["avg_cost"] *= 1000
        notes.append("Giá vốn trong file tính theo nghìn đồng: đã tự đổi sang đồng.")
    out = clean_holdings(rows)
    skipped = int(df[mapping["symbol"]].notna().sum()) - len(rows)
    if out and skipped > 0:
        notes.append(f"Bỏ qua {skipped} dòng không phải cổ phiếu hợp lệ (ví dụ dòng tổng cộng, mã sai hoặc khối lượng bằng 0).")
    if not out:
        notes.append("Không đọc được dòng cổ phiếu hợp lệ nào.")
    return out, notes


def parse_statement(raw: pd.DataFrame) -> Tuple[List[Dict], List[str]]:
    """Đọc bảng danh mục xuất từ công ty chứng khoán. Trả về (danh mục, ghi chú/cảnh báo cho người dùng)."""
    df, mapping = raw, _map_columns(raw.columns)
    if not {"symbol", "qty"} <= set(mapping):  # tiêu đề có thể nằm ở vài dòng đầu
        for i in range(min(15, len(raw))):
            cand = raw.iloc[i:].copy()
            cand.columns = [str(v) for v in raw.iloc[i]]
            m = _map_columns(cand.columns)
            if {"symbol", "qty"} <= set(m):
                df, mapping = cand.iloc[1:], m
                break
    if not {"symbol", "qty"} <= set(mapping):
        return [], ["Không nhận ra cột “Mã” và “Khối lượng” trong file. Hãy dùng phần “Tự chọn cột” bên dưới."]
    return _holdings_from(df, mapping)


# ---------------------------------------------------------------- lịch sử giao dịch
TX_SYN = {
    "side": {"loai lenh", "mua ban", "loai gd", "side", "lenh", "buy sell", "nb ns", "giao dich", "loai giao dich",
             "exectype", "exec type", "chieu"},
    "price": {"gia khop", "gia", "price", "gia giao dich", "gia khop tb", "gia thuc hien"},
    "qty": {"khoi luong khop", "kl khop", "sl khop", "khoi luong", "so luong", "sl", "quantity", "qty", "kl"},
    "date": {"ngay", "ngay giao dich", "date", "thoi gian", "ngay khop", "ngay thuc hien", "time"},
    "status": {"trang thai", "status", "tinh trang"},
    "symbol": SYNONYMS["symbol"],
}


def _tx_map(cols) -> Dict[str, str]:
    """Ánh xạ cột lịch sử giao dịch. Với số lượng/giá ưu tiên cột 'khớp' (không lấy khối lượng ĐẶT)."""
    found: Dict[str, str] = {}
    folded = {c: _fold(c) for c in cols}
    for key, syn in TX_SYN.items():
        cand = [c for c, f in folded.items() if f in syn]
        if key in ("qty", "price") and cand:
            cand.sort(key=lambda c: 0 if "khop" in folded[c] else 1)
        if cand:
            found[key] = cand[0]
    return found


def _side(v) -> int:
    f = _fold(v)
    if re.search(r"\b(mua|buy|nb)\b", f):
        return 1
    if re.search(r"\b(ban|sell|ns)\b", f):
        return -1
    return 0


def _find_header(raw: pd.DataFrame, need: set):
    m = _tx_map(raw.columns)
    if need <= set(m):
        return raw, m
    for i in range(min(15, len(raw))):
        cand = raw.iloc[i:].copy()
        cand.columns = [str(v) for v in raw.iloc[i]]
        m = _tx_map(cand.columns)
        if need <= set(m):
            return cand.iloc[1:], m
    return None, {}


def looks_like_transactions(raw: pd.DataFrame) -> bool:
    df, _ = _find_header(raw, {"symbol", "side", "qty", "price"})
    return df is not None


def _tx_parse(df: pd.DataFrame, m: Dict[str, str]) -> Tuple[List[tuple], List[str]]:
    """Đọc từng lệnh khớp: [(ngày, thứ tự, mã, chiều +1/-1, khối lượng, giá)], đã sắp theo ngày; kèm ghi chú."""
    notes: List[str] = []
    if m.get("status"):
        keep = df[m["status"]].map(lambda v: ("khop" in _fold(v) or "filled" in _fold(v) or "matched" in _fold(v)
                                              or "hoan thanh" in _fold(v)) and "huy" not in _fold(v) and "cancel" not in _fold(v))
        dropped = int((~keep).sum())
        df = df[keep]
        if dropped:
            notes.append(f"Bỏ {dropped} dòng không phải lệnh đã khớp (huỷ, chờ khớp...).")
    else:
        notes.append("File không có cột trạng thái: coi mọi dòng là lệnh đã khớp. Hãy kiểm tra không có lệnh bị huỷ lẫn vào.")
    tx = []
    for pos, (_, r) in enumerate(df.iterrows()):
        sym = str(r[m["symbol"]]).upper().strip()
        side, qty, price = _side(r[m["side"]]), to_number(r[m["qty"]]), to_number(r[m["price"]])
        if _SYM.match(sym) and side and qty and qty > 0 and price and price > 0:
            when = pd.to_datetime(r[m["date"]], dayfirst=True, errors="coerce") if m.get("date") else pd.NaT
            tx.append((when, pos, sym, side, qty, price))
    if tx and max(t[5] for t in tx) < 1000:  # giá tính theo nghìn đồng
        tx = [(w, i, sy, sd, q, p * 1000) for w, i, sy, sd, q, p in tx]
        notes.append("Giá trong file tính theo nghìn đồng: đã tự đổi sang đồng.")
    if tx and all(pd.notna(t[0]) for t in tx):
        tx.sort(key=lambda t: (t[0], t[1]))  # theo ngày, giữ thứ tự trong cùng ngày
    elif m.get("date"):
        notes.append("Một số dòng không đọc được ngày: giữ nguyên thứ tự trong file.")
    return tx, notes


def _tx_from(df: pd.DataFrame, m: Dict[str, str]) -> Tuple[List[Dict], List[str]]:
    """Từ lịch sử lệnh khớp -> danh mục hiện tại. Giá vốn = bình quân gia quyền các lần mua (chưa gồm phí)."""
    tx, notes = _tx_parse(df, m)
    pos_qty: Dict[str, float] = {}
    pos_cost: Dict[str, float] = {}
    oversold = set()
    for _, _, sym, side, qty, price in tx:
        q0 = pos_qty.get(sym, 0.0)
        if side > 0:
            pos_qty[sym], pos_cost[sym] = q0 + qty, pos_cost.get(sym, 0.0) + qty * price
        else:
            sell = min(qty, q0)
            if qty > q0:
                oversold.add(sym)
            avg = pos_cost.get(sym, 0.0) / q0 if q0 else 0.0
            pos_qty[sym], pos_cost[sym] = q0 - sell, avg * (q0 - sell)
    rows = [{"symbol": sym, "qty": q, "avg_cost": pos_cost[sym] / q} for sym, q in pos_qty.items() if q > 0]
    if oversold:
        notes.append("Bán nhiều hơn số đang có ở " + ", ".join(sorted(oversold)) + ": file thiếu lịch sử mua trước đó, "
                     "số lượng/giá vốn các mã này có thể sai.")
    notes.append("Giá vốn tính từ giá khớp, chưa gồm phí. Cổ phiếu thưởng, cổ tức bằng cổ phiếu, chia tách không có trong lịch sử lệnh "
                 "nên không được cộng vào. File phải bắt đầu từ lần mua đầu tiên.")
    out = clean_holdings(rows)
    if not out:
        notes.append("Theo lịch sử này, hiện không còn cổ phiếu nào đang giữ.")
    return out, notes


def parse_transactions(raw: pd.DataFrame) -> Tuple[List[Dict], List[str]]:
    df, m = _find_header(raw, {"symbol", "side", "qty", "price"})
    if df is None:
        return [], ["Không nhận ra các cột “Mã”, “Mua/Bán”, “Khối lượng”, “Giá” trong file lịch sử giao dịch."]
    return _tx_from(df, m)


def transactions_from_file(raw: pd.DataFrame) -> Tuple[List[tuple], List[str]]:
    """Từng lệnh khớp trong file lịch sử giao dịch (tự tìm tiêu đề). Rỗng nếu không phải file giao dịch."""
    df, m = _find_header(raw, {"symbol", "side", "qty", "price"})
    return ([], []) if df is None else _tx_parse(df, m)


def transactions_manual(df: pd.DataFrame, cols: Dict[str, Optional[str]]) -> Tuple[List[tuple], List[str]]:
    cols = {k: v for k, v in cols.items() if v}
    if not {"symbol", "side", "qty", "price"} <= set(cols):
        return [], []
    return _tx_parse(df, cols)


def apply_header(raw: pd.DataFrame, k: int) -> Tuple[pd.DataFrame, List[str]]:
    """Coi dòng thứ k của file (1 = dòng đầu) là tiêu đề. Trả về (bảng dữ liệu, tên cột duy nhất)."""
    if k <= 1:
        df, names = raw, [str(c) for c in raw.columns]
    else:
        cand = raw.iloc[k - 2:].copy()
        names = [str(v) for v in raw.iloc[k - 2]]
        df = cand.iloc[1:]
    seen, uniq = {}, []
    for i, n in enumerate(names):
        n = f"Cột {i + 1}" if n.strip().lower() in ("", "nan", "none") or n.startswith("Unnamed") else n
        seen[n] = seen.get(n, 0) + 1
        uniq.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    df = df.copy()
    df.columns = uniq
    return df, uniq


def parse_manual(df: pd.DataFrame, kind: str, cols: Dict[str, Optional[str]]) -> Tuple[List[Dict], List[str]]:
    """Đọc theo cột do người dùng tự chọn. kind: 'danh mục' hoặc 'giao dịch'."""
    cols = {k: v for k, v in cols.items() if v}
    need = {"symbol", "qty"} | ({"side", "price"} if kind == "giao dịch" else set())
    if not need <= set(cols):
        return [], ["Hãy chọn đủ các cột bắt buộc."]
    return _tx_from(df, cols) if kind == "giao dịch" else _holdings_from(df, cols)


def parse_file(raw: pd.DataFrame) -> Tuple[List[Dict], List[str], str]:
    """Tự nhận loại file: lịch sử giao dịch (có cột Mua/Bán) hay danh mục đang giữ. Trả về (danh mục, ghi chú, loại)."""
    if looks_like_transactions(raw):
        rows, notes = parse_transactions(raw)
        return rows, notes, "giao dịch"
    rows, notes = parse_statement(raw)
    return rows, notes, "danh mục"


# ---------------------------------------------------------------- định giá
def valuate(pf: Dict, last_price: Callable[[str], Optional[float]], max_alloc: float = 0.30, capital: float = 0.0) -> Tuple[pd.DataFrame, Dict]:
    """Định giá danh mục. Thứ tự giá: giá đóng cửa trong dữ liệu của bạn -> giá thị trường do TCBS báo -> giá vốn.

    capital: vốn/tổng tài sản bạn đặt ở Cài đặt. Bạn thường chỉ đầu tư MỘT PHẦN, phần còn lại chưa ghi trong Danh mục. Mọi tỷ lệ % (tỷ trọng, tiền mặt) tính trên
    base = max(cổ phiếu + tiền mặt đã ghi, capital); phần chênh lệch coi là tiền chưa đầu tư (assumed_cash). `total` vẫn là số đã ghi trong Danh mục."""
    rows = []
    for h in pf["holdings"]:
        p, src = last_price(h["symbol"]), "dữ liệu giá của bạn"
        if not p:
            if h.get("market_value"):
                p, src = h["market_value"] / h["qty"], "TCBS báo"
            else:
                p, src = h["avg_cost"] or None, "giá vốn (chưa có giá thị trường)"
        value = (p or 0) * h["qty"]
        cost = h["avg_cost"] * h["qty"]
        pnl = value - cost if h["avg_cost"] > 0 and p else None
        net = (value * (1 - FEE_RATE - SELL_TAX) - cost * (1 + FEE_RATE)) if pnl is not None else None
        rows.append({"symbol": h["symbol"], "qty": h["qty"], "avg_cost": h["avg_cost"], "price": p, "price_src": src,
                     "value": value, "cost": cost, "pnl": pnl, "pnl_pct": (pnl / cost if pnl is not None and cost else None),
                     "net_pnl": net})
    df = pd.DataFrame(rows, columns=["symbol", "qty", "avg_cost", "price", "price_src", "value", "cost", "pnl", "pnl_pct", "net_pnl"])
    stock_value = float(df["value"].sum()) if len(df) else 0.0
    total = stock_value + pf["cash"]
    base = max(total, float(capital or 0.0))
    assumed = base - total
    df["weight"] = df["value"] / base if base else 0.0
    known = df[df["pnl"].notna()]
    cost_known = float(known["cost"].sum())
    pnl_known = float(known["pnl"].sum()) if len(known) else 0.0
    warnings: List[str] = []
    for r in df.itertuples():
        if r.weight > max_alloc:
            warnings.append(f"{r.symbol} chiếm {r.weight * 100:.0f}% tổng tài sản, vượt mức {max_alloc * 100:.0f}% bạn đặt cho một mã.")
        if r.price_src.startswith("giá vốn"):
            warnings.append(f"{r.symbol}: chưa có giá thị trường, đang tạm tính theo giá vốn.")
    if base and (pf["cash"] + assumed) / base < 0.05 and len(df):
        warnings.append("Tiền mặt dưới 5% tổng tài sản: gần như không còn dư địa khi cần mua thêm hoặc chịu biến động.")
    summary = {"total": total, "base": base, "assumed_cash": assumed, "stock_value": stock_value, "cash": pf["cash"], "pnl": pnl_known,
               "pnl_pct": (pnl_known / cost_known if cost_known else None), "n": len(df), "warnings": warnings,
               "net_pnl": float(known["net_pnl"].sum()) if len(known) else 0.0}
    return df, summary
