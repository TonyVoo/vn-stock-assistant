"""Trang Nghiên cứu (nâng cao): kiểm chứng các chiến lược bằng dữ liệu quá khứ."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st

from src import backtest, explain, paper, risk, ui, xsection
from src.data import VN30_DEFAULT
from views import shared


def _verdict_card() -> None:
    st.markdown(
        '<div class="card"><div style="font-weight:800;font-size:1.15rem;margin-bottom:6px">Kết luận hiện tại: chưa có “công thức thắng thị trường”</div>'
        '<div class="hint" style="font-size:.95rem">Chúng tôi đã thử hơn 100 cách chọn cổ phiếu bằng dữ liệu gần 8 năm của 30 mã lớn, '
        'mua ở giá thực tế của phiên kế tiếp và đã trừ phí, thuế. Kết quả:</div>'
        '<div class="item"><div class="t">Chấm điểm xu hướng từng mã</div><div class="d">Không tốt hơn việc mua ngẫu nhiên. '
        'Điểm cao hay thấp không báo trước giá sẽ tăng hay giảm.</div></div>'
        '<div class="item"><div class="t">Chọn 5 mã tăng mạnh nhất 6–12 tháng (“động lượng”)</div><div class="d">Trên giấy hơn giữ đều khoảng 7%/năm, '
        'nhưng độ chắc chắn thấp (có thể chỉ do may mắn). Khi chỉ xét những mã mà vốn 10 triệu mua nổi thì lợi thế <b>biến mất</b>.</div></div>'
        '<div class="item"><div class="t">Mua mã vừa giảm mạnh trong tuần</div><div class="d">Thua rõ rệt, chủ yếu vì phí giao dịch.</div></div>'
        '<div class="item"><div class="t">Điều này có nghĩa gì?</div><div class="d">Hãy dùng app như một công cụ giúp bạn <b>giữ kỷ luật và quản lý rủi ro</b>, '
        'không phải máy đoán giá. Đừng tin vào bất cứ “tín hiệu thần kỳ” nào chưa được kiểm chứng như thế này.</div></div></div>',
        unsafe_allow_html=True)


def _load_universe():
    prices, srcs = {}, set()
    for s in VN30_DEFAULT:
        d, src = shared.load_long(s)
        prices[s] = d
        srcs.add(src)
    idx, isrc = shared.load_long("VNINDEX")
    return prices, idx, srcs | {isrc}


def _tab_score() -> None:
    st.markdown("**Câu hỏi:** nếu mỗi lần mua mã có điểm xu hướng cao, kết quả có tốt hơn mua ngẫu nhiên không?")
    st.caption("Mô phỏng từng phiên trong quá khứ: mua ở giá mở cửa ngày hôm sau, tự bán khi giá giảm tới mức cắt lỗ "
               "hoặc sau một thời gian giữ, đã trừ phí và thuế.")
    with st.expander(":material/tune: Tuỳ chỉnh (không bắt buộc)"):
        thr = st.slider("Chỉ mua khi điểm từ", 50, 95, 70, 5)
        hold = st.slider("Giữ tối đa (phiên giao dịch)", 5, 60, 20, 5)
        atr = st.slider("Mức cắt lỗ (số lần biên độ dao động thông thường)", 1.0, 4.0, 2.0, 0.5)
    if st.button(":material/play_arrow: Chạy kiểm chứng", type="primary", key="run_bt"):
        with st.spinner("Đang mô phỏng, khoảng 20–40 giây..."):
            prices, idx, srcs = _load_universe()
            st.session_state["bt"] = (backtest.compare_with_baseline(prices, idx, threshold=thr, hold_days=hold, atr_mult=atr), srcs)
    if "bt" in st.session_state:
        (strat, base, s1, s2), srcs = st.session_state["bt"]
        if "demo" in srcs:
            ui.callout("Có dữ liệu giả lập, kết quả vô nghĩa.", "bad")
        if s1.get("trades", 0) == 0:
            ui.callout("Không có lệnh nào. Hãy hạ mức điểm.", "warn")
        else:
            edge = s1["avg_ret"] - s2["avg_ret"]
            if edge > 0.003 and s1["trades"] >= 30:
                ui.callout(f"Trên dữ liệu này, mua theo điểm cao hơn mua ngẫu nhiên {explain.pct(edge, 2)} mỗi lệnh. "
                           "Vẫn chưa chắc chắn (xem phần kiểm tra gắt hơn bên dưới).", "good")
            else:
                ui.callout(f"Mua theo điểm cao KHÔNG tốt hơn mua ngẫu nhiên đáng kể (chênh {explain.pct(edge, 2)} mỗi lệnh). "
                           "Điểm xu hướng chưa chứng minh được giá trị dự báo.", "warn")
            st.dataframe(pd.DataFrame([
                {"Cách mua": "Theo điểm cao", "Số lệnh": s1["trades"], "Lệnh có lãi": explain.pct(s1["win_rate"], 0, False),
                 "Lãi trung bình mỗi lệnh": explain.pct(s1["avg_ret"], 2)},
                {"Cách mua": "Ngẫu nhiên (mốc so sánh)", "Số lệnh": s2["trades"], "Lệnh có lãi": explain.pct(s2["win_rate"], 0, False),
                 "Lãi trung bình mỗi lệnh": explain.pct(s2["avg_ret"], 2)}]), hide_index=True, width="stretch")
    with st.expander(":material/science: Kiểm tra gắt hơn: thử 108 cách rồi xem còn đúng với dữ liệu mới không"):
        st.caption("Chia dữ liệu làm hai phần. Chọn cách tốt nhất ở phần CŨ, rồi xem nó có còn tốt ở phần MỚI mà nó chưa từng thấy. "
                   "Đây là cách phát hiện những kết quả chỉ đẹp do may mắn.")
        cut = st.date_input("Ngày chia dữ liệu", dt.date(2025, 1, 1), key="cut1")
        if st.button("Chạy kiểm tra gắt hơn", key="run_split"):
            with st.spinner("Đang chạy 108 cách..."):
                prices, idx, srcs = _load_universe()
                st.session_state["split"] = (backtest.split_evaluation(backtest.prepare_all(prices, idx), pd.Timestamp(cut)), srcs)
        if "split" in st.session_state:
            res, srcs = st.session_state["split"]
            el = res[res["eligible"]]
            if el.empty:
                ui.callout("Không đủ số lệnh ở phần dữ liệu cũ. Hãy lùi ngày chia về sau.", "warn")
            else:
                best = el.iloc[0]
                if el["test_z"].max() < 2:
                    ui.callout(f"Không cách nào qua được kiểm tra: ngay cả cách tốt nhất ở dữ liệu cũ cũng chỉ cho kết quả "
                               f"{explain.pct(best['test_edge'], 2)}/lệnh ở dữ liệu mới, và độ chắc chắn rất thấp (z = {explain.num(best['test_z'], 1)}; "
                               "cần ít nhất khoảng 2). Chưa có bằng chứng nên dùng điểm này để mua.", "warn")
                else:
                    ui.callout("Có cách vượt ngưỡng ở dữ liệu mới. Vẫn cần thử thêm giai đoạn khác trước khi tin.", "info")
                st.caption(f"Trung bình mọi cách thử ở dữ liệu mới: {explain.pct(el['test_edge'].mean(), 2)}/lệnh so với mua ngẫu nhiên.")


def _tab_momentum(ctx) -> None:
    st.markdown("**Ý tưởng:** mỗi tháng chọn vài mã đã tăng mạnh nhất trong 6–12 tháng qua, giữ 1 tháng rồi xếp hạng lại.")
    ui.callout("Chưa được chứng minh là hiệu quả. Trên giấy hơn giữ đều ~7%/năm nhưng độ chắc chắn thấp, "
               "và biến mất khi chỉ xét mã vốn 10 triệu mua nổi. Dùng phần này để THEO DÕI và GIẢ LẬP, không phải để mua thật.", "bad")
    prices = {}
    for s in VN30_DEFAULT:
        d, src = shared.load_long(s)
        if len(d) >= 300 and src != "demo":
            prices[s] = d
    if len(prices) < 15:
        ui.callout("Cần dữ liệu thật của ít nhất 15 mã VN30. Xem trang Tổng quan để biết cách tải.", "bad")
        return
    panel = xsection.build_panel(prices)
    asof = panel["close"].index[-1]
    st.caption(f"Dữ liệu đến hết phiên {asof:%d/%m/%Y}. Nếu dữ liệu đã cũ, hãy tải lại giá (xem trang Hướng dẫn).")
    per = ctx.capital / 5
    st.write(f"Vốn {explain.money_short(ctx.capital)} chia 5 mã = **{explain.money_short(per)}** mỗi mã.")
    picks = {}
    cols = st.columns(2)
    for col, name in zip(cols, ["mom_12_1", "mom_6_1"]):
        rk = xsection.rank_now(panel, name, 5)
        picks[name] = rk[rk["top"]]["symbol"].tolist()
        top = rk.head(5).copy()
        top["Giá (đồng)"] = top["close"].round(0)
        top["Mua nổi (cp)"] = (np.floor(per / top["close"] / risk.LOT) * risk.LOT).astype(int)
        names = {"mom_12_1": "Tăng mạnh nhất 12 tháng qua", "mom_6_1": "Tăng mạnh nhất 6 tháng qua"}
        col.markdown(f"**{names[name]}**")
        col.dataframe(top[["symbol", "Giá (đồng)", "Mua nổi (cp)"]].rename(columns={"symbol": "Mã"}),
                      hide_index=True, width="stretch")
    st.caption("“Mua nổi = 0” nghĩa là số vốn chia cho mã đó không đủ mua 1 lô (100 cổ phiếu).")
    st.markdown("#### Sổ giả lập (không dùng tiền thật)")
    st.caption("Ghi lại danh sách này mỗi tháng và xem sau vài tháng nó thực sự hơn/kém thị trường bao nhiêu.")
    if st.button("Ghi danh sách tháng này vào sổ", key="save_paper"):
        ok = [paper.save_snapshot(f"{asof:%Y-%m-%d}", nm, pk, xsection.SIGNALS[nm]["h"]) for nm, pk in picks.items()]
        st.success("Đã ghi." if all(ok) else "Tháng này đã ghi rồi, không ghi trùng.")
    snaps = paper.list_snapshots()
    if snaps.empty:
        st.info("Chưa có bản ghi. Cần ít nhất 12 tháng mới bắt đầu có ý nghĩa.")
        return
    ev = paper.evaluate(snaps, panel)
    show = ev.copy()
    for c in ("gross", "bench", "net_excess"):
        show[c] = (show[c] * 100).round(2)
    st.dataframe(show.rename(columns={"asof": "Ngày chốt", "signal": "Cách chọn", "picks": "Danh sách", "h": "Số phiên giữ",
                                      "status": "Trạng thái", "gross": "Lãi danh sách (%)", "bench": "Lãi VN30 đều (%)",
                                      "net_excess": "Hơn VN30 sau phí (%)"}), hide_index=True, width="stretch")


def render(ctx) -> None:
    ui.page_header("Nghiên cứu (nâng cao)", "Dành cho người muốn tự kiểm chứng các chiến lược bằng dữ liệu quá khứ. Không bắt buộc phải xem.")
    _verdict_card()
    t1, t2 = st.tabs(["Kiểm chứng “điểm xu hướng”", "Chiến lược chọn mã tăng mạnh (động lượng)"])
    with t1:
        _tab_score()
    with t2:
        _tab_momentum(ctx)
