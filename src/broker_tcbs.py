"""Kết nối TCBS iFlash Open API ở chế độ CHỈ ĐỌC (xem tài liệu: developers.tcbs.com.vn).

Vì sao phải tự chặn: theo tài liệu, khoá API của TCBS KHÔNG có chế độ chỉ-đọc (cùng khoá dùng được cả lệnh đặt/sửa/huỷ
và chuyển tiền). Nên ở đây:
- Chỉ có MỘT lệnh POST duy nhất, tới địa chỉ cố định để đổi khoá + Smart OTP lấy mã truy cập (hiệu lực tối đa 8 giờ).
- Mọi lệnh còn lại là GET, và đường dẫn phải khớp danh sách cho phép (danh mục, tiền, sức mua, lệnh, hồ sơ).
  Các đường dẫn đặt/sửa/huỷ lệnh (/akhlys/...) và chuyển tiền không thể gọi được từ lớp này.
- Mã truy cập chỉ nằm trong bộ nhớ của đối tượng này, không ghi ra đĩa, không đưa vào log hay thông báo lỗi.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

import requests

BASE_URL = "https://openapi.tcbs.com.vn"
TOKEN_PATH = "/gaia/v1/oauth2/openapi/token"
TOKEN_TTL = 8 * 3600 - 300  # tối đa 8 giờ theo tài liệu, trừ 5 phút an toàn

READ_ALLOWED = (
    re.compile(r"^/aion/v1/accounts/[A-Za-z0-9]{3,20}/(se|cashInvestments|orders|ppse)$"),
    re.compile(r"^/eros/v2/get-profile/by-username/[A-Za-z0-9]{3,20}$"),
)


class BrokerError(Exception):
    """Lỗi từ TCBS hoặc mạng. Nội dung đã được làm sạch, không chứa khoá/OTP/mã truy cập."""


class AuthRequired(BrokerError):
    """Chưa đăng nhập hoặc mã truy cập hết hạn: cần nhập Smart OTP mới."""


class TcbsReadOnly:
    def __init__(self, api_key: str, session: Optional[requests.Session] = None, timeout: int = 15):
        if not api_key or not api_key.strip():
            raise BrokerError("Chưa có TCBS_API_KEY.")
        self._key = api_key.strip()
        self._s = session or requests.Session()
        self._timeout = timeout
        self._token: Optional[str] = None
        self._expires = 0.0
        self._secrets = [self._key]

    # ---- trạng thái
    def logged_in(self) -> bool:
        return bool(self._token) and time.time() < self._expires

    # ---- xác thực: lệnh POST duy nhất
    def login(self, otp: str) -> None:
        otp = (otp or "").strip()
        if not re.fullmatch(r"\d{4,8}", otp):
            raise BrokerError("Smart OTP phải gồm 4–8 chữ số.")
        self._secrets.append(otp)
        try:
            r = self._s.post(BASE_URL + TOKEN_PATH, json={"apiKey": self._key, "otp": otp},
                             headers={"Content-Type": "application/json"}, timeout=self._timeout)
        except requests.RequestException as e:
            raise BrokerError(f"Không kết nối được TCBS ({type(e).__name__}).") from None
        if r.status_code != 200:
            raise BrokerError(self._fail("Đăng nhập không thành công", r))
        try:
            token = r.json().get("token")
        except ValueError:
            token = None
        if not token:
            raise BrokerError("TCBS không trả về mã truy cập.")
        self._token = token
        self._secrets.append(token)
        self._expires = time.time() + TOKEN_TTL

    # ---- đọc dữ liệu
    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        if not any(p.match(path) for p in READ_ALLOWED):
            raise BrokerError("Đường dẫn không nằm trong danh sách chỉ-đọc được phép.")
        if not self.logged_in():
            raise AuthRequired("Cần nhập Smart OTP để lấy mã truy cập mới.")
        try:
            r = self._s.get(BASE_URL + path, params=params,
                            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
                            timeout=self._timeout)
        except requests.RequestException as e:
            raise BrokerError(f"Không kết nối được TCBS ({type(e).__name__}).") from None
        if r.status_code == 401:
            self._token = None
            raise AuthRequired("Mã truy cập đã hết hạn. Cần nhập Smart OTP mới.")
        if r.status_code != 200:
            raise BrokerError(self._fail("TCBS từ chối yêu cầu", r))
        try:
            return r.json()
        except ValueError:
            raise BrokerError("TCBS trả về dữ liệu không đọc được.") from None

    def accounts(self, custody_code: str) -> List[Dict]:
        """Tiểu khoản của một số lưu ký (để tìm accountNo)."""
        j = self._get(f"/eros/v2/get-profile/by-username/{custody_code}", {"fields": "bankSubAccounts"})
        return [{"accountNo": a.get("accountNo"), "type": a.get("accountType"), "name": a.get("accountTypeName"),
                 "default": a.get("isDefault") == "Y"} for a in j.get("bankSubAccounts", [])]

    def holdings(self, account_no: str) -> List[Dict]:
        j = self._get(f"/aion/v1/accounts/{account_no}/se")
        out = []
        for a in j.get("assets", []) or []:
            out.append({"symbol": str(a.get("symbol", "")).upper(), "qty": a.get("quantity") or 0,
                        "avg_cost": a.get("avgPrice") or 0.0, "market_value": a.get("marketValue")})
        return out

    def cash(self, account_no: str) -> float:
        j = self._get(f"/aion/v1/accounts/{account_no}/cashInvestments")
        return float(sum((row.get("cashBalance") or 0) for row in j.get("data", []) or []))

    def snapshot(self, account_no: str) -> Dict:
        """Danh mục + tiền mặt (đúng định dạng của src/portfolio.py)."""
        return {"holdings": self.holdings(account_no), "cash": self.cash(account_no)}

    # ---- làm sạch thông báo lỗi
    def _fail(self, msg: str, r) -> str:
        body = ""
        try:
            body = (r.text or "")[:160]
        except Exception:  # noqa: BLE001
            pass
        for s in self._secrets:
            if s:
                body = body.replace(s, "***")
        return f"{msg} (mã {r.status_code}). {body}".strip()
