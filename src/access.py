"""Mã PIN tuỳ chọn khi bạn mở app cho điện thoại trong cùng mạng WiFi.

Đặt APP_PIN trong file .env để bật. Đây chỉ là lớp chắn cơ bản cho mạng WiFi nhà tin cậy (so sánh an toàn thời gian, khoá tạm sau nhiều lần sai);
KHÔNG đủ để đưa app ra Internet công cộng. Không đặt APP_PIN thì app không hỏi mã (dùng trên chính máy này).
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Callable, Optional

MIN_LEN = 4


def configured_pin() -> Optional[str]:
    pin = (os.getenv("APP_PIN") or "").strip()
    return pin or None


class Guard:
    """Kiểm tra mã PIN, dùng chung cho mọi phiên trình duyệt: sai liên tiếp max_fail lần thì khoá lock_s giây."""

    def __init__(self, pin: str, max_fail: int = 5, lock_s: float = 60.0, clock: Callable[[], float] = time.time):
        self.pin, self.max_fail, self.lock_s, self.clock = pin, max_fail, lock_s, clock
        self.fails, self.locked_until = 0, 0.0

    def remaining_lock(self) -> float:
        return max(0.0, self.locked_until - self.clock())

    def check(self, entered: str) -> bool:
        if self.remaining_lock() > 0:
            return False  # đang khoá: kể cả nhập đúng cũng không được, để không dò mã được trong lúc khoá
        if hmac.compare_digest(str(entered).encode(), self.pin.encode()):
            self.fails = 0
            return True
        self.fails += 1
        if self.fails >= self.max_fail:
            self.fails, self.locked_until = 0, self.clock() + self.lock_s
        return False


_GUARDS: dict = {}


def guard() -> Optional[Guard]:
    pin = configured_pin()
    if pin is None:
        return None
    if _GUARDS.get("pin") != pin:
        _GUARDS["pin"], _GUARDS["g"] = pin, Guard(pin)
    return _GUARDS["g"]
