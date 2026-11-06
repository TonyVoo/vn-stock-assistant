"""Trang Cài đặt: vốn, danh sách theo dõi, mức an toàn. Bấm Lưu để ghi ra file (không mất khi tải lại trang)."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

from src import data as datamod
from src import backup, explain, inbox, settings, ui
from views import data_update, shared


def _available_symbols():
    have = {p.stem.upper() for p in datamod.CSV_DIR.glob("*.csv")} - {"VNINDEX"}
    return sorted(have | set(datamod.VN30_DEFAULT))


def _inbox_section() -> None:
    ui.section("Tự nhập sao kê", "Thả file sao kê vào một thư mục, app tự đọc và cập nhật Danh mục, Nhật ký")
    d = inbox.inbox_dir()
    st.markdown(f"Thư mục: `{d}`")
    st.caption("Tải sao kê (danh mục đang giữ hoặc lịch sử lệnh khớp, dạng Excel hoặc CSV) từ trang của công ty chứng khoán, rồi lưu vào thư mục trên. "
               "Khoảng vài chục giây sau app tự đọc. Trước mỗi lần nhập app tự sao lưu dữ liệu, và bạn có thể hoàn tác. File xử lý xong được chuyển sang thư mục da-xu-ly, "
               "không bị xoá. Nếu app chưa nhận ra cột của file, nó sẽ báo và KHÔNG sửa dữ liệu; khi đó hãy tải file lên ở trang Danh mục và tự chọn cột.")
    if sys.platform == "darwin" and st.button(":material/folder_open: Mở thư mục", key="ib_open"):
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(d)], check=False)
    state = inbox.load_state()
    if state["history"]:
        st.markdown("**Các lần nhập gần đây**")
        for h in reversed(state["history"][-5:]):
            st.caption(f"{h['at'].replace('T', ' ')} · {h['summary']}")
    for msg in list(state["failed"].values())[-3:]:
        st.caption(f":orange[Chưa nhập được một file: {msg}]")
    u = state.get("undo")
    if u:
        ok = st.checkbox(f"Tôi muốn hoàn tác lần nhập “{u['name']}” (Nhật ký và Danh mục quay về trước lúc nhập; lệnh bạn ghi thêm sau đó sẽ mất)", key="ib_ok")
        if st.button(":material/undo: Hoàn tác lần nhập gần nhất", disabled=not ok, key="ib_undo"):
            res = inbox.undo()
            shared.clear_price_caches()
            st.success("Đã hoàn tác." if res else "Không tìm thấy bản sao lưu để hoàn tác.", icon=":material/check_circle:")


def _backup_section() -> None:
    ui.section("Sao lưu và khôi phục", "Nhật ký, Danh mục, tiền nạp/rút, cổ tức, sổ giả lập và cài đặt (không gồm file giá, tải lại được)")
    a, b = st.columns(2)
    a.download_button(":material/download: Tải bản sao lưu", backup.create, f"sao-luu-{datetime.now():%Y%m%d-%H%M}.zip", "application/zip",
                      width="stretch", key="bk_dl", help="Lưu file này ở nơi an toàn (ổ khác, đám mây). Chứa dữ liệu cá nhân của bạn.")
    if b.button(":material/save: Lưu bản sao lưu vào máy", width="stretch", key="bk_local",
                help=f"Lưu trong data/backups, giữ {backup.KEEP_LOCAL} bản mới nhất."):
        p = backup.save_local()
        st.success(f"Đã lưu {p.name} trong thư mục data/backups.", icon=":material/check_circle:")
    last = backup.latest_auto()
    st.caption("Tự động sao lưu mỗi ngày khi bạn mở app, giữ " + str(backup.KEEP_AUTO) + " bản gần nhất trong data/backups. "
               + (f"Bản tự động gần nhất: {datetime.fromtimestamp(last.stat().st_mtime):%H:%M %d/%m/%Y}." if last else "Chưa có bản tự động nào."))
    with st.expander(":material/restore: Khôi phục từ file sao lưu"):
        st.caption("Khôi phục sẽ GHI ĐÈ dữ liệu hiện tại bằng nội dung trong file. App tự lưu một bản dữ liệu hiện tại trước khi ghi đè.")
        up = st.file_uploader("Chọn file sao lưu (.zip)", type=["zip"], key="bk_up")
        if up is not None:
            raw = up.getvalue()
            try:
                info = backup.inspect(raw)
            except ValueError as e:
                st.error(str(e))
                return
            st.write(f"File chứa: {', '.join(info['files'])}" + (f" (tạo lúc {info['created']})" if info["created"] else ""))
            ok = st.checkbox("Tôi hiểu dữ liệu hiện tại sẽ bị thay bằng nội dung file này", key="bk_ok")
            if st.button("Khôi phục", type="primary", disabled=not ok, key="bk_restore"):
                res = backup.restore(raw)
                shared.clear_price_caches()
                st.success(f"Đã khôi phục {len(res['restored'])} mục. Bản dữ liệu trước đó được lưu tại {res['safety_copy'].name}. Hãy tải lại trang.",
                           icon=":material/check_circle:")


def _save_simple() -> None:
    st.session_state["simple_mode"] = st.session_state["w_simple"]
    settings.save(shared.current_settings())


def _save_auto() -> None:
    st.session_state["auto_price"] = st.session_state["w_auto_price"]
    settings.save(shared.current_settings())


def render(ctx) -> None:
    ui.page_header("Cài đặt", "Chỉnh xong bấm “Lưu cài đặt”. Cài đặt được lưu trên máy bạn và vẫn còn khi tải lại trang.")
    s = st.session_state
    with st.form("settings_form"):
        st.markdown("**Vốn của bạn**")
        capital = st.number_input("Số tiền bạn dự định dùng để đầu tư (triệu đồng)", 0.1, 1_000_000.0,
                                  float(s["capital_m"]), step=1.0,
                                  help="App dùng số này để tính nên mua bao nhiêu cổ phiếu. Ví dụ 10 = 10 triệu đồng.")
        st.markdown("**Danh sách mã theo dõi**")
        opts = _available_symbols()
        watch = st.multiselect("Các mã hiện ở trang Tổng quan", opts, default=[w for w in s["watch"] if w in opts],
                               help="Mã ngoài danh sách này cần tải dữ liệu trước (xem trang Hướng dẫn).")
        st.markdown("**Mức an toàn mặc định cho trang “Tính lệnh mua”**")
        a, b = st.columns(2)
        risk_pct = a.slider("Chấp nhận mất tối đa bao nhiêu % vốn nếu một lệnh sai?", 0.5, 5.0, float(s["risk_pct"]), 0.5,
                            format="%.1f%%", help="Người mới nên để 1–2%.")
        max_alloc = b.slider("Tối đa bao nhiêu % vốn dồn vào một mã?", 10, 50, int(s["max_alloc"]), 5, format="%d%%",
                             help="Không nên bỏ hết trứng vào một giỏ.")
        if st.form_submit_button(":material/save: Lưu cài đặt", type="primary"):
            if not watch:
                st.error("Cần chọn ít nhất một mã để theo dõi.")
            else:
                saved = settings.save({"capital_m": capital, "watch": watch, "risk_pct": risk_pct, "max_alloc": max_alloc,
                                    "auto_price": s.get("auto_price", True),
                                    "simple_mode": s.get("simple_mode", False)})
                s.update(saved)
                st.toast("Đã lưu cài đặt", icon=":material/check_circle:")
                st.success(f"Đã lưu: vốn {explain.money_short(saved['capital_m'] * 1e6)}, theo dõi {len(saved['watch'])} mã.")
    if st.button("Khôi phục mặc định"):
        s.update(settings.save(dict(settings.DEFAULTS)))
        st.rerun()

    ui.section("Giao diện")
    st.toggle("Chế độ đơn giản (ẩn các trang nâng cao)", value=bool(s.get("simple_mode", False)), key="w_simple", on_change=_save_simple,
              help="Ẩn các trang Mua dần, Báo cáo tháng và Nghiên cứu (nâng cao) cho gọn. Dữ liệu không mất, tắt đi là hiện lại.")
    ui.section("Dữ liệu giá")
    st.toggle("Tự động cập nhật giá trong giờ giao dịch", value=bool(s.get("auto_price", True)), key="w_auto_price", on_change=_save_auto,
              help=f"Khi app đang mở, cứ {data_update.AUTO_MINUTES} phút tải giá mới (9:00 đến 15:05, thứ Hai đến thứ Sáu) rồi làm mới trang. "
                   "Đây là cập nhật định kỳ, không phải giá từng giây như bảng điện của công ty chứng khoán.")
    st.caption(data_update.auto_status())
    data_update.render_panel(ctx)

    _inbox_section()
    _backup_section()

    ui.section("Thông tin hệ thống")
    c1, c2 = st.columns(2)
    with c1:
        ui.stat_card("AI", shared.ai_name(), "Đã bật" if shared.ai_ready() else "Chưa bật (tuỳ chọn). Xem trang Hướng dẫn.")
    with c2:
        df, src = shared.load("VNINDEX")
        nguon = {"csv": "File CSV trên máy", "demo": "Giả lập (chưa có dữ liệu thật)"}.get(src, src)
        ui.stat_card("Dữ liệu giá", nguon, f"Đến hết phiên {df['date'].iloc[-1]:%d/%m/%Y}" if len(df) else "")
    st.caption(f"Cài đặt được lưu tại: {Path(settings.PATH)}")
