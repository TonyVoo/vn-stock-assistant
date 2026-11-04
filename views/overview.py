"""Trang Tổng quan: thị trường chung + danh sách theo dõi (bảng gọn, bấm vào dòng để xem chi tiết) + bản tin AI."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from src import charts, explain, journal, llm, news as newsmod, ui
from views import data_update, shared

ORDER = {"up": 0, "flat": 1, "down": 2, "muted": 3}


def _setup_help(ctx) -> None:
    ui.callout("App cần dữ liệu giá thật để hoạt động. Hiện chưa có (đang dùng dữ liệu giả lập, "
               "không dùng để quyết định gì).", "warn", "Bạn cần làm một lần: tải giá về máy")
    st.markdown("**Cách nhanh:** bấm nút bên dưới để app tự tải giá (cần vnstock đã đăng ký, xem trang Hướng dẫn).")
    data_update.render_panel(ctx, default_vn30=True)
    st.markdown("**Hoặc làm bằng Terminal.** Mở Terminal, chạy:")
    st.code("cd ~/Desktop/vn-stock-assistant/vn-stock-assistant\n.venv/bin/python scripts/download_prices.py --years 10",
            language="bash")
    st.markdown("Chờ khoảng 3 phút, rồi bấm **F5** để tải lại trang này.")
    st.caption("Chưa cài được công cụ tải? Xem trang Hướng dẫn.")


def _brief(ctx, snaps) -> None:
    ui.section("Bản tin hôm nay", "AI đọc tin tức + thị trường thế giới rồi tóm tắt giúp bạn")
    if not shared.ai_ready():
        ui.callout("Chưa bật tính năng AI. Đây là phần tuỳ chọn; các phần còn lại vẫn dùng bình thường. "
                   "Muốn bật, xem trang Hướng dẫn, mục “Bật AI”.", "info")
        return
    if st.button(":material/auto_awesome: Tạo bản tin ngay", type="primary"):
        with st.spinner("AI đang đọc tin tức, khoảng 10–20 giây..."):
            try:
                items = newsmod.filter_news(newsmod.fetch_news(), ctx.watchlist)
                glob = shared.world_snapshot()
                watch = [{"symbol": s["symbol"], "score": s["score"], "close": s["close"], "rsi": s["rsi"],
                          "warnings": "; ".join(s["warnings"])} for s in snaps]
                st.session_state["brief"] = (llm.morning_brief(items, glob, watch), len(items), dt.datetime.now(explain.VN_TZ))
            except Exception as e:  # noqa: BLE001
                st.session_state.pop("brief", None)
                ui.callout(f"Không tạo được bản tin ({type(e).__name__}). Thử lại sau ít phút.", "bad")
    if "brief" not in st.session_state:
        return
    b, n, when = st.session_state["brief"]
    st.caption(f"Tạo lúc {when:%H:%M %d/%m} · dựa trên {n} tin đã lọc")
    with st.container(border=True):
        st.markdown("**Tóm lại**")
        st.write(b.get("tong_quan", ""))
        if b.get("ket_noi_the_gioi"):
            st.markdown("**Thế giới đang ảnh hưởng thế nào?**")
            st.write(b["ket_noi_the_gioi"])
    tin = b.get("tin_quan_trong", [])
    if tin:
        rows = ""
        for t in tin:
            kind = {"tich_cuc": "up", "tieu_cuc": "down"}.get(t.get("tac_dong"), "muted")
            label = {"tich_cuc": "Tin tốt", "tieu_cuc": "Tin xấu"}.get(t.get("tac_dong"), "Trung lập")
            ma = " ".join(ui.badge(m, "info") for m in t.get("ma_lien_quan", []))
            lvl = {"cao": "Ảnh hưởng lớn", "vua": "Ảnh hưởng vừa", "thap": "Ảnh hưởng nhỏ"}.get(t.get("muc_do"), "")
            rows += (f'<div class="item"><div>{ui.badge(label, kind)} {ui.badge(lvl, "muted") if lvl else ""} {ma}</div>'
                     f'<div class="t">{ui.esc(t.get("tieu_de"))}</div><div class="d">{ui.esc(t.get("nhan_xet"))}</div></div>')
        st.markdown("**Tin đáng chú ý**")
        st.markdown(f'<div class="card">{rows}</div>', unsafe_allow_html=True)
    rr = b.get("rui_ro_can_theo_doi", [])
    if rr:
        st.markdown("**Điều cần cẩn thận**")
        st.markdown('<div class="card">' + "".join(f'<div class="item"><div class="d">• {ui.esc(x)}</div></div>' for x in rr)
                    + "</div>", unsafe_allow_html=True)
    st.caption("Bản tin do AI tổng hợp từ tin công khai nên có thể sai hoặc thiếu. Dùng để tham khảo, không phải căn cứ duy nhất.")


def _market_hero(idx_df: pd.DataFrame, groups: dict, n_watch: int) -> None:
    last, prev = float(idx_df["close"].iloc[-1]), float(idx_df["close"].iloc[-2])
    chg = last / prev - 1
    with st.container(border=True):
        st.markdown(f'<div class="hero"><div class="row1"><span class="sym" style="font-size:1.1rem;color:{ui.tokens()["soft"]}">'
                    f'Chỉ số thị trường chung · VN-Index</span></div><div class="row2"><span class="px">{explain.num(last, 2)}</span>'
                    f'<span class="abs {ui.change_kind(chg)}">{"+" if last >= prev else "-"}{explain.num(abs(last - prev), 2)}</span>{ui.change_pill(chg, 2, big=True)}</div>'
                    f'<div class="note">{groups["up"]} mã đang tăng · {groups["flat"]} đi ngang · {groups["down"]} đang giảm '
                    f'(trong {n_watch} mã bạn theo dõi)</div></div>', unsafe_allow_html=True)
        rng = st.segmented_control("Khoảng thời gian", list(charts.RANGES), default="1 năm", key="ov_range",
                                   label_visibility="collapsed") or "1 năm"
        d = charts.slice_range(idx_df, rng)
        kind = ui.change_kind(float(d["close"].iloc[-1] / d["close"].iloc[0] - 1))
        charts.price_chart(d, "close", kind, height=300)
        st.caption(f"Biến động VN-Index trong {rng.lower()}: {explain.pct(float(d['close'].iloc[-1] / d['close'].iloc[0] - 1), 1)}")


def _watchlist(snaps) -> None:
    ui.section("Danh sách theo dõi", "Bấm vào một dòng để xem chi tiết")
    rows = sorted(snaps, key=lambda s: (ORDER[explain.trend(s["score"])[1]], -(s["score"] or 0)))
    df = pd.DataFrame([{"Mã": s["symbol"], "Giá": s["close"], "Hôm nay": s["change"],
                        "Xu hướng": explain.trend(s["score"])[0], "60 phiên": s["closes"]} for s in rows])

    def color(v):
        return "color:%s;font-weight:700" % (ui.tokens()["up"] if v > 0 else ui.tokens()["down"] if v < 0 else ui.tokens()["flat"])

    sty = (df.style.format({"Giá": lambda v: explain.num(v), "Hôm nay": lambda v: explain.pct(v, 2)})
           .map(color, subset=["Hôm nay"]))
    ev = st.dataframe(sty, hide_index=True, width="stretch", height=min(38 * len(df) + 40, 520), on_select="rerun",
                      selection_mode="single-row", key="watch_tbl",
                      column_config={"60 phiên": st.column_config.LineChartColumn("60 phiên", width="small"),
                                     "Mã": st.column_config.TextColumn(width="small")})
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        shared.open_page("stock", {"symbol": df.iloc[sel[0]]["Mã"]})
    st.caption("Màu: xanh = tăng, đỏ = giảm. “Xu hướng” mô tả hiện tại, không dự đoán sẽ tăng hay giảm tiếp.")


def render(ctx) -> None:
    now = dt.datetime.now(explain.VN_TZ)
    ui.page_header("Tổng quan thị trường", f"{explain.vi_date(now)} · bức tranh nhanh về các cổ phiếu bạn theo dõi")
    snaps, srcs = shared.snapshot(tuple(ctx.watchlist))
    if not snaps or "demo" in srcs:
        _setup_help(ctx)
        return

    last_date = max(s["last_date"] for s in snaps)
    if any(s["partial"] for s in snaps):
        ui.callout("Phiên giao dịch hôm nay chưa kết thúc (đóng cửa lúc 14:45), nên giá bên dưới là giá tạm thời "
                   "và có thể thay đổi đến cuối phiên.", "warn")

    data_update.render_compact(ctx)

    idx_df, _ = shared.load_long("VNINDEX")
    groups = {k: sum(1 for s in snaps if explain.trend(s["score"])[1] == k) for k in ("up", "flat", "down")}

    left, right = st.columns([3, 2], gap="large")
    with left:
        _market_hero(idx_df, groups, len(snaps))
    with right:
        _watchlist(snaps)

    open_t = journal.list_trades()
    n_open = int(open_t["exit_price"].isna().sum()) if not open_t.empty else 0
    c1, c2, c3 = st.columns(3)
    with c1:
        ui.stat_card("Vốn của bạn", explain.money_short(ctx.capital), "Đổi ở trang Cài đặt")
    with c2:
        ui.stat_card("Lệnh đang giữ", f"{n_open} lệnh", "Xem ở “Nhật ký giao dịch”")
    with c3:
        ui.stat_card("Mã đang tăng", f"{groups['up']}/{len(snaps)}", "Trong danh sách theo dõi", "up" if groups["up"] else "")

    ui.section("Nên làm gì hôm nay?", "Không việc nào bắt buộc; không mua cũng là một lựa chọn tốt")
    ui.steps(["Đọc <b>Bản tin hôm nay</b> bên dưới để biết thị trường có gì mới.",
              "Bấm vào một mã trong danh sách để xem tình hình và hiểu vì sao nó đang tăng/giảm.",
              "Nếu muốn mua, vào <b>Tính lệnh mua</b> để biết nên mua bao nhiêu cổ phiếu cho an toàn.",
              "Mua xong, ghi vào <b>Nhật ký giao dịch</b> kèm lý do. Đừng mua khi chưa viết được lý do."])
    _brief(ctx, snaps)
