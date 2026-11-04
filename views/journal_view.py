"""Trang Nhật ký giao dịch."""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd
import streamlit as st

from src import explain, journal, ui
from views import shared


def _reason_text(r) -> str:
    c = _clean_reason(r)
    return "Chưa ghi lý do mua (bấm “Bổ sung lý do và cắt lỗ” bên dưới)" if (not c or c.startswith(journal.PLACEHOLDER_REASON)) else c


def _clean_reason(r) -> str:
    return re.sub(r"\[sao kê [0-9a-f]{10}\]\s*", "", str(r or ""))


def _nz(x, default=0.0) -> float:
    return default if x is None or x != x else float(x)


def _toast(msg: str) -> None:
    st.toast(msg, icon=":material/check_circle:")


def _quick_form(t) -> None:
    """Sửa nhanh một lệnh đang giữ: lý do, cắt lỗ, mục tiêu."""
    tid = int(t["id"])
    clean = _clean_reason(t["reason"])
    placeholder = clean.startswith(journal.PLACEHOLDER_REASON)
    with st.form(f"jq_{tid}"):
        reason = st.text_area("Vì sao bạn mua?", value="" if placeholder else clean, key=f"jq_reason_{tid}",
                              placeholder="Ví dụ: Xu hướng tăng, doanh nghiệp công bố lợi nhuận tốt...")
        a, b = st.columns(2)
        stop = a.number_input("Giá cắt lỗ (đồng, 0 = chưa đặt)", min_value=0.0, value=_nz(t["stop"]), step=50.0, format="%.0f",
                              key=f"jq_stop_{tid}", help="Mức giá bạn tự bán để không lỗ sâu hơn. Thường thấp hơn giá mua; nếu giá đã tăng, có thể kéo lên trên giá mua để giữ lại phần lãi.")
        target = b.number_input("Giá mục tiêu (đồng, 0 = bỏ trống)", min_value=0.0, value=_nz(t["target"]), step=50.0, format="%.0f",
                                key=f"jq_target_{tid}", help="Mức giá bạn hy vọng chốt lãi. Phải cao hơn giá mua.")
        if st.form_submit_button("Lưu", type="primary"):
            try:
                journal.update_trade(tid, reason=reason, stop=stop, target=target)
            except ValueError as e:
                st.error(str(e))
            else:
                _toast(f"Đã cập nhật lệnh {t['symbol']} #{tid}")
                st.rerun()


def _full_editor(trades: pd.DataFrame) -> None:
    """Sửa mọi trường của một lệnh (đang giữ hoặc đã bán), mở lại lệnh bán nhầm, hoặc xoá lệnh."""
    ui.section("Sửa hoặc xoá một lệnh", "Dùng khi nhập sai hoặc cần chỉnh ngày, giá, số lượng")
    rows = trades.sort_values("id", ascending=False)
    labels = {f"#{int(r.id)} · {r.symbol} · {int(r.qty)} cp · mua {explain.vnd(r.entry)} · {r.opened} · "
              f"{'đã bán' if pd.notna(r.exit_price) else 'đang giữ'}": int(r.id) for r in rows.itertuples()}
    pick = st.selectbox("Chọn lệnh", list(labels), key="je_pick")
    tid = labels[pick]
    t = journal.get_trade(tid)
    if t is None:
        return
    closed = t["exit_price"] is not None
    with st.form(f"je_form_{tid}"):
        c1, c2, c3 = st.columns(3)
        symbol = c1.text_input("Mã cổ phiếu", value=t["symbol"], key=f"je_sym_{tid}")
        qty = c2.number_input("Số lượng", min_value=1, value=int(t["qty"]), step=100, key=f"je_qty_{tid}")
        entry = c3.number_input("Giá mua (đồng)", min_value=0.0, value=_nz(t["entry"]), step=50.0, format="%.0f", key=f"je_entry_{tid}")
        c4, c5, c6 = st.columns(3)
        stop = c4.number_input("Giá cắt lỗ (0 = chưa đặt)", min_value=0.0, value=_nz(t["stop"]), step=50.0, format="%.0f", key=f"je_stop_{tid}")
        target = c5.number_input("Giá mục tiêu (0 = bỏ trống)", min_value=0.0, value=_nz(t["target"]), step=50.0, format="%.0f", key=f"je_target_{tid}")
        opened = c6.text_input("Ngày mua (YYYY-MM-DD hoặc “Không rõ”)", value=t["opened"], key=f"je_opened_{tid}")
        clean = _clean_reason(t["reason"])
        reason = st.text_area("Vì sao bạn mua?", value="" if clean.startswith(journal.PLACEHOLDER_REASON) else clean, key=f"je_reason_{tid}")
        extra = {}
        if closed:
            c7, c8, c9 = st.columns(3)
            extra["exit_price"] = c7.number_input("Giá bán (đồng)", min_value=0.0, value=_nz(t["exit_price"]), step=50.0, format="%.0f", key=f"je_exit_{tid}")
            extra["closed"] = c8.text_input("Ngày bán (YYYY-MM-DD)", value=t["closed"] or "", key=f"je_closed_{tid}")
            extra["note"] = c9.text_input("Bài học rút ra", value=t["note"] or "", key=f"je_note_{tid}")
        if st.form_submit_button("Lưu thay đổi", type="primary"):
            try:
                journal.update_trade(tid, symbol=symbol, qty=qty, entry=entry, stop=stop, target=target, opened=opened, reason=reason, **extra)
            except ValueError as e:
                st.error(str(e))
            else:
                _toast(f"Đã lưu thay đổi lệnh #{tid}")
                st.rerun()
    c1, c2 = st.columns(2)
    with c1:
        if closed and st.button("Mở lại lệnh này (xoá thông tin bán)", key=f"je_reopen_{tid}",
                                help="Dùng khi bạn bấm “đã bán” nhầm. Lệnh quay về trạng thái đang giữ."):
            journal.reopen_trade(tid)
            _toast(f"Đã mở lại lệnh #{tid}")
            st.rerun()
    with c2:
        ok = st.checkbox("Tôi chắc chắn muốn xoá lệnh này", key=f"je_del_ok_{tid}")
        if st.button("Xoá lệnh", key=f"je_del_{tid}", disabled=not ok):
            journal.delete_trade(tid)
            _toast(f"Đã xoá lệnh #{tid}")
            st.rerun()


def _last_price(sym: str):
    try:
        df, src = shared.load(sym)
        return float(df["close"].iloc[-1]) if src != "demo" and len(df) else None
    except Exception:  # noqa: BLE001
        return None


def render(ctx) -> None:
    ui.page_header("Nhật ký giao dịch",
                   "Ghi lại mỗi lần mua/bán cùng lý do. Đây là cách tốt nhất để học từ chính mình và tránh lặp lại sai lầm.")
    trades = journal.list_trades()
    done = trades[trades["pnl"].notna()] if not trades.empty else trades
    if not trades.empty and len(done):
        s = journal.stats(trades)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            ui.stat_card("Lệnh đã bán", f"{s['closed']} lệnh")
        with c2:
            ui.stat_card("Tỷ lệ lệnh có lãi", explain.pct(s["win_rate"], 0, signed=False))
        with c3:
            ui.stat_card("Tổng lãi/lỗ", explain.vnd(s["total_pnl"]), "", "up" if s["total_pnl"] > 0 else "down")
        with c4:
            ui.stat_card("Lãi/lỗ so với mức rủi ro đặt ra", f"{explain.num(s['avg_r'], 2)} lần" if s["avg_r"] is not None else "Chưa tính được",
                         "Trung bình mỗi lệnh. Dương là tốt." if s["avg_r"] is not None else "Cần lệnh đã đặt mức cắt lỗ.")

    with st.expander(":material/add: Ghi một lệnh mua mới", expanded=trades.empty):
        st.caption("Viết lý do TRƯỚC khi biết kết quả. Nếu chưa viết được lý do rõ ràng thì có thể bạn chưa nên mua.")
        with st.form("new_trade", clear_on_submit=True):
            a, b = st.columns(2)
            sym = a.text_input("Mã cổ phiếu", placeholder="Ví dụ: FPT").upper().strip()
            qty = b.number_input("Số lượng cổ phiếu", 100, 1_000_000, 100, step=100, help="Mua theo lô 100 cổ phiếu.")
            c, d, e = st.columns(3)
            entry = c.number_input("Giá mua (đồng)", 1000, 2_000_000, 25000, step=50)
            stop = d.number_input("Giá cắt lỗ (đồng)", 1000, 2_000_000, 23500, step=50)
            target = e.number_input("Giá mục tiêu (đồng, có thể bỏ trống = 0)", 0, 2_000_000, 0, step=50)
            reason = st.text_area("Vì sao bạn mua? (bắt buộc)", placeholder="Ví dụ: Xu hướng tăng, doanh nghiệp công bố lợi nhuận tốt...")
            if st.form_submit_button("Lưu lệnh", type="primary"):
                if not sym or not reason.strip():
                    st.error("Cần nhập mã và lý do mua.")
                elif stop >= entry:
                    st.error("Giá cắt lỗ phải thấp hơn giá mua.")
                else:
                    journal.add_trade(sym, int(qty), float(entry), float(stop), float(target) or None, reason.strip(),
                                      dt.date.today().isoformat())
                    _toast(f"Đã lưu lệnh {sym}")
                    st.rerun()

    if trades.empty:
        ui.callout("Chưa có lệnh nào. Khi bạn mua cổ phiếu thật, hãy ghi vào đây. Nếu bạn có file lịch sử giao dịch (sao kê lệnh khớp) "
                   "xuất từ công ty chứng khoán, có thể nhập một lần: vào trang Danh mục, tab “Nhập từ file”, rồi chọn thêm vào Nhật ký.", "info")
        from src import importer, portfolio
        held = portfolio.load()["holdings"]
        todo = importer.holdings_to_trades(held, importer.open_symbols())
        if todo:
            st.markdown(f"Danh mục của bạn đang có **{len(todo)} mã** chưa có trong Nhật ký.")
            if st.button(f"Thêm {len(todo)} mã từ Danh mục vào Nhật ký", type="primary", key="jr_sync_pf"):
                r = importer.to_journal(todo)
                st.toast(f"Đã thêm {r['open']} lệnh đang giữ vào Nhật ký", icon=":material/check_circle:")
                st.rerun()
        if st.button("Đi tới trang Danh mục để nhập file", key="jr_go_pf"):
            shared.open_page("portfolio")
        return

    open_t = trades[trades["exit_price"].isna()]
    if len(open_t):
        st.markdown("### Lệnh đang giữ")
        for _, t in open_t.iterrows():
            last = _last_price(t["symbol"])
            note, kind, line = "", "muted", "Chưa có giá hiện tại."
            if last:
                pnl = (last - t["entry"]) * t["qty"]
                kind = "up" if pnl > 0 else "down" if pnl < 0 else "flat"
                line = f"Giá hiện tại {explain.vnd(last)} · đang {'lãi' if pnl >= 0 else 'lỗ'} {explain.vnd(abs(pnl))} " \
                       f"({explain.pct(last / t['entry'] - 1, 1)})"
                if t["stop"] > 0 and last <= t["stop"] * 1.03:
                    note = ui.badge("Gần mức cắt lỗ" if last > t["stop"] else "Đã chạm mức cắt lỗ", "down")
            st.markdown(f'<div class="card"><div style="display:flex;justify-content:space-between;flex-wrap:wrap">'
                        f'<div><b style="font-size:1.15rem">{ui.esc(t["symbol"])}</b> · {int(t["qty"])} cổ phiếu · mua {explain.vnd(t["entry"])} '
                        f'ngày {ui.esc(t["opened"])} {note}</div><div class="hint">{"Cắt lỗ " + explain.vnd(t["stop"]) if t["stop"] > 0 else "Chưa đặt mức cắt lỗ"}</div></div>'
                        f'<div class="stat"><div class="sub {kind}" style="font-size:.95rem">{ui.esc(line)}</div></div>'
                        f'<div class="hint" style="margin-top:6px">Lý do mua: {ui.esc(_reason_text(t["reason"]))}</div></div>', unsafe_allow_html=True)
            with st.expander(f":material/edit_note: Bổ sung lý do và cắt lỗ · {t['symbol']} #{int(t['id'])}"):
                _quick_form(t)
            with st.expander(f"Bán / đóng lệnh {t['symbol']} #{int(t['id'])}"):
                with st.form(f"close_{int(t['id'])}"):
                    p = st.number_input("Giá bán (đồng)", 1000, 2_000_000, int(last) if last else int(t["entry"]), step=50)
                    n = st.text_input("Bài học rút ra (tuỳ chọn)")
                    if st.form_submit_button("Xác nhận đã bán"):
                        journal.close_trade(int(t["id"]), float(p), dt.date.today().isoformat(), n)
                        _toast(f"Đã đóng lệnh {t['symbol']} #{int(t['id'])}")
                        st.rerun()

    closed = trades[trades["exit_price"].notna()].copy()
    if len(closed):
        st.markdown("### Lệnh đã bán")
        closed["pct"] = closed["exit_price"] / closed["entry"] - 1
        closed["reason"] = closed["reason"].map(_clean_reason)
        view = closed[["symbol", "opened", "closed", "qty", "entry", "exit_price", "pnl", "pct", "reason", "note"]].rename(columns={
            "symbol": "Mã", "opened": "Ngày mua", "closed": "Ngày bán", "qty": "Số lượng", "entry": "Giá mua",
            "exit_price": "Giá bán", "pnl": "Lãi/lỗ (đồng)", "pct": "Lãi/lỗ (%)", "reason": "Lý do mua", "note": "Bài học"})
        sty = (view.style.format({"Giá mua": "{:,.0f}", "Giá bán": "{:,.0f}", "Lãi/lỗ (đồng)": "{:+,.0f}", "Lãi/lỗ (%)": "{:+.1%}"})
               .map(lambda v: "color:#15803D;font-weight:700" if v > 0 else "color:#B91C1C;font-weight:700",
                    subset=["Lãi/lỗ (đồng)", "Lãi/lỗ (%)"]))
        st.dataframe(sty, hide_index=True, width="stretch")

    _full_editor(trades)
