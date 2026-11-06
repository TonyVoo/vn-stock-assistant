"""Nút “Cập nhật giá”: dùng ở Tổng quan (gọn), Cài đặt (đầy đủ) và màn hình chưa có dữ liệu."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

import streamlit as st

from src import explain, journal, portfolio, ui, updater
from src.data import VN30_DEFAULT
from views import shared

import os
import threading
import time

AUTO_MINUTES = 5            # chu kỳ tự cập nhật trong giờ giao dịch (nguồn dữ liệu có giới hạn tốc độ, không nên dày hơn)
_AUTO = {"last": 0.0, "last_ok": None, "lock": threading.Lock(), "running": False, "version": 0}  # dùng chung mọi phiên trình duyệt, tránh gọi nguồn song song
SECONDS_PER_SYMBOL = 4  # ước lượng gồm thời gian nghỉ để tránh giới hạn tốc độ


def targets(ctx, include_vn30: bool = False) -> List[str]:
    """Mã cần cập nhật: chỉ số, danh sách theo dõi, mã đang giữ (Danh mục + Nhật ký), và tuỳ chọn cả VN30."""
    syms = ["VNINDEX"] + list(ctx.watchlist)
    syms += [h["symbol"] for h in portfolio.load()["holdings"]]
    t = journal.list_trades()
    if not t.empty:
        syms += list(t[t["exit_price"].isna()]["symbol"])
    if include_vn30:
        syms += VN30_DEFAULT
    seen, out = set(), []
    for s in syms:
        s = str(s).upper().strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _line(r: Dict) -> str:
    if r["status"] == "ok":
        tail = f", đến {r['last_date']:%d/%m/%Y}" if r["last_date"] is not None else ""
        return f"thêm {r['added']} phiên{tail}" + (f". {r['note']}" if r["note"] else "")
    return r["status"] + (f". {r['note']}" if r["note"] else "")


def _run(symbols: List[str]) -> List[Dict]:
    """Chạy cập nhật có tiến độ ngay trên màn hình. Lỗi từng mã được báo, không dừng cả đợt."""
    n = len(symbols)
    with st.status(f"Đang cập nhật giá {n} mã (khoảng {n * SECONDS_PER_SYMBOL} giây)...", expanded=True) as status:
        bar = st.progress(0.0)

        def cb(i: int, total: int, r: Dict) -> None:
            bar.progress(i / total, text=f"{i}/{total} · {r['symbol']}")
            st.write(f"**{r['symbol']}**: {_line(r)}")

        results = updater.update_many(symbols, progress=cb)
        status.update(label="Đã xong", state="complete", expanded=False)
    return results


def _store_result(results: List[Dict]) -> None:
    good = [r for r in results if r["status"] in ("ok", "không có dữ liệu mới")]
    bad = [r for r in results if r not in good]
    dates = [r["last_date"] for r in results if r["last_date"] is not None]
    msg = f"Đã cập nhật {len(good)}/{len(results)} mã." + (f" Dữ liệu mới nhất đến hết phiên {max(dates):%d/%m/%Y}." if dates else "")
    lines = [f"{r['symbol']}: {_line(r)}" for r in bad[:6]] + ([f"... và {len(bad) - 6} mã khác" ] if len(bad) > 6 else [])
    st.session_state["upd_result"] = ("warn" if bad else "good", msg, lines)
    shared.clear_price_caches()  # (cách chính để trang đổi theo là phiên bản file giá; xoá thêm cho chắc)


def show_result() -> None:
    res = st.session_state.pop("upd_result", None)
    if res:
        kind, msg, lines = res
        ui.callout(msg + ("\n" + "\n".join(lines) if lines else ""), kind)


def in_trading_hours(now=None) -> bool:
    now = now or dt.datetime.now(explain.VN_TZ)
    return now.weekday() < 5 and dt.time(9, 0) <= now.time() <= dt.time(15, 5)


def auto_status() -> str:
    if not st.session_state.get("auto_price", True):
        return "Tự động cập nhật giá: đang tắt (bật ở Cài đặt)."
    ok = _AUTO["last_ok"]
    when = f" Lần gần nhất: {ok:%H:%M}." if ok else ""
    if in_trading_hours():
        return f"Tự động cập nhật giá mỗi {AUTO_MINUTES} phút trong giờ giao dịch.{when}"
    return "Ngoài giờ giao dịch (9:00 đến 15:05, thứ Hai đến thứ Sáu): giá không đổi nên không tự cập nhật." + when


def inbox_tick() -> None:
    """Quét thư mục sao kê; kết quả hiện thành thông báo nổi (một lần). Gọi ở mỗi lần chạy trang, tự giới hạn tần suất."""
    from src import inbox
    msgs = st.session_state.setdefault("inbox_msgs", [])
    for r in inbox.scan_throttled():
        msgs.append(r)
    while msgs:
        r = msgs.pop(0)
        if r["ok"]:
            st.toast(f"Đã tự nhập sao kê: {r['summary']}", icon=":material/check_circle:")
        else:
            st.toast(f"Chưa nhập được {r.get('file', 'file')}: {r['error']}", icon=":material/warning:")


def _auto_worker(symbols: List[str]) -> None:
    """Chạy trong luồng nền: tải giá rồi đánh dấu có dữ liệu mới. Không đụng vào giao diện Streamlit."""
    try:
        results = updater.update_many(symbols)
        if any(r["status"] == "ok" for r in results):
            _AUTO["last_ok"] = dt.datetime.now(explain.VN_TZ)
            _AUTO["version"] += 1
    except Exception:  # noqa: BLE001
        pass
    finally:
        _AUTO["running"] = False


AUTO_TICK = os.getenv("AUTO_TICK", "1m")  # chu kỳ kiểm tra của khung tự cập nhật (đổi để thử nghiệm)


@st.fragment(run_every=AUTO_TICK)
def auto_refresh(ctx) -> None:
    """Mỗi phút kiểm tra: nếu đang giờ giao dịch và đã đủ AUTO_MINUTES phút thì bắt đầu tải giá ở LUỒNG NỀN (trang không bị chặn);
    khi luồng nền xong thì làm mới trang. Đây là cập nhật định kỳ (gần thời gian thực), không phải dữ liệu từng giây.
    Mốc thời gian và cờ dùng chung mọi phiên trình duyệt nên mở nhiều tab/lần tải lại không gọi dồn nguồn dữ liệu."""
    from src import inbox
    new = inbox.scan_throttled()  # trang đang mở mà bạn vừa thả sao kê vào thư mục: tự đọc và làm mới
    if new:
        st.session_state.setdefault("inbox_msgs", []).extend(new)
        if st.session_state.get("chat_busy_until", 0.0) <= time.time():
            st.rerun()
    if not st.session_state.get("auto_price", True) or not in_trading_hours():
        return
    seen = st.session_state.get("_auto_seen", _AUTO["version"])
    st.session_state["_auto_seen"] = _AUTO["version"]
    if _AUTO["version"] != seen:  # luồng nền đã tải xong dữ liệu mới từ lần kiểm tra trước
        if st.session_state.get("chat_busy_until", 0.0) > time.time():
            st.session_state["_auto_seen"] = seen  # đang chat: không làm mới cả trang lúc này (sẽ cắt ngang câu trả lời), thử lại lần kiểm tra sau
        else:
            shared.clear_price_caches()
            st.rerun()
    if _AUTO["running"] or time.time() - _AUTO["last"] < AUTO_MINUTES * 60 - 15:
        return
    with _AUTO["lock"]:
        if _AUTO["running"]:
            return
        _AUTO["running"], _AUTO["last"] = True, time.time()
    threading.Thread(target=_auto_worker, args=(targets(ctx),), daemon=True).start()


def _market_note() -> None:
    now = dt.datetime.now(explain.VN_TZ)
    if now.weekday() < 5 and dt.time(9, 0) <= now.time() < dt.time(15, 5):
        st.caption("Phiên đang giao dịch: giá hôm nay chỉ là tạm thời. Cập nhật sau 15:05 để có giá đóng cửa.")


def _last_date_text() -> str:
    d = updater.last_data_date(["VNINDEX"])
    return f"Dữ liệu giá đến hết phiên {d:%d/%m/%Y}." if d is not None else "Chưa có dữ liệu giá."


def render_compact(ctx) -> None:
    """Một dòng + nút ở trang Tổng quan."""
    show_result()
    syms = targets(ctx)
    c1, c2 = st.columns([4, 1])
    with c1:
        st.caption(_last_date_text() + " " + auto_status())
    with c2:
        go = st.button(":material/sync: Cập nhật giá", key="upd_compact", width="stretch",
                       help=f"Lấy giá mới cho {len(syms)} mã (chỉ số, danh sách theo dõi, mã đang giữ). Khoảng {len(syms) * SECONDS_PER_SYMBOL} giây.")
    if go:
        _store_result(_run(syms))
        st.rerun()
    _market_note()


def render_panel(ctx, default_vn30: bool = False) -> None:
    """Phần đầy đủ (Cài đặt và màn hình chưa có dữ liệu)."""
    show_result()
    st.markdown("**Cập nhật giá**")
    st.caption(_last_date_text() + " Chỉ tải phần mới và gộp vào dữ liệu hiện có, nên nhanh và không làm mất lịch sử.")
    all30 = st.checkbox("Cập nhật cả 30 mã VN30 (lâu hơn)", value=default_vn30, key=f"upd_vn30_{default_vn30}")
    syms = targets(ctx, include_vn30=all30)
    go = st.button(f":material/sync: Cập nhật giá {len(syms)} mã", type="primary", key=f"upd_panel_{default_vn30}",
                   help=f"Khoảng {len(syms) * SECONDS_PER_SYMBOL} giây. Mã chưa có dữ liệu sẽ tải khoảng {updater.YEARS_FULL} năm.")
    if go:
        _store_result(_run(syms))
        st.rerun()
    _market_note()
    st.caption("Cần vnstock đã đăng ký (lệnh `vnstock register`, xem trang Hướng dẫn). Tài khoản Khách chỉ có 365 ngày giá cổ phiếu: app sẽ không xoá lịch sử dài đã có.")
