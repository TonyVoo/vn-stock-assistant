"""Dữ liệu và tiện ích dùng chung cho các trang."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import streamlit as st

from src import explain, llm, settings, signals
from src import news as newsmod
from src import data as data_mod
from src.data import get_prices

PAGES: Dict[str, object] = {}  # khoá -> st.Page, do app.py điền


@dataclass
class Ctx:
    capital: float
    watchlist: List[str]


def get_ctx() -> Ctx:
    s = st.session_state
    return Ctx(capital=float(s["capital_m"]) * 1_000_000, watchlist=list(s["watch"]) or settings.DEFAULTS["watch"])


def current_settings() -> Dict:
    s = st.session_state
    return {"capital_m": s["capital_m"], "watch": s["watch"], "risk_pct": s["risk_pct"], "max_alloc": s["max_alloc"],
            "auto_price": s.get("auto_price", True), "simple_mode": s.get("simple_mode", False)}


def init_state() -> None:
    """Nạp cài đặt từ file vào session một lần mỗi phiên làm việc."""
    if "settings_loaded" in st.session_state:
        return
    st.session_state.update(settings.load())
    st.session_state["settings_loaded"] = True


def page(fn: Callable, key: Optional[str] = None) -> Callable:
    """Bọc hàm render(ctx) thành hàm không tham số để st.Page gọi. Ghi lại trang đang xem để chatbot hiểu “mã này”, “ở đây”."""
    def _run():
        if key:
            st.session_state["current_page"] = key
        fn(get_ctx())
    return _run


def open_page(key: str, state: Optional[Dict] = None) -> None:
    """Chuyển sang trang `key` (và đặt sẵn giá trị). Gọi trong nhánh `if st.button(...)`."""
    for k, v in (state or {}).items():
        st.session_state[k] = v
    if key in PAGES:  # trang nâng cao bị ẩn ở chế độ đơn giản thì không chuyển
        st.switch_page(PAGES[key])


def _ver(symbol: str) -> Tuple[int, int]:
    """Phiên bản dữ liệu giá của một mã = thời điểm sửa + kích thước file CSV. File đổi (nút Cập nhật, lệnh Terminal, tiến trình khác)
    thì phiên bản đổi, nên MỌI trang tự đọc lại giá mới thay vì chờ bộ nhớ đệm hết hạn."""
    try:
        st_ = (data_mod.CSV_DIR / f"{symbol.upper()}.csv").stat()
        return (st_.st_mtime_ns, st_.st_size)
    except OSError:
        return (0, 0)


@st.cache_data(ttl=900, show_spinner=False)
def _load(symbol: str, ver: Tuple[int, int]):
    return get_prices(symbol)


@st.cache_data(ttl=900, show_spinner=False)
def _load_long(symbol: str, ver: Tuple[int, int]):
    return get_prices(symbol, 1500)


def load(symbol: str):
    """Giá gần đây của một mã: (bảng giá, nguồn). Cùng một phiên bản dữ liệu cho mọi trang."""
    return _load(symbol, _ver(symbol))


def load_long(symbol: str):
    """Toàn bộ lịch sử có sẵn (backtest và biểu đồ dài hạn cần nhiều năm)."""
    return _load_long(symbol, _ver(symbol))


@st.cache_data(ttl=900, show_spinner=False)
def _snapshot(symbols: Tuple[str, ...], vers: Tuple[Tuple[int, int], ...]):
    idx, idx_src = load("VNINDEX")
    out, srcs = [], {idx_src}
    for s in symbols:
        df, src = load(s)
        srcs.add(src)
        if len(df) < 2:
            continue
        sig = signals.score_stock(df, idx)
        last, prev = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        last_date = df["date"].iloc[-1]
        out.append({
            "symbol": s, "close": last, "prev": prev, "change": last / prev - 1, "score": sig.get("score"),
            "rsi": sig.get("rsi"), "vol_ratio": sig.get("vol_ratio"), "stop": sig.get("suggested_stop"),
            "stop_pct": sig.get("stop_pct"), "liquid": sig.get("liquid", False),
            "reasons": sig.get("reasons", []), "warnings": sig.get("warnings", []),
            "closes": df["close"].tail(60).tolist(), "last_date": last_date,
            "partial": explain.is_partial_session(last_date), "src": src,
        })
    return out, srcs


def snapshot(symbols: Tuple[str, ...]):
    """Tóm tắt từng mã: giá, thay đổi, điểm, cắt lỗ gợi ý, đường giá 60 phiên. Đổi theo phiên bản file giá của chính các mã đó và VN-Index."""
    symbols = tuple(symbols)
    return _snapshot(symbols, tuple(_ver(s) for s in ("VNINDEX",) + symbols))


def clear_price_caches() -> None:
    for fn in (_load, _load_long, _snapshot):
        fn.clear()


@st.cache_data(ttl=900, show_spinner=False)
def world_snapshot():
    try:
        return newsmod.fetch_global_snapshot()
    except Exception:  # noqa: BLE001
        return []


def strip_items() -> List[Tuple[str, str, Optional[float]]]:
    """Dải chỉ số đầu trang: VN-Index (dữ liệu của bạn) + thế giới (cache 15 phút)."""
    items: List[Tuple[str, str, Optional[float]]] = []
    try:
        df, src = load("VNINDEX")
        if src != "demo" and len(df) >= 2:
            items.append(("VN-Index", explain.num(float(df["close"].iloc[-1]), 2),
                          float(df["close"].iloc[-1] / df["close"].iloc[-2] - 1)))
    except Exception:  # noqa: BLE001
        pass
    short = {"Chỉ số USD (DXY)": "USD Index", "Lợi suất TP Mỹ 10Y": "TP Mỹ 10Y"}
    for g in world_snapshot():
        dec = 2
        items.append((short.get(g["name"], g["name"]), explain.num(g["last"], dec), g["change_pct"] / 100))
    return items


@st.cache_data(ttl=600, show_spinner=False)
def news_items():
    """Tin RSS, giữ 10 phút để các trang dùng chung, không gọi mạng mỗi lần bấm."""
    return newsmod.fetch_news()


def ai_ready() -> bool:
    return llm.has_key()


def ai_name() -> str:
    return {"anthropic": "Claude", "openai_compat": "Gemini/khác", "mock": "Chế độ thử (mẫu)"}.get(
        llm.provider(), llm.provider())
