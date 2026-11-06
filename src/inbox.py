"""Thư mục “thả file vào là xong”: app tự đọc sao kê (CSV/Excel) công ty chứng khoán đặt trong data/inbox rồi cập nhật Danh mục và Nhật ký.

An toàn vì app tự ghi vào dữ liệu thật của bạn:
- TRƯỚC khi áp dụng luôn lưu một bản sao lưu đầy đủ, và có nút HOÀN TÁC lần nhập gần nhất (khôi phục Nhật ký + Danh mục về trước lúc nhập).
- Chỉ tự áp dụng khi đọc ra được ít nhất một mã cổ phiếu; file đọc không ra thì để nguyên và báo, không bao giờ xoá Danh mục.
- Mỗi file chỉ xử lý một lần (theo nội dung); nhập lại không trùng lệnh (cơ chế khoá lệnh của Nhật ký). File xử lý xong được CHUYỂN (không xoá) sang thư mục da-xu-ly.
- File đang được ghi dở (vừa sửa dưới vài giây) thì bỏ qua lượt này.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import backup, importer, portfolio

INBOX_DIR = Path(os.getenv("INBOX_DIR") or Path(__file__).resolve().parent.parent / "data" / "inbox")
EXTS = (".csv", ".xlsx")
SETTLE_SECONDS = 3.0        # file vừa sửa trong vòng này coi là đang ghi dở
SCAN_EVERY = 10.0           # giây, tối thiểu giữa hai lần quét
KEEP_HISTORY = 20
_LOCK = threading.Lock()
_LAST_SCAN = {"t": 0.0}


def inbox_dir() -> Path:
    return Path(INBOX_DIR)


def _state_path() -> Path:
    return inbox_dir() / "trang_thai.json"


def load_state() -> Dict:
    try:
        s = json.loads(_state_path().read_text(encoding="utf-8"))
        if isinstance(s, dict):
            return {"processed": s.get("processed", {}), "failed": s.get("failed", {}), "history": s.get("history", []), "undo": s.get("undo")}
    except (OSError, ValueError):
        pass
    return {"processed": {}, "failed": {}, "history": [], "undo": None}


def save_state(s: Dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    s["history"] = s.get("history", [])[-KEEP_HISTORY:]
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def read_bytes(name: str, data: bytes) -> Dict[str, pd.DataFrame]:
    """{tên trang tính: bảng}. CSV chỉ có một bảng; Excel có thể có nhiều trang tính."""
    buf = io.BytesIO(data)
    if name.lower().endswith(".csv"):
        return {"CSV": pd.read_csv(buf, sep=None, engine="python", encoding="utf-8-sig", dtype=str, header=0)}
    return pd.read_excel(buf, sheet_name=None, dtype=str, header=0)


def read_pasted(text: str) -> Dict[str, pd.DataFrame]:
    """Bảng copy từ trang web: các ô cách nhau bằng dấu tab (hoặc từ 2 dấu cách trở lên)."""
    text = (text or "").strip("\n\r ")
    if not text:
        raise ValueError("Chưa có nội dung.")
    sep = "\t" if "\t" in text else r"\s{2,}"
    df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", dtype=str, header=0)
    if df.shape[1] < 2 or df.empty:
        raise ValueError("Không thấy dạng bảng. Hãy bôi đen cả bảng (gồm dòng tiêu đề) trên trang web rồi copy.")
    return {"Dán": df}


def interpret(sheets: Dict[str, pd.DataFrame]):
    """Chọn trang tính đọc được. Trả (tên trang, bảng thô, danh mục, ghi chú, loại)."""
    chosen = None
    for name, raw in sheets.items():
        rows, notes, kind = portfolio.parse_file(raw)
        if rows or kind == "giao dịch":
            chosen = (name, raw, rows, notes, kind)
            break
    if chosen is None:
        name, raw = next(iter(sheets.items()))
        rows, notes, kind = portfolio.parse_file(raw)
        chosen = (name, raw, rows, notes, kind)
    return chosen


def apply_rows(kind: str, raw: pd.DataFrame, rows: List[Dict], pf_path: Optional[Path] = None, jpath: Optional[Path] = None) -> Dict:
    """Ghi vào Nhật ký (không trùng) và cập nhật Danh mục, giống nút “Thêm vào Nhật ký và cập nhật Danh mục”. Giữ nguyên tiền mặt đang có."""
    pf = portfolio.load(pf_path)
    notes: List[str] = []
    if kind == "giao dịch":
        tx, _ = portfolio.transactions_from_file(raw)
        trades, notes = importer.fifo_trades(tx)
    else:
        trades = importer.holdings_to_trades(rows, importer.open_symbols(jpath))
    r = importer.to_journal(trades, jpath)
    portfolio.save({"holdings": rows, "cash": pf["cash"]}, "import", pf_path)
    return {"journal_open": r["open"], "journal_closed": r["closed"], "holdings": len(rows), "notes": notes}


def process_bytes(name: str, data: bytes) -> Dict:
    """Xử lý một file. Trả {ok, kind, summary, ...}. Không bao giờ ghi gì nếu không đọc ra được mã cổ phiếu."""
    try:
        sheets = read_bytes(name, data)
    except ImportError:
        return {"ok": False, "error": "Đọc file Excel cần thư viện openpyxl (pip install openpyxl) hoặc hãy xuất file dạng CSV."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Không đọc được file ({type(e).__name__})."}
    _, raw, rows, notes, kind = interpret(sheets)
    if not rows:
        return {"ok": False, "error": "Không nhận ra mã cổ phiếu trong file này (hoặc theo lịch sử, bạn không còn giữ mã nào). Để an toàn, app KHÔNG tự cập nhật; bạn tải file lên thủ công ở trang Danh mục."}
    snap = backup.save_local(tag="-truoc-nhap")        # bản sao lưu đầy đủ trước khi ghi
    res = apply_rows(kind, raw, rows)
    return {"ok": True, "kind": kind, "snapshot": str(snap), "notes": notes + res["notes"],
            "summary": f"{name}: {'lịch sử giao dịch' if kind == 'giao dịch' else 'danh mục đang giữ'}, {res['holdings']} mã, "
                       f"thêm {res['journal_open']} lệnh đang giữ và {res['journal_closed']} lệnh đã bán vào Nhật ký."}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:20]


def _candidates(directory: Path) -> List[Path]:
    if not directory.is_dir():
        return []
    out = []
    for f in sorted(directory.iterdir()):
        if not f.is_file() or f.suffix.lower() not in EXTS or f.name.startswith((".", "~$")):
            continue
        out.append(f)
    return out


def scan(now: Optional[float] = None, mover: Callable = shutil.move) -> List[Dict]:
    """Quét thư mục inbox. Trả về danh sách kết quả mỗi file mới."""
    now = time.time() if now is None else now
    results: List[Dict] = []
    with _LOCK:
        base = inbox_dir()
        base.mkdir(parents=True, exist_ok=True)
        state = load_state()
        for f in _candidates(base):
            try:
                if now - f.stat().st_mtime < SETTLE_SECONDS:
                    continue  # đang ghi dở
                data = f.read_bytes()
            except OSError:
                continue
            h = _hash(data)
            fail_key = f"{f}:{len(data)}:{int(f.stat().st_mtime)}"
            if h in state["processed"]:
                _archive(f, mover, "trung-")
                continue
            if fail_key in state["failed"]:
                continue
            r = process_bytes(f.name, data)
            r["file"] = f.name
            if r["ok"]:
                state["processed"][h] = {"name": f.name, "at": datetime.now().isoformat(timespec="seconds"), "summary": r["summary"]}
                state["history"].append({"name": f.name, "at": state["processed"][h]["at"], "summary": r["summary"]})
                state["undo"] = {"zip": r["snapshot"], "name": f.name, "at": state["processed"][h]["at"], "summary": r["summary"]}
                _archive(f, mover, "")
            else:
                state["failed"][fail_key] = r["error"]
            results.append(r)
        save_state(state)
    return results


def _archive(f: Path, mover: Callable, prefix: str) -> None:
    done = inbox_dir() / "da-xu-ly"
    done.mkdir(parents=True, exist_ok=True)
    try:
        mover(str(f), str(done / f"{datetime.now():%Y%m%d-%H%M%S}-{prefix}{f.name}"))
    except OSError:
        pass


def scan_throttled() -> List[Dict]:
    """Gọi thoải mái từ giao diện: chỉ thật sự quét tối đa mỗi SCAN_EVERY giây; lỗi bất ngờ thì bỏ qua, không làm app lỗi."""
    t = time.time()
    if t - _LAST_SCAN["t"] < SCAN_EVERY:
        return []
    _LAST_SCAN["t"] = t
    try:
        return scan()
    except Exception:  # noqa: BLE001
        return []


def undo() -> Optional[Dict]:
    """Hoàn tác lần nhập gần nhất: khôi phục Nhật ký và Danh mục về bản sao lưu trước lúc nhập (các file khác giữ nguyên)."""
    with _LOCK:
        state = load_state()
        u = state.get("undo")
        if not u or not Path(u["zip"]).exists():
            return None
        backup.restore_some(Path(u["zip"]).read_bytes(), ("journal.db", "portfolio.json"))
        state["undo"] = None
        state["history"].append({"name": u["name"], "at": datetime.now().isoformat(timespec="seconds"), "summary": "Đã hoàn tác lần nhập này."})
        # cho phép nhập lại đúng file đó nếu bạn muốn
        state["processed"] = {k: v for k, v in state["processed"].items() if v.get("name") != u["name"] or v.get("at") != u["at"]}
        save_state(state)
        return u
