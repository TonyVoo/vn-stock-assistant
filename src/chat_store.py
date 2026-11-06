"""Lưu lịch sử chat trên máy bạn (data/chat_history.json) để không mất khi tải lại trang hay đóng tab.

Chỉ lưu nội dung các lượt hỏi đáp (không lưu khoá API hay dữ liệu gửi kèm). Ghi nguyên tử; file hỏng thì bỏ qua và bắt đầu lại, không làm app lỗi.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

PATH = Path(os.getenv("CHAT_PATH") or Path(__file__).resolve().parent.parent / "data" / "chat_history.json")
MAX_MESSAGES = 60      # chỉ giữ các tin nhắn mới nhất
MAX_CHARS = 6000       # mỗi tin nhắn


def clean(items) -> List[Dict]:
    """Chỉ nhận đúng dạng {role: user|assistant, content: str}; bỏ phần còn lại; cắt độ dài."""
    out: List[Dict] = []
    for m in items if isinstance(items, list) else []:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            continue
        e = {"role": m["role"], "content": m["content"][:MAX_CHARS]}
        if m.get("partial") is True:
            e["partial"] = True
        out.append(e)
    return out[-MAX_MESSAGES:]


def load(path: Optional[Path] = None) -> List[Dict]:
    try:
        return clean(json.loads(Path(path or PATH).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def save(hist: List[Dict], path: Optional[Path] = None) -> None:
    p = Path(path or PATH)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(clean(hist), ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass  # không lưu được thì thôi, chat vẫn dùng bình thường
