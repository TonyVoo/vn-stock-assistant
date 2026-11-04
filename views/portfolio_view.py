"""Trang Danh mục: cổ phiếu đang giữ, giá trị, lãi/lỗ, tỷ trọng. CHỈ ĐỌC: app không đặt lệnh thay bạn."""
from __future__ import annotations

import io
import os
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src import broker_tcbs, cashflow, explain, importer, journal, portfolio, risk_table, ui
from views import shared

SOURCE_LABEL = {"manual": "nhập tay", "import": "nhập từ file", "journal": "từ nhật ký giao dịch", "tcbs": "TCBS (chỉ đọc)"}
PALETTE = ["#5E6AD2", "#3DD68C", "#E5B64A", "#F2555A", "#8C99F2", "#4FB3D9", "#B47EDB", "#E08A4B", "#7A8AA0", "#2FA37A"]


def _done(msg: str) -> None:
    """Sau khi lưu: báo rõ ở đầu trang + thông báo nổi, xoá file đã chọn và cuộn lên đầu để thấy kết quả."""
    st.session_state["pf_flash"] = msg
    st.session_state["pf_scroll_top"] = True
    st.session_state["pf_up_gen"] = st.session_state.get("pf_up_gen", 0) + 1  # đổi khoá => ô chọn file được làm mới
    st.rerun()


def _last_price(sym: str):
    try:
        df, src = shared.load(sym)
        return float(df["close"].iloc[-1]) if src != "demo" and len(df) else None
    except Exception:  # noqa: BLE001
        return None


def _stops() -> dict:
    t = journal.list_trades()
    if t.empty:
        return {}
    op = t[t["exit_price"].isna()]
    op = op[op["stop"] > 0]  # stop = 0 nghĩa là chưa đặt
    return {s: float(g["stop"].max()) for s, g in op.groupby("symbol")}


def _donut(df: pd.DataFrame, cash: float, total: float) -> None:
    tk = ui.tokens()
    rows = [{"name": r.symbol, "value": r.value} for r in df.itertuples() if r.value > 0]
    if cash > 0:
        rows.append({"name": "Tiền mặt", "value": cash})
    d = pd.DataFrame(rows)
    d["pct"] = d["value"] / total
    names = d["name"].tolist()
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(names))]
    if "Tiền mặt" in names:
        colors[names.index("Tiền mặt")] = "#4B5563"
    chart = (alt.Chart(d).mark_arc(innerRadius=58, outerRadius=100, stroke=tk["card"], strokeWidth=2).encode(
        theta=alt.Theta("value:Q"),
        color=alt.Color("name:N", scale=alt.Scale(domain=names, range=colors),
                        legend=alt.Legend(orient="right", title=None, labelColor=tk["soft"], symbolType="square")),
        tooltip=[alt.Tooltip("name:N", title="Mã"), alt.Tooltip("pct:Q", title="Tỷ trọng", format=".1%"),
                 alt.Tooltip("value:Q", title="Giá trị (đồng)", format=",.0f")])
        .properties(height=230).configure_view(strokeWidth=0).configure(background="transparent"))
    st.altair_chart(chart, theme=None, width="stretch")


def _manual_tab(pf) -> None:
    st.caption("Sửa trực tiếp trong bảng (thêm dòng ở hàng cuối, xoá bằng cách chọn dòng rồi nhấn phím Delete). Giá vốn là giá mua trung bình mỗi cổ phiếu, tính bằng đồng.")
    base = pd.DataFrame([{"Mã": h["symbol"], "Số lượng": h["qty"], "Giá vốn (đồng)": h["avg_cost"]} for h in pf["holdings"]],
                        columns=["Mã", "Số lượng", "Giá vốn (đồng)"])
    edited = st.data_editor(base, num_rows="dynamic", hide_index=True, width="stretch", key="pf_editor",
                            column_config={"Mã": st.column_config.TextColumn(max_chars=6),
                                           "Số lượng": st.column_config.NumberColumn(min_value=0, step=100, format="%d"),
                                           "Giá vốn (đồng)": st.column_config.NumberColumn(min_value=0, step=50, format="%d")})
    cash = st.number_input("Tiền mặt (đồng)", 0.0, 1e13, float(pf["cash"]), step=100_000.0, format="%.0f")
    if st.button(":material/save: Lưu danh mục", type="primary", key="pf_save_manual"):
        rows = [{"symbol": r["Mã"], "qty": r["Số lượng"], "avg_cost": r["Giá vốn (đồng)"]}
                for _, r in edited.dropna(subset=["Mã"]).iterrows()]
        ok = portfolio.clean_holdings(rows)
        portfolio.save({"holdings": ok, "cash": cash}, "manual")
        dropped = len(edited.dropna(subset=["Mã"])) - len(ok)
        _done(f"Đã lưu {len(ok)} mã." + (f" Bỏ qua {dropped} dòng không hợp lệ." if dropped else ""))


def _tx_actions(tx, rows, pf, kp: str, manual: bool = False) -> None:
    """Khi file là lịch sử giao dịch: cho chọn cập nhật Danh mục và/hoặc thêm từng lệnh vào Nhật ký."""
    trades, notes = importer.fifo_trades(tx)
    for n in notes:
        ui.callout(n, "warn")
    pv = importer.preview(trades)
    ui.callout("Danh mục cho biết bạn ĐANG GIỮ gì. Nhật ký ghi TỪNG LỆNH (mua, bán, lý do, cắt lỗ, lãi/lỗ đã chốt). "
               "Với file lịch sử giao dịch, bạn có thể cập nhật cả hai cùng lúc. Lưu ý: giá vốn ở Danh mục tính bình quân, "
               "còn ở Nhật ký tính theo từng lô (mua trước bán trước), nên hai con số có thể hơi khác nhau.", "info", "Khác nhau giữa Danh mục và Nhật ký")
    st.markdown(f"Sẽ thêm **{pv['new']} lệnh** vào Nhật ký ({pv['open']} đang giữ, {pv['closed']} đã bán)"
                + (f"; bỏ qua {pv['skipped']} lệnh đã có từ lần nhập trước." if pv["skipped"] else "."))
    if trades:
        st.dataframe(pd.DataFrame([{"Mã": t["symbol"], "Số lượng": t["qty"], "Giá mua": t["entry"], "Ngày mua": t["opened"],
                                    "Giá bán": t["exit"], "Ngày bán": t["closed"]} for t in trades]), hide_index=True, width="stretch")
    st.caption("Lệnh nhập từ sao kê chưa có lý do mua và mức cắt lỗ. Bạn có thể bổ sung sau; lãi/lỗ đã trừ phí và thuế bán ước tính. "
               "Nên nhập đủ lịch sử một lần. Nhập lại cùng file sẽ không bị trùng.")
    c1, c2 = st.columns(2)
    tag = " (theo cột đã chọn)" if manual else ""
    if c1.button("Thêm vào Nhật ký và cập nhật Danh mục" + tag, type="primary", key=f"{kp}_both"):
        r = importer.to_journal(trades)
        portfolio.save({"holdings": rows, "cash": pf["cash"]}, "import")
        _done(f"Đã thêm {r['open'] + r['closed']} lệnh vào Nhật ký ({r['open']} đang giữ, {r['closed']} đã bán) "
              f"và cập nhật Danh mục {len(rows)} mã. Vào Nhật ký giao dịch để bổ sung lý do và mức cắt lỗ.")
    if c2.button("Chỉ cập nhật Danh mục" + tag, key=f"{kp}_pf"):
        portfolio.save({"holdings": rows, "cash": pf["cash"]}, "import")
        _done(f"Đã cập nhật Danh mục {len(rows)} mã (không thêm vào Nhật ký).")


def _holdings_actions(rows, pf, kp: str, manual: bool = False) -> None:
    """File danh mục đang giữ: mặc định lưu vào CẢ Danh mục và Nhật ký (mỗi mã thành một lệnh đang giữ)."""
    trades = importer.holdings_to_trades(rows, importer.open_symbols())
    pv = importer.preview(trades)
    tag = "theo cột đã chọn " if manual else ""
    ui.callout("Danh mục cho biết bạn ĐANG GIỮ gì; Nhật ký ghi TỪNG LỆNH. Khi lưu vào cả hai, mỗi mã thành một lệnh đang giữ trong Nhật ký "
               "(giá mua = giá vốn trong file, ngày mua “Không rõ”, chưa có lý do và mức cắt lỗ để bạn bổ sung sau).", "info")
    if pv["new"] == 0:
        st.caption("Các mã này đã có lệnh đang giữ trong Nhật ký (hoặc file thiếu giá vốn), nên chỉ cập nhật Danh mục.")
        if st.button(f"Lưu {tag}vào Danh mục", type="primary", key=f"{kp}_pf"):
            portfolio.save({"holdings": rows, "cash": pf["cash"]}, "import")
            _done(f"Đã lưu Danh mục: {len(rows)} mã ({', '.join(h['symbol'] for h in rows[:8])}{'...' if len(rows) > 8 else ''}).")
        return
    c1, c2 = st.columns(2)
    if c1.button(f"Lưu {tag}vào Danh mục và thêm {pv['new']} mã vào Nhật ký", type="primary", key=f"{kp}_both"):
        r = importer.to_journal(trades)
        portfolio.save({"holdings": rows, "cash": pf["cash"]}, "import")
        _done(f"Đã lưu Danh mục {len(rows)} mã và thêm {r['open']} lệnh đang giữ vào Nhật ký giao dịch. "
              "Vào Nhật ký giao dịch để bổ sung lý do mua và mức cắt lỗ.")
    if c2.button(f"Chỉ lưu {tag}vào Danh mục", key=f"{kp}_pf"):
        portfolio.save({"holdings": rows, "cash": pf["cash"]}, "import")
        _done(f"Đã lưu Danh mục: {len(rows)} mã ({', '.join(h['symbol'] for h in rows[:8])}{'...' if len(rows) > 8 else ''}).")


def _risk_section(df: pd.DataFrame, s: dict, pf: dict) -> None:
    """Bảng rủi ro: nếu các mã chạm mức cắt lỗ, bạn mất thêm bao nhiêu; mã nào chưa có cắt lỗ; thử kịch bản giá giảm."""
    ui.section("Rủi ro danh mục", "Nếu giá giảm, bạn có thể mất thêm bao nhiêu?")
    t = journal.list_trades()
    open_t = t[t["exit_price"].isna()] if not t.empty else None
    risk_pct = float(st.session_state.get("risk_pct", 2.0))
    rt, rs = risk_table.build(df, open_t, pf["cash"], risk_pct)
    label, level, text = rs["verdict"]
    ui.callout(text, {"bad": "bad", "warn": "warn", "ok": "good"}.get(level, "info"), f"Đánh giá nhanh: {label}")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ui.stat_card("Mất thêm nếu chạm cắt lỗ", explain.money_short(rs["loss_to_stop"]),
                     f"{explain.pct(rs['loss_to_stop_pct'], 1, signed=False)} tổng tài sản", "down" if rs["loss_to_stop"] else "")
    with c2:
        ui.stat_card("Chưa có cắt lỗ", explain.money_short(rs["unprotected_value"]),
                     f"{explain.pct(rs['unprotected_share'], 0, signed=False)} giá trị cổ phiếu · {rs['n_unprotected']} mã chưa đặt",
                     "down" if rs["unprotected_value"] else "up")
    with c3:
        ui.stat_card("Tiền mặt đệm", explain.pct(rs["cash_pct"], 0, signed=False), f"{explain.money_short(rs['cash'])} trên tổng tài sản")
    with c4:
        need = rs["n_hit"] + rs["n_over"] + rs["n_unprotected"]
        ui.stat_card("Mã cần xem lại", f"{need} mã", f"{rs['n_hit']} đã chạm · {rs['n_over']} vượt mức · {rs['n_unprotected']} chưa đặt",
                     "down" if need else "up")

    view = pd.DataFrame({
        "Mã": rt["symbol"], "Giá trị": rt["value"].map(lambda x: explain.num(x)), "Tỷ trọng": rt["weight"].map(lambda x: explain.pct(x, 0, signed=False)),
        "Mức cắt lỗ": rt["stop"].map(lambda x: explain.num(x) if pd.notna(x) else "chưa đặt"),
        "Cách cắt lỗ": rt["dist_pct"].map(lambda x: explain.pct(x, 1, signed=False) if pd.notna(x) else "—"),
        "Mất nếu chạm": rt["loss"].map(lambda x: explain.num(x) if x else "—"),
        "% tài sản": rt.apply(lambda r: explain.pct(r["pct_assets"], 1, signed=False) if r["loss"] else "—", axis=1),
        "Trạng thái": rt["status"]})
    tk = ui.tokens()
    colors = {"bad": tk["down"], "warn": tk["flat"], "ok": tk["up"]}
    lvl = dict(zip(rt["symbol"], rt["level"]))
    sty = view.style.apply(lambda col: [f"color:{colors[lvl[m]]};font-weight:600" for m in view["Mã"]], subset=["Trạng thái"])
    st.dataframe(sty, hide_index=True, width="stretch")
    st.caption(f"“Mất nếu chạm” là phần bạn còn có thể mất thêm TỪ GIÁ HIỆN TẠI xuống mức cắt lỗ (không phải lỗ so với giá vốn). Mức cắt lỗ lấy từ lệnh đang giữ trong Nhật ký. "
               f"“Vượt mức” so với mức bạn chấp nhận mất cho mỗi mã ({risk_pct:.1f}% tài sản, chỉnh ở Cài đặt). Thực tế giá có thể nhảy qua mức cắt lỗ hoặc "
               "giảm kịch sàn khiến không bán được, nên mất thực tế có thể lớn hơn. Các ngưỡng đánh giá chỉ là quy tắc kinh nghiệm.")
    if rs["n_unprotected"] or (rt["uncovered"] > 0).any():
        if st.button("Đi tới Nhật ký để đặt mức cắt lỗ", key="risk_go_journal"):
            shared.open_page("journal")
    st.markdown("**Thử kịch bản: nếu tất cả cổ phiếu giảm thêm...**")
    st.dataframe(pd.DataFrame([{"Giảm thêm": f"{x['drop']}%", "Bạn mất": explain.vnd(x["loss"]),
                                "Tương đương": explain.pct(x["pct_assets"], 1, signed=False) + " tổng tài sản"} for x in rs["scenarios"]]),
                 hide_index=True, width="stretch")


def _submit_cashflow() -> None:
    """Chạy khi bấm Ghi giao dịch (trước khi trang vẽ lại). Chỉ xoá ô nhập khi ghi THÀNH CÔNG; lỗi thì giữ nguyên lựa chọn của bạn."""
    s = st.session_state
    amount, kind = float(s.get("cf_amount") or 0), s.get("cf_kind", "Nạp tiền vào")
    if amount <= 0:
        s["cf_error"] = "Hãy nhập số tiền lớn hơn 0."
        return
    try:
        cashflow.add(s["cf_day"], amount if kind == "Nạp tiền vào" else -amount, s.get("cf_note", ""))
    except ValueError as e:
        s["cf_error"] = str(e)
        return
    s["cf_error"] = None
    s["cf_flash"] = f"Đã ghi {kind.lower()} {explain.vnd(amount)} ngày {s['cf_day']:%d/%m/%Y}."
    s["cf_amount"], s["cf_note"] = 0.0, ""


def _cashflow_section(total: float, cash: float, has_holdings: bool, capital: float) -> None:
    """Tiền nạp/rút: tách lãi thật do đầu tư khỏi số tiền bạn bỏ thêm vào."""
    ui.section("Tiền nạp/rút và lãi thật", "Tách phần lãi do đầu tư khỏi phần tiền bạn bỏ thêm vào")
    msg = st.session_state.pop("cf_flash", None)
    if msg:
        st.success(msg, icon=":material/check_circle:")
        st.toast(msg, icon=":material/check_circle:")
    flows = cashflow.list_flows()
    sm = cashflow.summary(flows, total)
    if not sm["n"]:
        ui.callout("Chưa có ghi chép nào. Hãy ghi số tiền bạn đã bỏ vào tài khoản đầu tư (ví dụ: ngày bắt đầu, nạp 10 triệu) để app tính lãi thật. "
                   "Mỗi lần nạp thêm hoặc rút ra, ghi tiếp ở đây, nếu không tổng tài sản tăng lên sẽ bị hiểu nhầm là lãi.", "info")
    elif total <= 0:
        ui.callout("Cần có Danh mục (và tiền mặt) ở trên thì mới tính được lãi thật.", "warn")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            ui.stat_card("Tiền ròng bạn đã bỏ vào", explain.money_short(sm["net_in"]),
                         f"nạp {explain.money_short(sm['deposited'])} · rút {explain.money_short(sm['withdrawn'])}")
        with c2:
            ui.stat_card("Tổng tài sản hiện tại", explain.money_short(total), "cổ phiếu + tiền mặt")
        with c3:
            k = ui.change_kind(sm["pnl"])
            ui.stat_card("Lãi/lỗ thật", ("+" if sm["pnl"] >= 0 else "-") + explain.money_short(abs(sm["pnl"])),
                         (explain.pct(sm["pnl_pct"], 1) + " so với tiền ròng đã bỏ vào") if sm["pnl_pct"] is not None else "Chưa có tỷ lệ %", k)
        with c4:
            if sm["annual"] is not None:
                ui.stat_card("Tỷ suất quy năm", explain.pct(sm["annual"], 1), f"tính theo ngày nạp/rút, đã {sm['days']} ngày" + (" · chưa đủ 1 năm, chỉ tham khảo" if sm["days"] < 365 else ""),
                             ui.change_kind(sm["annual"]))
            else:
                ui.stat_card("Tỷ suất quy năm", "Chưa tính được", f"cần ít nhất {cashflow.MIN_DAYS_FOR_ANNUAL} ngày (hiện {sm['days']} ngày)")
        if cash <= 0 and has_holdings:
            ui.callout("Tiền mặt trong Danh mục đang là 0đ. Nếu tài khoản còn tiền mặt, hãy nhập ở tab “Nhập tay” bên dưới, nếu không tổng tài sản bị thiếu "
                       "và lãi thật sẽ bị tính thấp hơn thực tế.", "warn")
        st.caption("Lãi thật = tổng tài sản hiện tại trừ đi tiền ròng bạn đã bỏ vào. Đã gồm lãi/lỗ đã chốt, cổ tức, phí và thuế mà giá trên màn hình chưa thể hiện. "
                   "Tỷ suất quy năm cho biết nếu giữ tốc độ này một năm thì được bao nhiêu %, và chỉ hiện khi đã đủ lâu.")
    if st.session_state.get("cf_error"):
        st.error(st.session_state["cf_error"])
    with st.form("cf_form"):
        a, b, c = st.columns(3)
        day = a.date_input("Ngày", value=date.today(), max_value=date.today(), format="DD/MM/YYYY", key="cf_day")
        kind = b.radio("Loại", ["Nạp tiền vào", "Rút tiền ra"], horizontal=True, key="cf_kind")
        amount = c.number_input("Số tiền (đồng)", min_value=0.0, value=float(capital) if not sm["n"] else 0.0, step=100_000.0,
                                format="%.0f", key="cf_amount")
        note = st.text_input("Ghi chú (không bắt buộc)", key="cf_note", placeholder="Ví dụ: vốn ban đầu, góp tháng 11")
        st.form_submit_button(":material/add: Ghi giao dịch", type="primary", on_click=_submit_cashflow)
    if len(flows):
        show = flows.sort_values(["day", "id"], ascending=False)
        st.dataframe(pd.DataFrame({"Ngày": show["day"].dt.strftime("%d/%m/%Y"), "Loại": show["amount"].map(lambda x: "Nạp" if x > 0 else "Rút"),
                                   "Số tiền": show["amount"].abs().map(lambda x: explain.num(x)), "Ghi chú": show["note"]}),
                     hide_index=True, width="stretch")
        with st.expander(":material/delete: Xoá một ghi chép"):
            opts = {f"{r.day:%d/%m/%Y} · {'Nạp' if r.amount > 0 else 'Rút'} {explain.vnd(abs(r.amount))}" + (f" · {r.note}" if r.note else ""): int(r.id)
                    for r in show.itertuples()}
            pick = st.selectbox("Chọn ghi chép cần xoá", list(opts), key="cf_del_pick")
            if st.button("Xoá ghi chép này", key="cf_del"):
                cashflow.delete(opts[pick])
                st.session_state["cf_flash"] = "Đã xoá ghi chép."
                st.rerun()


def _journal_sync_button(pf, kp: str) -> None:
    """Nút thêm các mã đang có trong Danh mục vào Nhật ký (không cần tải lại file)."""
    trades = importer.holdings_to_trades(pf["holdings"], importer.open_symbols())
    n = importer.preview(trades)["new"]
    if not n:
        return
    ui.callout(f"{n} mã trong Danh mục chưa có trong Nhật ký giao dịch. Thêm vào để theo dõi lệnh đang giữ, cảnh báo gần cắt lỗ và ghi lý do.", "info")
    if st.button(f"Thêm {n} mã này vào Nhật ký giao dịch", type="primary", key=f"{kp}_sync"):
        r = importer.to_journal(trades)
        _done(f"Đã thêm {r['open']} lệnh đang giữ vào Nhật ký giao dịch. Vào Nhật ký để bổ sung lý do mua và mức cắt lỗ.")


def _read_upload(up) -> dict:
    """Trả về {tên trang tính: bảng}. CSV chỉ có một bảng; Excel có thể có nhiều trang tính."""
    data = io.BytesIO(up.getvalue())  # đọc từ bản sao: không phụ thuộc vị trí con trỏ sau các lần chạy lại
    if up.name.lower().endswith(".csv"):
        return {"CSV": pd.read_csv(data, sep=None, engine="python", encoding="utf-8-sig", dtype=str, header=0)}
    return pd.read_excel(data, sheet_name=None, dtype=str, header=0)  # tất cả trang tính


def _show_rows(rows) -> None:
    st.dataframe(pd.DataFrame(rows).rename(columns={"symbol": "Mã", "qty": "Số lượng", "avg_cost": "Giá vốn"}).drop(columns=["market_value"], errors="ignore"),
                 hide_index=True, width="stretch")


def _manual_columns(raw: pd.DataFrame, sheet: str, pf, expanded: bool) -> None:
    with st.expander(":material/tune: Tự chọn cột (nếu app đọc sai hoặc không nhận ra)", expanded=expanded):
        st.caption("Phần đầu của file mà app đã đọc được (để bạn biết cột nào là cột nào):")
        st.dataframe(raw.head(12), width="stretch")
        hdr = st.number_input("Dòng tiêu đề nằm ở dòng số (1 = dòng đầu tiên của file)", 1, 30, 1, key=f"pf_hdr_{sheet}")
        df, cols = portfolio.apply_header(raw, int(hdr))
        kind_m = st.radio("Đây là file", ["Danh mục đang giữ", "Lịch sử giao dịch"], horizontal=True, key=f"pf_kind_{sheet}")
        k = "giao dịch" if kind_m == "Lịch sử giao dịch" else "danh mục"
        guess = portfolio._map_columns(cols) if k == "danh mục" else portfolio._tx_map(cols)

        def pick(label: str, key: str, optional: bool = False):
            opts = (["(không có)"] if optional else []) + cols
            idx = opts.index(guess[key]) if guess.get(key) in opts else 0
            val = st.selectbox(label, opts, index=idx, key=f"pf_m_{key}_{k}_{hdr}_{sheet}")
            return None if val == "(không có)" else val

        c1, c2 = st.columns(2)
        with c1:
            chosen = {"symbol": pick("Cột Mã cổ phiếu", "symbol"), "qty": pick("Cột Khối lượng", "qty")}
        with c2:
            if k == "danh mục":
                chosen["avg_cost"] = pick("Cột Giá vốn (không bắt buộc)", "avg_cost", optional=True)
            else:
                chosen["side"] = pick("Cột Mua/Bán", "side")
                chosen["price"] = pick("Cột Giá khớp", "price")
        if k == "giao dịch":
            c3, c4 = st.columns(2)
            with c3:
                chosen["date"] = pick("Cột Ngày (không bắt buộc)", "date", optional=True)
            with c4:
                chosen["status"] = pick("Cột Trạng thái (không bắt buộc)", "status", optional=True)
        rows, notes = portfolio.parse_manual(df, k, chosen)
        for n in notes:
            ui.callout(n, "warn")
        if rows and k == "giao dịch":
            _show_rows(rows)
            tx_m, _ = portfolio.transactions_manual(df, chosen)
            _tx_actions(tx_m, rows, pf, f"pf_txm_{sheet}", manual=True)
        elif rows:
            _show_rows(rows)
            _holdings_actions(rows, pf, f"pf_usem_{sheet}", manual=True)


def _file_tab(pf) -> None:
    st.caption("Tải file CSV hoặc Excel xuất từ công ty chứng khoán: danh mục đang giữ (cột Mã, Khối lượng, Giá vốn) HOẶC lịch sử giao dịch "
               "(cột Mã, Mua/Bán, Khối lượng, Giá). App tự nhận loại file; nếu không nhận ra, bạn tự chọn cột. "
               "Cách này không cần khoá hay mật khẩu nào, và file chỉ được xử lý trên máy bạn.")
    sample = "Mã CK,Khối lượng,Giá vốn (đ)\nFPT,100,98500\nHPG,200,24000\n".encode("utf-8-sig")
    st.download_button(":material/download: Tải file mẫu (CSV)", sample, "mau_danh_muc.csv", "text/csv", key="pf_sample")
    up = st.file_uploader("Chọn file", type=["csv", "xlsx"], key=f"pf_file_{st.session_state.get('pf_up_gen', 0)}")
    if not up:
        return
    try:
        sheets = _read_upload(up)
    except ImportError:
        ui.callout("Đọc file Excel cần thư viện openpyxl. Hãy xuất file dạng CSV, hoặc chạy: pip install openpyxl", "warn")
        return
    except Exception as e:  # noqa: BLE001
        ui.callout(f"Không đọc được file ({type(e).__name__}). Thử xuất lại dạng CSV hoặc .xlsx.", "bad")
        return
    names = list(sheets)
    auto = next((n for n in names if portfolio.parse_file(sheets[n])[0]), None)  # trang tính đầu tiên đọc được
    sheet = names[0]
    if len(names) > 1:
        sheet = st.selectbox("Trang tính trong file", names, index=names.index(auto) if auto else 0, key="pf_sheet",
                             help="File Excel có nhiều trang tính. App đã chọn sẵn trang đọc được.")
    raw = sheets[sheet]
    rows, notes, kind = portfolio.parse_file(raw)
    if kind == "giao dịch" and rows:
        ui.callout("Đây là file lịch sử giao dịch. App tính số lượng đang giữ và giá vốn bình quân từ các lệnh mua/bán trong file.", "info")
    elif kind == "giao dịch":
        ui.callout("Theo lịch sử này, hiện bạn không còn cổ phiếu nào đang giữ. Vẫn có thể thêm các lệnh đã bán vào Nhật ký.", "info")
        tx0, _ = portfolio.transactions_from_file(raw)
        if tx0:
            _tx_actions(tx0, [], pf, "pf_tx0")
    for n in notes:
        ui.callout(n, "warn")
    if rows and kind == "giao dịch":
        _show_rows(rows)
        st.caption("Danh mục đang giữ suy ra từ lịch sử (ở trên). Bên dưới là các lệnh sẽ thêm vào Nhật ký.")
        tx, _ = portfolio.transactions_from_file(raw)
        _tx_actions(tx, rows, pf, "pf_tx")
    elif rows:
        _show_rows(rows)
        _holdings_actions(rows, pf, "pf_use")
    elif kind != "giao dịch":
        ui.callout("App chưa nhận ra các cột trong file này. Bạn chọn cột bằng tay ở bên dưới, chỉ mất vài giây.", "warn")
    _manual_columns(raw, sheet, pf, expanded=not rows and kind != "giao dịch")


def _journal_tab(pf) -> None:
    rows = portfolio.from_journal(journal.list_trades())
    if not rows:
        st.info("Nhật ký chưa có lệnh nào đang giữ.")
        return
    st.caption("Danh mục dựng từ các lệnh chưa bán trong Nhật ký giao dịch (giá vốn = giá mua).")
    st.dataframe(pd.DataFrame(rows).rename(columns={"symbol": "Mã", "qty": "Số lượng", "avg_cost": "Giá vốn"}).drop(columns=["market_value"]),
                 hide_index=True, width="stretch")
    if st.button("Dùng danh mục từ nhật ký (thay thế danh mục hiện tại)", type="primary", key="pf_use_journal"):
        portfolio.save({"holdings": rows, "cash": pf["cash"]}, "journal")
        _done(f"Đã dựng Danh mục từ Nhật ký: {len(rows)} mã.")


def _tcbs_tab() -> None:
    key = os.getenv("TCBS_API_KEY", "").strip()
    ui.callout("Theo tài liệu của TCBS, khoá API KHÔNG có chế độ chỉ-đọc: cùng một khoá có thể đặt lệnh và chuyển tiền. "
               "Vì vậy app chỉ có code để ĐỌC (danh mục, tiền mặt) và không thể gọi lệnh đặt, sửa, huỷ hay chuyển tiền. "
               "Mỗi lần lấy dữ liệu cần Smart OTP từ app TCInvest; mã truy cập chỉ nằm trong bộ nhớ, không ghi ra đĩa.", "info", "Cách bảo vệ tài khoản của bạn")
    if not key:
        st.markdown("**Chưa cấu hình.** Làm một lần:")
        ui.steps(["Trong app TCInvest: <b>Menu trái, Tiện ích, iFlash Open API</b>, đăng ký (miễn phí) và tạo API key.",
                  "Mở file <code>.env</code> trong thư mục dự án và thêm dòng <code>TCBS_API_KEY=khoá_của_bạn</code>. "
                  "Có thể thêm <code>TCBS_ACCOUNT_NO=số_tiểu_khoản</code> để khỏi nhập lại.",
                  "Khởi động lại app. <b>Không gửi khoá cho ai và không dán vào chat.</b>"])
        st.caption("Khi không dùng nữa, bạn có thể huỷ khoá ngay trong trang iFlash Open API.")
        return
    client = st.session_state.get("tcbs_client")
    if client is None:
        client = st.session_state["tcbs_client"] = broker_tcbs.TcbsReadOnly(key)
    if client.logged_in():
        st.success("Đã xác thực với TCBS (mã truy cập còn hiệu lực trong bộ nhớ, tối đa 8 giờ).")
    with st.form("tcbs_form", clear_on_submit=True):
        acc = st.text_input("Số tiểu khoản", value=os.getenv("TCBS_ACCOUNT_NO", ""), placeholder="Ví dụ: 0001xxxxxx",
                            help="Không nhớ? Điền số lưu ký (ví dụ 105Cxxxxxx) ở ô dưới để app tìm giúp.")
        custody = st.text_input("Số lưu ký (chỉ cần nếu chưa biết số tiểu khoản)", value=os.getenv("TCBS_CUSTODY_CODE", ""))
        otp = st.text_input("Smart OTP từ app TCInvest" + (" (không cần nếu đã xác thực)" if client.logged_in() else ""),
                            type="password", max_chars=8)
        go = st.form_submit_button(":material/sync: Lấy danh mục từ TCBS (chỉ đọc)", type="primary")
    if not go:
        return
    try:
        if not client.logged_in():
            client.login(otp)
        acc = acc.strip()
        if not acc:
            if not custody.strip():
                raise broker_tcbs.BrokerError("Cần số tiểu khoản hoặc số lưu ký.")
            subs = [a for a in client.accounts(custody.strip()) if a["type"] == "NORMAL"] or client.accounts(custody.strip())
            if not subs:
                raise broker_tcbs.BrokerError("Không tìm thấy tiểu khoản nào.")
            acc = next((a["accountNo"] for a in subs if a["default"]), subs[0]["accountNo"])
        snap = client.snapshot(acc)
        saved = portfolio.save(snap, "tcbs")
        _done(f"Đã lấy {len(saved['holdings'])} mã và tiền mặt từ tiểu khoản ***{acc[-4:]}.")
    except broker_tcbs.BrokerError as e:
        ui.callout(str(e), "bad", "Không lấy được dữ liệu từ TCBS")


def render(ctx) -> None:
    ui.page_header("Danh mục", "Cổ phiếu bạn đang nắm giữ, giá trị hiện tại và lãi/lỗ. App chỉ đọc dữ liệu, không đặt lệnh thay bạn.")
    flash = st.session_state.pop("pf_flash", None)
    if flash:
        st.success(flash, icon=":material/check_circle:")
        st.toast(flash, icon=":material/check_circle:")
    if st.session_state.pop("pf_scroll_top", False):
        components.html("<script>const m=window.parent.document.querySelector('[data-testid=\"stMain\"]');"
                        "if(m){m.scrollTo({top:0,behavior:'smooth'});}</script>", height=0)
    pf = portfolio.load()
    empty = not pf["holdings"] and not pf["cash"]
    if not empty:
        df, s = portfolio.valuate(pf, _last_price, st.session_state.get("max_alloc", 30) / 100)
        label = SOURCE_LABEL.get(pf["source"], "không rõ")
        age = (datetime.now() - datetime.fromisoformat(pf["as_of"])).days if pf["as_of"] else None
        st.caption(f"Nguồn: {label} · cập nhật {datetime.fromisoformat(pf['as_of']):%H:%M %d/%m/%Y}" if pf["as_of"] else f"Nguồn: {label}")
        if age is not None and age >= 1:
            ui.callout(f"Danh mục được cập nhật lần cuối cách đây {age} ngày. Nếu bạn đã mua hoặc bán thêm, hãy cập nhật lại bên dưới.", "warn")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            ui.stat_card("Tổng tài sản", explain.money_short(s["total"]), explain.vnd(s["total"]))
        with c2:
            ui.stat_card("Cổ phiếu", explain.money_short(s["stock_value"]), f"{s['n']} mã")
        with c3:
            ui.stat_card("Tiền mặt", explain.money_short(s["cash"]),
                         explain.pct(s["cash"] / s["total"], 0, signed=False) + " tổng tài sản" if s["total"] else "")
        with c4:
            k = ui.change_kind(s["pnl"])
            ui.stat_card("Lãi/lỗ tạm tính", ("+" if s["pnl"] >= 0 else "-") + explain.money_short(abs(s["pnl"])),
                         (explain.pct(s["pnl_pct"], 1) + " so với giá vốn") if s["pnl_pct"] is not None else "Thiếu giá vốn", k)
        for w in s["warnings"]:
            ui.callout(w, "warn")

        left, right = st.columns([3, 2], gap="large")
        with left:
            ui.section("Chi tiết từng mã", "Giá lấy từ dữ liệu của bạn")
            stops = _stops()
            view = pd.DataFrame({
                "Mã": df["symbol"], "Số lượng": df["qty"], "Giá vốn": df["avg_cost"], "Giá hiện tại": df["price"],
                "Giá trị": df["value"], "Lãi/lỗ": df["pnl"], "Lãi/lỗ %": df["pnl_pct"], "Tỷ trọng": df["weight"],
                "Cắt lỗ (nhật ký)": df["symbol"].map(stops).map(lambda v: explain.num(v) if pd.notna(v) else "chưa đặt")})

            def color(v):
                if pd.isna(v):
                    return ""
                return "color:%s;font-weight:600" % (ui.tokens()["up"] if v > 0 else ui.tokens()["down"] if v < 0 else ui.tokens()["flat"])

            sty = (view.style.format({"Số lượng": lambda v: explain.num(v), "Giá vốn": lambda v: explain.num(v) if v else "—",
                                      "Giá hiện tại": lambda v: explain.num(v) if pd.notna(v) else "—",
                                      "Giá trị": lambda v: explain.num(v), "Lãi/lỗ": lambda v: explain.num(v) if pd.notna(v) else "—",
                                      "Lãi/lỗ %": lambda v: explain.pct(v, 1) if pd.notna(v) else "—",
                                      "Tỷ trọng": lambda v: explain.pct(v, 0, signed=False)})
                   .map(color, subset=["Lãi/lỗ", "Lãi/lỗ %"]))
            st.dataframe(sty, hide_index=True, width="stretch")
            _journal_sync_button(pf, "pf_main")
            st.caption(f"Lãi/lỗ sau khi trừ phí và thuế bán ước tính: {('+' if s['net_pnl'] >= 0 else '-')}{explain.vnd(abs(s['net_pnl']))}. "
                       "“Cắt lỗ (nhật ký)” lấy từ lệnh cùng mã bạn đã ghi; “chưa đặt” nghĩa là mã này chưa có mức cắt lỗ.")
        with right:
            ui.section("Tỷ trọng")
            _donut(df, s["cash"], s["total"])
        _risk_section(df, s, pf)
    else:
        ui.callout("Chưa có danh mục. Chọn một cách nhập bên dưới. Nếu bạn dùng TCBS, có thể kết nối chỉ-đọc để lấy tự động.", "info")

    _cashflow_section(s["total"] if not empty else pf["cash"], pf["cash"], bool(pf["holdings"]),
                      float(st.session_state.get("capital_m", 10.0)) * 1_000_000)

    ui.section("Cập nhật danh mục")
    t1, t2, t3, t4 = st.tabs(["Nhập tay", "Nhập từ file", "Từ nhật ký", "Kết nối TCBS (chỉ đọc)"])
    with t1:
        _manual_tab(pf)
    with t2:
        _file_tab(pf)
    with t3:
        _journal_tab(pf)
    with t4:
        _tcbs_tab()
