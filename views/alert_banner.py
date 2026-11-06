"""Dải cảnh báo cắt lỗ/mục tiêu hiện ở đầu mọi trang, và thông báo macOS khi có cảnh báo mới nghiêm trọng."""
from __future__ import annotations

import datetime as dt
import subprocess
import sys

import streamlit as st

from src import alerts, journal, ui
from views import shared

_NOTIFIED: set = set()  # (id lệnh, loại, ngày) đã thông báo trong tiến trình này, để không báo lặp
MAX_SHOWN = 4


def _last_price(sym: str):
    try:
        df, _ = shared.load(sym)
        return float(df["close"].iloc[-1]) if df is not None and len(df) else None
    except Exception:  # noqa: BLE001
        return None


def current() -> list:
    t = journal.list_trades()
    open_t = t[t["exit_price"].isna()] if not t.empty else None
    return alerts.check(open_t, _last_price)


def _notify(items: list) -> None:
    """Thông báo của macOS cho cảnh báo MỚI mức chạm cắt lỗ/mục tiêu (chỉ khi app chạy trên máy Mac của bạn)."""
    if sys.platform != "darwin":
        return
    for a in items:
        key = (a["id"], a["kind"], dt.date.today())
        if a["kind"] not in ("hit_stop", "hit_target") or key in _NOTIFIED:
            continue
        _NOTIFIED.add(key)
        text = a["message"].replace("\\", " ").replace('"', "'")
        try:
            subprocess.run(["osascript", "-e", f'display notification "{text}" with title "Trợ lý chứng khoán"'], timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            pass


def render() -> None:
    items = current()
    if not items:
        return
    _notify(items)
    for a in items[:MAX_SHOWN]:
        ui.callout(a["message"], alerts.kind_style(a["kind"]), "Cảnh báo cắt lỗ" if a["kind"].endswith("stop") else "Mục tiêu giá")
    if len(items) > MAX_SHOWN:
        st.caption(f"Còn {len(items) - MAX_SHOWN} cảnh báo khác trong trang Nhật ký giao dịch.")
