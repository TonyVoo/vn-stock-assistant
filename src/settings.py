"""Lưu cài đặt người dùng ra file (data/settings.json) để không mất khi tải lại trang.

Lý do cần file riêng: Streamlit xoá trạng thái của ô nhập khi bạn rời trang hoặc tải lại, nên không thể chỉ dựa vào session.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from .data import VN30_DEFAULT

PATH = Path(os.getenv("SETTINGS_PATH") or Path(__file__).resolve().parent.parent / "data" / "settings.json")
DEFAULTS = {"capital_m": 10.0, "watch": VN30_DEFAULT[:12], "risk_pct": 2.0, "max_alloc": 30, "auto_price": True, "simple_mode": False}
_SYM = re.compile(r"^[A-Z0-9]{2,6}$")


def clean(raw: Dict) -> Dict:
    """Ép giá trị về dạng hợp lệ; trường nào hỏng thì dùng mặc định."""
    out = dict(DEFAULTS)
    try:
        v = float(raw.get("capital_m", out["capital_m"]))
        if 0.1 <= v <= 1_000_000:
            out["capital_m"] = v
    except (TypeError, ValueError):
        pass
    watch = raw.get("watch")
    if isinstance(watch, list):
        seen, w = set(), []
        for s in watch:
            s = str(s).upper().strip()
            if _SYM.match(s) and s not in seen:
                seen.add(s)
                w.append(s)
        if w:
            out["watch"] = w
    for k, lo, hi in (("risk_pct", 0.5, 5.0), ("max_alloc", 10, 50)):
        try:
            v = float(raw.get(k, out[k]))
            if lo <= v <= hi:
                out[k] = v if k == "risk_pct" else int(v)
        except (TypeError, ValueError):
            pass
    for k in ("auto_price", "simple_mode"):
        b = raw.get(k, out[k])
        out[k] = b if isinstance(b, bool) else out[k]
    return out


def load(path: Optional[Path] = None) -> Dict:
    p = Path(path or PATH)
    try:
        return clean(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(values: Dict, path: Optional[Path] = None) -> Dict:
    p = Path(path or PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = clean(values)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)  # ghi nguyên tử: không bao giờ để lại file nửa chừng
    return data
