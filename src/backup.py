"""Sao lưu và khôi phục dữ liệu cá nhân (Nhật ký, Danh mục, tiền nạp/rút, cổ tức, sổ giả lập, cài đặt).

An toàn:
- Sao lưu SQLite bằng API sao lưu của SQLite (nhất quán kể cả khi đang ghi), không chép file thô.
- Khôi phục: chỉ nhận đúng các tên file đã biết trong gói (không bao giờ giải nén đường dẫn tuỳ ý), kiểm tra từng file CSDL mở được,
  và LUÔN tự sao lưu dữ liệu hiện tại trước khi ghi đè. Ghi nguyên tử (file tạm rồi thay thế).
- Không gồm file giá (data/prices) vì tải lại được bằng nút Cập nhật giá.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import cashflow, chat_store, dividends, journal, paper, portfolio, settings

BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or Path(__file__).resolve().parent.parent / "data" / "backups")
KEEP_LOCAL = 20      # bản tự lưu bằng nút hoặc trước khi khôi phục
KEEP_AUTO = 14       # bản tự động hằng ngày (2 tuần gần nhất), tính riêng để không đẩy bản thủ công đi
AUTO_TAG = "-tu-dong"
_CHECKED: Dict[str, str] = {}   # thư mục -> ngày đã kiểm tra (trong tiến trình này)
DB_NAMES = ("journal.db", "cashflows.db", "dividends.db", "paper.db")
JSON_NAMES = ("portfolio.json", "settings.json", "chat_history.json")


def default_paths() -> Dict[str, Path]:
    """Tra cứu lúc gọi (không lúc nhập module) để kiểm thử thay thế được."""
    return {"journal.db": Path(journal.DB_PATH), "cashflows.db": Path(cashflow.DB_PATH), "dividends.db": Path(dividends.DB_PATH),
            "paper.db": Path(paper.DB_PATH), "portfolio.json": Path(portfolio.PATH), "settings.json": Path(settings.PATH),
            "chat_history.json": Path(chat_store.PATH)}


def _sqlite_bytes(path: Path) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "copy.db"
        src, dst = sqlite3.connect(path), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return tmp.read_bytes()


def create(paths: Optional[Dict[str, Path]] = None) -> bytes:
    paths = paths or default_paths()
    buf = io.BytesIO()
    included: List[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, p in paths.items():
            if not Path(p).exists():
                continue
            z.writestr(name, _sqlite_bytes(Path(p)) if name in DB_NAMES else Path(p).read_bytes())
            included.append(name)
        z.writestr("manifest.json", json.dumps({"created": datetime.now().isoformat(timespec="seconds"), "files": included}, ensure_ascii=False))
    return buf.getvalue()


def save_local(paths: Optional[Dict[str, Path]] = None, directory: Optional[Path] = None, tag: str = "", when=None) -> Path:
    d = Path(directory or BACKUP_DIR)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"sao-luu-{(when or datetime.now()):%Y%m%d-%H%M%S}{tag}.zip"
    out.write_bytes(create(paths))
    _rotate(d)
    return out


def _rotate(d: Path) -> None:
    """Chỉ giữ các bản mới nhất, tính riêng bản tự động (KEEP_AUTO) và bản còn lại (KEEP_LOCAL)."""
    allz = sorted(d.glob("sao-luu-*.zip"))
    auto = [f for f in allz if f.name.endswith(AUTO_TAG + ".zip")]
    manual = [f for f in allz if f not in auto]
    for group, keep in ((auto, KEEP_AUTO), (manual, KEEP_LOCAL)):
        for old in group[:-keep]:
            old.unlink()


def auto_backup(paths: Optional[Dict[str, Path]] = None, directory: Optional[Path] = None, today=None) -> Optional[Path]:
    """Mỗi ngày tối đa MỘT bản tự động, và chỉ khi đã có dữ liệu cá nhân để lưu. Lỗi thì trả None, không bao giờ làm app lỗi."""
    try:
        d = Path(directory or BACKUP_DIR)
        day = (today or datetime.now()).strftime("%Y%m%d")
        if _CHECKED.get(str(d)) == day:
            return None  # hôm nay đã kiểm tra rồi (app chạy lại nhiều lần mỗi phút, không cần quét thư mục mỗi lần)
        _CHECKED[str(d)] = day
        if any(d.glob(f"sao-luu-{day}-*{AUTO_TAG}.zip")):
            return None
        paths = paths or default_paths()
        if not any(Path(paths[n]).exists() for n in ("journal.db", "portfolio.json", "cashflows.db", "dividends.db") if n in paths):
            return None  # chưa có dữ liệu thì chưa cần sao lưu
        return save_local(paths, d, tag=AUTO_TAG, when=today)
    except Exception:  # noqa: BLE001
        return None


def latest_auto(directory: Optional[Path] = None) -> Optional[Path]:
    files = sorted(Path(directory or BACKUP_DIR).glob(f"sao-luu-*{AUTO_TAG}.zip"))
    return files[-1] if files else None


def restore_some(data: bytes, names, paths: Optional[Dict[str, Path]] = None) -> List[str]:
    """Khôi phục CHỈ các file được chọn từ một gói sao lưu (ví dụ hoàn tác lần nhập sao kê). Có kiểm tra gói và tự lưu bản hiện tại trước."""
    info = inspect(data)
    paths = paths or default_paths()
    want = [n for n in names if n in info["files"]]
    if not want:
        return []
    save_local(paths, tag="-truoc-hoan-tac")
    z = zipfile.ZipFile(io.BytesIO(data))
    for name in want:
        target = Path(paths[name])
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".restore.tmp")
        tmp.write_bytes(z.read(name))
        os.replace(tmp, target)
    return want


def inspect(data: bytes) -> Dict:
    """Kiểm tra gói trước khi khôi phục. Trả về {"files": [...], "created": str}; lỗi thì ValueError."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Đây không phải file sao lưu hợp lệ (.zip).") from None
    names = [n for n in z.namelist() if n in DB_NAMES + JSON_NAMES]
    if not names:
        raise ValueError("File không chứa dữ liệu của app.")
    for n in names:
        raw = z.read(n)
        if n in DB_NAMES:
            if not raw.startswith(b"SQLite format 3\x00"):
                raise ValueError(f"{n} không phải cơ sở dữ liệu hợp lệ.")
            with tempfile.TemporaryDirectory() as td:
                t = Path(td) / "t.db"
                t.write_bytes(raw)
                c = sqlite3.connect(t)
                try:
                    if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError(f"{n} bị hỏng.")
                finally:
                    c.close()
        else:
            try:
                json.loads(raw.decode("utf-8"))
            except ValueError:
                raise ValueError(f"{n} không đọc được.") from None
    created = ""
    if "manifest.json" in z.namelist():
        try:
            created = json.loads(z.read("manifest.json")).get("created", "")
        except ValueError:
            pass
    return {"files": names, "created": created}


def restore(data: bytes, paths: Optional[Dict[str, Path]] = None, directory: Optional[Path] = None) -> Dict:
    """Khôi phục. Tự sao lưu dữ liệu hiện tại trước. Chỉ ghi đè các file CÓ trong gói; file khác giữ nguyên."""
    info = inspect(data)  # lỗi thì dừng, chưa đụng dữ liệu hiện tại
    paths = paths or default_paths()
    safety = save_local(paths, directory, tag="-truoc-khi-khoi-phuc")
    z = zipfile.ZipFile(io.BytesIO(data))
    for name in info["files"]:
        target = Path(paths[name])
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".restore.tmp")
        tmp.write_bytes(z.read(name))
        os.replace(tmp, target)
    return {"restored": info["files"], "safety_copy": safety, "created": info["created"]}
