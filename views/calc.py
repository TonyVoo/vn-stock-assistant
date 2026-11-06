"""Trang Tính lệnh mua: trả lời 'nên mua bao nhiêu cổ phiếu để an toàn?'."""
from __future__ import annotations

import streamlit as st

from src import explain, portfolio, precheck, risk, settings, ui
from views import shared

LIMIT_TEXT = {"rủi ro": "mua thêm sẽ vượt mức mất tối đa bạn chấp nhận",
              "tỷ trọng tối đa": "đã đạt tỷ lệ vốn tối đa cho một mã",
              "tiền mặt": "đã dùng hết số tiền bạn có"}


def _save_safety() -> None:
    """Lưu mức an toàn ngay khi đổi (widget bị xoá khi rời trang nên phải sao chép sang khoá bền vững + file)."""
    st.session_state["risk_pct"] = st.session_state["w_risk"]
    st.session_state["max_alloc"] = st.session_state["w_alloc"]
    settings.save(shared.current_settings())


def _price(sym: str):
    try:
        df, _ = shared.load(sym)
        return float(df["close"].iloc[-1]) if df is not None and len(df) else None
    except Exception:  # noqa: BLE001
        return None


def _traffic_light(ctx, entry, stop, target, recommended: int) -> None:
    """Đèn giao thông cho số cổ phiếu bạn THỰC SỰ định mua (mặc định là mức app tính)."""
    ui.section("Kiểm tra trước khi mua", "Đối chiếu với quy tắc an toàn của chính bạn")
    shares = int(st.number_input("Số cổ phiếu bạn định mua", 100, 10_000_000, int(recommended), 100, key=f"calc_plan_{recommended}",
                                 help="Mặc định là số tối đa app tính. Nhập số bạn thực sự định mua để kiểm tra."))
    pf = portfolio.load()
    sym = (st.session_state.get("calc_symbol") or "").upper()
    existing, total, cash = 0.0, ctx.capital, None
    if pf["holdings"] or pf["cash"] > 0:
        df, s = portfolio.valuate(pf, _price, st.session_state["max_alloc"] / 100)
        cash = pf["cash"]  # tổng tài sản vẫn lấy theo vốn ở Cài đặt, cùng cơ sở với số cổ phiếu app vừa tính ở trên
        if sym and len(df):
            existing = float(df.loc[df["symbol"] == sym, "value"].sum())
    avg_value = None
    if sym:
        d, _ = shared.load(sym)
        if d is not None and len(d) >= 5 and "volume" in d:
            avg_value = float((d["close"] * d["volume"]).tail(20).mean())
    r = precheck.check(entry, stop, target, shares, total, cash, existing, st.session_state["risk_pct"] / 100,
                       st.session_state["max_alloc"] / 100, avg_value)
    title, sub = precheck.TITLE[r["level"]]
    ui.callout(sub, {"ok": "good", "warn": "warn", "bad": "bad"}[r["level"]], title)
    rows = "".join(f'<div class="item"><div>{ui.badge({"ok": "Ổn", "warn": "Cân nhắc", "bad": "Vi phạm"}[i["level"]], {"ok": "up", "warn": "flat", "bad": "down"}[i["level"]])} '
                   f'<b>{ui.esc(i["label"])}</b></div><div class="d">{ui.esc(i["text"])}</div></div>' for i in r["items"])
    st.markdown(f'<div class="card">{rows}</div>', unsafe_allow_html=True)
    st.caption(f"Các tỷ lệ % tính theo vốn {explain.money_short(ctx.capital)} ở Cài đặt; tiền mặt lấy từ Danh mục.")
    if not sym:
        st.caption("Chưa biết mã cổ phiếu nên chưa kiểm tra được thanh khoản và tỷ trọng của chính mã này. Mở trang này từ trang Tra cứu để kiểm tra đầy đủ hơn.")


def render(ctx) -> None:
    ui.page_header("Tính lệnh mua", "Trả lời câu hỏi: “Tôi nên mua bao nhiêu cổ phiếu để nếu sai thì không mất quá nhiều?”")
    st.session_state.setdefault("calc_entry", 25000)
    st.session_state.setdefault("calc_stop", 23500)
    st.session_state.setdefault("calc_target", 29000)

    left, right = st.columns([5, 6], gap="large")
    with left:
        with st.container(border=True):
            sym = st.session_state.get("calc_symbol")
            st.markdown("**Bước 1. Nhập 3 mức giá**" + (f"  ·  mã **{sym}**" if sym else ""))
            st.caption("Nhập giá đầy đủ, ví dụ 25000 (không phải 25).")
            entry = st.number_input("Giá bạn định mua (đồng)", 1000, 2_000_000, step=50, key="calc_entry",
                                    help="Mức giá bạn dự định đặt lệnh mua.")
            stop = st.number_input("Giá bạn sẽ bán để cắt lỗ (đồng)", 1000, 2_000_000, step=50, key="calc_stop",
                                   help="Nếu giá rơi xuống mức này, bạn bán ngay để không lỗ sâu hơn. Phải thấp hơn giá mua.")
            target = st.number_input("Giá bạn hy vọng bán được lãi (đồng)", 1000, 2_000_000, step=50, key="calc_target",
                                     help="Mức giá mục tiêu để chốt lời. Phải cao hơn giá mua.")
        with st.expander(":material/tune: Điều chỉnh mức an toàn (tuỳ chọn)"):
            st.slider("Nếu lệnh này sai, tôi chấp nhận mất tối đa bao nhiêu % tổng vốn?", 0.5, 5.0, step=0.5,
                      value=float(st.session_state["risk_pct"]), key="w_risk", format="%.1f%%", on_change=_save_safety,
                      help="Người mới nên để 1–2%. Mức cao hơn nghĩa là một lệnh sai có thể làm mất nhiều tiền.")
            st.slider("Tối đa bao nhiêu % vốn được dồn vào một mã?", 10, 50, step=5,
                      value=int(st.session_state["max_alloc"]), key="w_alloc", format="%d%%", on_change=_save_safety,
                      help="Không nên bỏ hết trứng vào một giỏ. 30% nghĩa là một mã chiếm tối đa 3/10 số vốn.")
            st.caption("Thay đổi ở đây được lưu tự động.")
    with right:
        res = risk.position_size(ctx.capital, entry, stop, st.session_state["risk_pct"] / 100,
                                 st.session_state["max_alloc"] / 100)
        st.markdown("**Kết quả**")
        if "error" in res:
            msg = "Giá cắt lỗ phải THẤP hơn giá mua." if stop >= entry else res["error"]
            ui.callout(msg, "bad")
            return
        if res["shares"] == 0:
            ui.callout(res["message"], "warn", "Với số vốn này, lệnh này chưa phù hợp")
            st.caption("Mỗi lần mua phải mua theo “lô” tối thiểu 100 cổ phiếu. Có thể thử: chọn mã giá thấp hơn, "
                       "đặt mức cắt lỗ gần giá mua hơn, hoặc tăng mức % chấp nhận mất (cần cân nhắc kỹ).")
            return
        gain = res["shares"] * (target * (1 - risk.FEE_RATE - risk.SELL_TAX) - entry * (1 + risk.FEE_RATE))
        rr = risk.reward_risk(entry, stop, target)
        verdict = ("Hấp dẫn", "up") if rr >= 2 else ("Tạm được", "flat") if rr >= 1.5 else ("Chưa hấp dẫn", "down")
        st.markdown(
            f'<div class="card"><div class="bigsub">Bạn nên mua tối đa</div>'
            f'<div class="big">{explain.num(res["shares"])} cổ phiếu</div>'
            f'<div class="bigsub">tương đương {res["lots"]} lô · cần khoảng <b>{explain.vnd(res["cost"])}</b> '
            f'({explain.pct(res["alloc_pct"], 0, signed=False)} vốn của bạn)</div></div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        with a:
            st.markdown(f'<div class="card" style="border-color:#FECACA"><div class="hint">Nếu sai và chạm mức cắt lỗ</div>'
                        f'<div class="big" style="color:#B91C1C;font-size:1.5rem">−{explain.vnd(res["max_loss"])}</div>'
                        f'<div class="hint">≈ {explain.pct(res["max_loss_pct"], 1, signed=False)} tổng vốn</div></div>',
                        unsafe_allow_html=True)
        with b:
            st.markdown(f'<div class="card" style="border-color:#BBF7D0"><div class="hint">Nếu đúng và đạt giá mục tiêu</div>'
                        f'<div class="big" style="color:#15803D;font-size:1.5rem">+{explain.vnd(max(gain, 0))}</div>'
                        f'<div class="hint">đã trừ phí và thuế</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card">{ui.kv_rows([("Lãi tiềm năng so với lỗ tiềm năng", f"gấp {explain.num(rr, 1)} lần")])}'
                    f'<div style="padding:8px 0">{ui.badge(verdict[0], verdict[1])} '
                    f'<span class="hint">Người đầu tư kỷ luật thường chỉ vào lệnh khi lãi tiềm năng ≥ 2 lần lỗ tiềm năng.</span></div>'
                    f'{ui.kv_rows([("Giá phải đạt để hòa vốn (sau phí, thuế)", explain.vnd(res["breakeven"])), ("Không mua nhiều hơn vì", LIMIT_TEXT.get(res["limited_by"], res["limited_by"]))])}'
                    f'</div>', unsafe_allow_html=True)
        _traffic_light(ctx, entry, stop, target, res["shares"])
        lim = risk.price_limits(entry, "HOSE")
        st.caption(f"Cần biết: mua hôm nay thì 2 ngày làm việc sau mới bán được (quy định T+2). "
                   f"Trong một ngày, giá sàn HOSE chỉ được biến động trong khoảng {explain.vnd(lim['floor'])} – {explain.vnd(lim['ceiling'])} "
                   f"(±7%) so với giá tham chiếu.")
