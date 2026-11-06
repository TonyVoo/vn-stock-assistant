"""Trang Hỏi trợ lý: “giờ mua có ổn không hay nên đợi giá xuống?” trả lời bằng số, rồi hỏi thêm bằng chữ (AI, tuỳ chọn)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import ask, explain, llm, portfolio, risk, ui
from views import shared

PRESETS = ["Giờ mua có ổn không?", "Nên đợi giá xuống rồi mua không?", "Mua dần như thế nào để giá vốn đẹp hơn?"]


def _price_df(sym: str):
    try:
        df, src = shared.load_long(sym)
        return (None if src == "demo" else df)
    except Exception:  # noqa: BLE001
        return None


@st.fragment
def _ai_section(sym, f, h, qty, avg, budget, tr, weight_after, max_alloc, guide, rows, pf, ctx) -> None:
    # fragment: hỏi AI và stream câu trả lời chỉ chạy lại khối này, phần còn lại của trang không bị mờ/đứng
    ui.section("Hỏi AI", "AI nói thẳng quan điểm kèm lý do. Tin hay không là quyền của bạn")
    if not shared.ai_ready():
        st.caption("Chưa bật AI. Xem trang Hướng dẫn, mục “Bật AI”. Phần trả lời bằng số bên dưới vẫn dùng bình thường.")
        return
    cols = st.columns(len(PRESETS))
    for i, p in enumerate(PRESETS):
        if cols[i].button(p, key=f"ask_p{i}", width="stretch"):
            st.session_state["ask_q"] = p
    q = st.text_area("Câu hỏi của bạn", key="ask_q", placeholder="Ví dụ: Tôi đang lỗ 8%, có nên mua thêm để hạ giá vốn không?", max_chars=500)
    share = st.toggle("Cho AI biết danh mục và số tiền của tôi để trả lời sát hơn", key="ask_share", value=False,
                      help="Bật thì số tiền định mua, số cổ phiếu đang giữ, giá vốn, tiền mặt và vốn của bạn được gửi cho nhà cung cấp AI cùng câu hỏi. Tắt thì chỉ gửi số liệu thị trường và các tỷ lệ.")
    ask_now = st.button(":material/send: Hỏi AI", type="primary", key="ask_go", disabled=not q.strip())
    box = st.container()
    if ask_now:
        # Chỉ gửi số liệu thị trường của mã và tỷ lệ; số tiền, số lượng, vốn, danh mục CHỈ gửi khi bạn bật công tắc ở trên
        data = {"ma": sym, "gia_hien_tai": round(f["price"]), "so_voi_dinh_1_nam": round(f["from_high"], 3), "so_voi_trung_binh_50_phien": round(f["vs_ma50"], 3),
                "so_voi_trung_binh_200_phien": (round(f["price"] / f["ma200"] - 1, 3) if f["ma200"] else None), "rsi": round(f["rsi"]),
                "vi_tri_trong_vung_1_nam_0_den_1": round(f["pos_in_range"], 2), "chia_lan_mua": int(tr),
                "nhan_xet_cua_he_thong": [g["text"] for g in guide],
                "gia_von_moi_theo_cach_mua": [{"cach_mua": r["name"], "gia_von_trung_binh_moi_so_voi_mua_mot_lan": round(r["avg"] / rows[0]["avg"] - 1, 4)} for r in rows],
                "so_voi_gia_von_cua_nguoi_hoi": (round(f["price"] / avg - 1, 3) if h else None), "ty_trong_sau_khi_mua": round(weight_after, 3),
                "ty_trong_toi_da_nguoi_dung_dat": max_alloc}
        if share:
            data.update({"so_tien_dinh_mua": round(budget), "so_co_phieu_dang_giu": qty, "gia_von_binh_quan": round(avg), "tien_mat": round(pf["cash"]),
                         "von_cua_nguoi_dung": round(ctx.capital), "muc_chap_nhan_mat_moi_lenh_pct": st.session_state.get("risk_pct", 2.0)})
        with box:
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant"):
                try:
                    text = st.write_stream(llm.smooth(llm.chat_stream(q, [], data)))
                except Exception as e:  # noqa: BLE001
                    text = f"Mình chưa trả lời được ({type(e).__name__}). Bạn thử lại sau ít phút nhé."
                    st.markdown(text)
        st.session_state["ask_ans"] = (q, text if isinstance(text, str) else "".join(map(str, text)), bool(share))
    elif st.session_state.get("ask_ans"):
        saved = st.session_state["ask_ans"]
        with box:
            with st.chat_message("user"):
                st.markdown(saved[0])
            with st.chat_message("assistant"):
                st.markdown(saved[1])
    ans = st.session_state.get("ask_ans")
    if not ans:
        return
    st.caption("Đây là quan điểm của AI dựa trên số liệu ở trang này, không phải sự thật và không đảm bảo lợi nhuận; AI có thể sai. Bạn là người quyết định."
               + (" Danh mục và số tiền của bạn đã được gửi cho AI trong lần hỏi này." if ans[2] else " Lần hỏi này không gửi số tiền hay danh mục của bạn."))


def render(ctx) -> None:
    ui.page_header("Hỏi trợ lý", "Ví dụ: “Giờ mua cổ phiếu này có ổn không, hay đợi giá xuống?” Câu trả lời dựa trên số liệu, không đoán giá.")
    pf = portfolio.load()
    held = {h["symbol"]: h for h in pf["holdings"]}
    options = list(dict.fromkeys(list(held) + list(ctx.watchlist)))
    a, b, c = st.columns([1, 1, 1])
    sym = a.selectbox("Mã cổ phiếu bạn đang cân nhắc", options, key="ask_sym", accept_new_options=True)
    sym = (sym or "").upper().strip()
    budget = b.number_input("Số tiền định bỏ ra (đồng)", min_value=100_000.0, value=float(max(round(ctx.capital * 0.1, -5), 1_000_000)),
                            step=500_000.0, format="%.0f", key="ask_budget")
    b.caption(f"= {explain.vnd(budget)}")
    tr = c.radio("Chia làm mấy lần mua", [1, 2, 3, 4], index=2, horizontal=True, key="ask_tr",
                 help="1 nghĩa là mua hết một lần. Chia nhiều lần để giảm rủi ro mua đúng lúc giá cao.")
    df = _price_df(sym) if sym else None
    f = ask.facts(df) if df is not None else None
    if f is None:
        ui.callout("Chưa đủ dữ liệu giá thật cho mã này (cần ít nhất 60 phiên). Hãy bấm Cập nhật giá ở trang Tổng quan hoặc chọn mã khác.", "warn")
        return
    h = held.get(sym)
    qty, avg = (h["qty"], h["avg_cost"]) if h else (0, 0.0)
    total = pf["cash"] + sum((h2["avg_cost"] * h2["qty"]) for h2 in pf["holdings"]) or ctx.capital
    cost = budget
    weight_after = ((avg * qty if h else 0.0) + cost) / max(total, ctx.capital)
    max_alloc = st.session_state.get("max_alloc", 30) / 100

    guide = ask.guidance(f, qty, avg, weight_after, max_alloc)
    rows = ask.average_scenarios(f["price"], float(budget), int(tr), qty, avg)
    _ai_section(sym, f, h, qty, avg, budget, tr, weight_after, max_alloc, guide, rows, pf, ctx)

    ui.section("Trả lời nhanh bằng số", "Không đoán giá: chỉ cho bạn thấy giá đang ở đâu và mỗi cách mua làm giá vốn thay đổi ra sao")
    x1, x2, x3, x4 = st.columns(4)
    with x1:
        ui.stat_card("Giá hiện tại", explain.num(f["price"]) + "đ", f"phiên gần nhất của {sym}")
    with x2:
        ui.stat_card("So với đỉnh 1 năm", explain.pct(f["from_high"], 0), f"vùng 1 năm: {explain.num(f['low'])} đến {explain.num(f['high'])}")
    with x3:
        ui.stat_card("So với trung bình 50 phiên", explain.pct(f["vs_ma50"], 1), "dương: giá đang cao hơn mức trung bình gần đây", "up" if f["vs_ma50"] >= 0 else "down")
    with x4:
        ui.stat_card("Giá vốn của bạn", explain.num(avg) + "đ" if h else "Chưa giữ mã này", ("giá hiện tại " + explain.pct(f["price"] / avg - 1, 1) + " so với giá vốn") if h else "")
    for g in guide:
        ui.callout(g["text"], "warn" if g["level"] == "warn" else "info")

    ui.section("Giá vốn trung bình thay đổi thế nào?", "So sánh mua một lần với chia nhiều lần, trong 3 kịch bản giá (chỉ là minh hoạ)")
    base = rows[0]["avg"]
    st.dataframe(pd.DataFrame({"Cách mua": [r["name"] for r in rows], "Giá vốn trung bình mới": [explain.vnd(r["avg"]) for r in rows],
                               "So với mua một lần": ["" if i == 0 else explain.pct(r["avg"] / base - 1, 1) for i, r in enumerate(rows)],
                               "Số cổ phiếu (gần đúng)": [explain.num(r["qty"]) for r in rows]}), hide_index=True, width="stretch")
    st.caption("Âm nghĩa là giá vốn thấp hơn nếu mua một lần. Chia lần có lợi khi giá giảm và bất lợi khi giá tăng; bạn không biết trước kịch bản nào xảy ra. "
               "Số cổ phiếu tính gần đúng, thực tế phải mua theo lô 100.")

    sizing = risk.position_size(ctx.capital, f["price"], f["price"] * 0.93, st.session_state.get("risk_pct", 2.0) / 100, max_alloc)
    if "shares" in sizing and sizing["shares"] > 0 and budget > sizing["cost"]:
        ui.callout(f"Với mức cắt lỗ 7% dưới giá mua và mức chấp nhận mất {st.session_state.get('risk_pct', 2.0):.1f}% vốn, "
                   f"số tiền mua tối đa an toàn khoảng {explain.vnd(sizing['cost'])}. Bạn định bỏ {explain.vnd(budget)}, nhiều hơn mức đó. "
                   "Xem trang Tính lệnh mua để kiểm tra chi tiết.", "warn")
