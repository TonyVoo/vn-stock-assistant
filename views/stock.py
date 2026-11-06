"""Trang Tra cứu cổ phiếu: bố cục kiểu app chứng khoán (giá lớn, vùng giá 52 tuần, số liệu gọn, biểu đồ vùng)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import charts, explain, llm, news as newsmod, prompts, risk, signals, ui
from src.data import VN30_DEFAULT
from views import screener_view, shared


def _assessment(s: dict) -> str:
    t, h, a = explain.trend(s["score"]), explain.heat(s["rsi"]), explain.activity(s["vol_ratio"], s["partial"])
    liq = ("Tốt", "up") if s["liquid"] else ("Thấp", "down")
    rows = [("Xu hướng giá", t[0], t[1], t[2]), ("Mức độ nóng", h[0], h[1], h[2]),
            ("Lượng giao dịch", a[0], a[1], a[2]), ("Dễ mua/bán", liq[0], liq[1],
                                                    "Có đủ người giao dịch." if s["liquid"] else "Ít người giao dịch, có thể khó bán.")]
    body = "".join(f'<div class="r"><div><div class="k">{ui.esc(k)}</div><div class="hint">{ui.esc(tip)}</div></div>'
                   f'{ui.badge(label, kind)}</div>' for k, label, kind, tip in rows)
    return f'<div class="card assess"><div style="font-weight:700;margin-bottom:2px">Đánh giá nhanh</div>{body}</div>'


def _ret(df: pd.DataFrame, n: int):
    c = df["close"]
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None


def render(ctx) -> None:
    screener_view.render(ctx)
    options = sorted(set(ctx.watchlist) | set(VN30_DEFAULT))
    if st.session_state.get("symbol") not in options:
        st.session_state["symbol"] = options[0]
    top1, top2 = st.columns([1, 3])
    with top1:
        sym = st.selectbox("Chọn mã cổ phiếu", options, key="symbol",
                           help="Mã gồm 3 chữ cái, ví dụ FPT (FPT Corp), HPG (Hòa Phát), VCB (Vietcombank).")
    snaps, srcs = shared.snapshot((sym,))
    if not snaps:
        ui.callout("Chưa có dữ liệu cho mã này.", "bad")
        return
    s = snaps[0]
    if "demo" in srcs:
        ui.callout("Đây là dữ liệu GIẢ LẬP, không dùng để quyết định. Xem trang Tổng quan để biết cách tải dữ liệu thật.", "bad")
    df, _ = shared.load_long(sym)
    d = signals.add_indicators(df)

    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(border=True):
            tags = (["HOSE"] if sym in VN30_DEFAULT else []) + (["VN30"] if sym in VN30_DEFAULT else [])
            note = "Giá tạm thời (phiên chưa đóng cửa)" if s["partial"] else f"Giá đóng cửa ngày {s['last_date']:%d/%m/%Y}"
            diff = s["close"] - s["prev"]
            ui.price_hero(sym, tags, explain.num(s["close"]), ("+" if diff >= 0 else "-") + explain.num(abs(diff)), s["change"], note)
            rng = st.segmented_control("Khoảng thời gian", list(charts.RANGES), default="1 năm", key="st_range",
                                       label_visibility="collapsed") or "1 năm"
            show_ma = st.toggle("Hiện đường trung bình 50 và 200 phiên", value=False,
                                help="Giá trung bình của 50/200 ngày gần nhất. Giá nằm trên các đường này thường là dấu hiệu xu hướng tốt.")
            part = charts.slice_range(d, rng)
            kind = ui.change_kind(float(part["close"].iloc[-1] / part["close"].iloc[0] - 1))
            charts.price_chart(part, "close", kind, height=340,
                               overlays={"sma50": "Trung bình 50 phiên", "sma200": "Trung bình 200 phiên"} if show_ma else None)
    with right:
        hi, lo = float(df["high"].tail(250).max()), float(df["low"].tail(250).min())
        vol = float(df["volume"].iloc[-1])
        val20 = float((df["close"] * df["volume"]).tail(20).mean())
        r1, r3, r12 = _ret(df, 21), _ret(df, 63), _ret(df, 250)
        atr_pct = float(d["atr14"].iloc[-1] / s["close"])
        grid = ui.stat_grid([
            ("Khối lượng hôm nay", explain.num(vol) + (" (tạm thời)" if s["partial"] else "")),
            ("Giá trị giao dịch TB 20 phiên", explain.num(val20 / 1e9, 1) + " tỷ đồng"),
            ("Thay đổi 1 tháng", explain.pct(r1) if r1 is not None else "—"),
            ("Thay đổi 3 tháng", explain.pct(r3) if r3 is not None else "—"),
            ("Thay đổi 1 năm", explain.pct(r12) if r12 is not None else "—"),
            ("Dao động thường ngày", "±" + explain.pct(atr_pct, 1, signed=False)),
        ])
        st.markdown(f'<div class="card"><div style="font-weight:700">Vùng giá 1 năm</div>'
                    f'{ui.range_bar(lo, hi, s["close"], "Thấp nhất " + explain.num(lo), "Cao nhất " + explain.num(hi))}'
                    f'<div class="hint" style="margin:8px 0 16px 0">Chấm tròn là giá hiện tại nằm ở đâu trong vùng này.</div>{grid}</div>',
                    unsafe_allow_html=True)
        st.markdown(_assessment(s), unsafe_allow_html=True)

    ui.callout(explain.plain_summary(sym, s), "info", "Nói đơn giản")

    pos, neg = [], []
    for txt in s["reasons"] + s["warnings"]:
        p, pol = explain.plainify(txt)
        (pos if pol == "+" else neg).append(p)
    l, r = st.columns(2)
    with l:
        st.markdown("**Điểm thuận lợi**")
        st.markdown("\n".join(f"- {x}" for x in pos) if pos else "_Chưa có điểm thuận lợi nổi bật._")
    with r:
        st.markdown("**Điểm cần lưu ý**")
        st.markdown("\n".join(f"- {x}" for x in neg) if neg else "_Chưa có điểm đáng lo nổi bật._")

    if s["stop"]:
        entry = risk.round_to_tick(s["close"], "HOSE", "up")
        stop = risk.round_to_tick(s["stop"], "HOSE", "down")
        target = risk.round_to_tick(entry + 2 * (entry - stop), "HOSE", "up")
        with st.container(border=True):
            st.markdown("**Mức bán để tránh lỗ nặng (gọi là “cắt lỗ”)**")
            st.write(f"Nếu mua ở giá hiện tại, một mức tham khảo là **{explain.vnd(stop)}** "
                     f"(thấp hơn giá hiện tại {explain.pct(s['stop_pct'], 1, signed=False)}). "
                     "Nghĩa là nếu giá rơi tới mức này, bạn tự bán để không bị lỗ sâu hơn.")
            if st.button(":material/calculate: Tính xem nên mua bao nhiêu cổ phiếu", type="primary"):
                shared.open_page("calc", {"calc_symbol": sym, "calc_entry": int(entry),
                                          "calc_stop": int(stop), "calc_target": int(target)})

    with st.expander(":material/fact_check: Kiểm tra cơ bản bằng Claude + TCBS MCP (miễn phí, chỉ đọc)"):
        st.caption("Dùng khi bạn muốn biết doanh nghiệp có khoẻ không (lợi nhuận, nợ, định giá, khối ngoại) trước khi quyết định. "
                   "Việc này làm trong Claude của bạn, không qua app này.")
        ui.steps([
            f'Làm <b>một lần</b>: trong Claude (claude.ai hoặc Claude Desktop) vào Settings, Connectors, <b>Add custom connector</b>, '
            f'dán địa chỉ bên dưới rồi xác nhận bằng iOTP. <a href="{prompts.MCP_DOC}" target="_blank" rel="noopener noreferrer" '
            f'style="color:inherit;text-decoration:underline">Hướng dẫn chính thức của TCBS</a>.',
            "Bấm biểu tượng sao chép ở góc khung câu hỏi bên dưới.",
            "Dán vào một cuộc trò chuyện mới trong Claude và đọc kết quả."])
        st.markdown("**Địa chỉ TCBS MCP**")
        st.code(prompts.MCP_URL, language=None)
        st.markdown(f"**Câu hỏi soạn sẵn cho {sym}**")
        st.code(prompts.fundamental_prompt(sym, s["close"], f"{s['last_date']:%d/%m/%Y}"), language=None, wrap_lines=True)
        st.caption("Câu hỏi chỉ chứa mã và giá công khai, không có vốn hay danh mục của bạn. TCBS MCP chỉ đọc dữ liệu thị trường và "
                   "doanh nghiệp, không đặt lệnh. Muốn ngắt: TCInvest, ảnh đại diện, AI Connector, Hủy chia sẻ. "
                   "Claude có thể yêu cầu gói trả phí để dùng connector. Kết quả chỉ để tham khảo.")

    with st.expander(":material/smart_toy: Nhờ AI phân tích sâu hơn (đọc tin tức + nêu lý do không nên mua)"):
        if not shared.ai_ready():
            st.info("Chưa bật AI. Xem trang Hướng dẫn, mục “Bật AI”.")
        elif st.button("Phân tích bằng AI"):
            with st.spinner("AI đang đọc tin và số liệu..."):
                try:
                    items = newsmod.filter_news(newsmod.fetch_news(), [sym])
                    sig = signals.score_stock(df, shared.load("VNINDEX")[0])
                    st.session_state["analysis"] = (sym, llm.analyze_symbol(sym, sig, items))
                except Exception as e:  # noqa: BLE001
                    ui.callout(f"Không phân tích được ({type(e).__name__}). Thử lại sau.", "bad")
        an = st.session_state.get("analysis")
        if an and an[0] == sym:
            a_ = an[1]
            st.write(a_.get("tom_tat", ""))
            x, y = st.columns(2)
            x.markdown("**Lý do có thể mua**\n\n" + "\n".join(f"- {ui.esc(i)}" for i in a_.get("luan_diem_mua", [])))
            y.markdown("**Lý do nên cân nhắc kỹ**\n\n" + "\n".join(f"- {ui.esc(i)}" for i in a_.get("phan_bien", [])))
            if a_.get("dieu_kien_sai"):
                ui.callout(a_["dieu_kien_sai"], "warn", "Khi nào nhận định trên không còn đúng")
            st.caption("AI có thể sai và không biết hết thông tin. Đây là ý kiến tham khảo, không phải khuyến nghị.")
