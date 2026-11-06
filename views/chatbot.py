"""Chatbot AI nổi ở góc dưới bên phải mọi trang. Đọc toàn bộ dữ liệu của bạn và giá hiện tại để trả lời; chỉ trả lời, không đặt lệnh, không sửa dữ liệu."""
from __future__ import annotations

import datetime as dt
import html
import time

import streamlit as st

from src import alerts, benchmark, cashflow, chat_context, chat_store, dividends, explain, journal, llm, news as newsmod, portfolio, risk_table, trade_parse, ui, updater
from views import alert_banner, health_view, shared

BUSY_SECONDS = 120   # trong lúc AI đang trả lời, chặn việc tự làm mới cả trang (nếu không câu trả lời bị cắt ngang và mất)
AVATAR = {"user": ":material/person:", "assistant": ":material/auto_awesome:"}
SUGGEST = ["Giờ mua thêm cổ phiếu có ổn không?", "Danh mục của tôi đang có rủi ro gì?", "Tôi đã mắc lỗi gì trong các lệnh vừa rồi?"]


def _price(sym: str):
    return alert_banner._last_price(sym)


def gather(ctx, share: bool = True) -> dict:
    """Dựng ngữ cảnh đầy đủ. share=False thì chỉ gồm giá thị trường và cài đặt, không có dữ liệu cá nhân."""
    now = dt.datetime.now(explain.VN_TZ)
    s = st.session_state
    settings = {"capital_m": s.get("capital_m", 10.0), "risk_pct": s.get("risk_pct", 2.0), "max_alloc": s.get("max_alloc", 30), "watch": list(ctx.watchlist)}
    pf = portfolio.load() if share else {"holdings": [], "cash": 0.0}
    trades = journal.list_trades() if share else journal.list_trades(None).iloc[0:0]
    capital = float(settings["capital_m"]) * 1_000_000
    valuation, vs = portfolio.valuate(pf, _price, settings["max_alloc"] / 100, capital)
    flows = cashflow.list_flows() if share else cashflow.list_flows().iloc[0:0]
    cf = cashflow.summary(flows, vs["total"])
    divs = dividends.list_all() if share else dividends.list_all().iloc[0:0]
    dsum = dividends.summary(divs, float((valuation["avg_cost"] * valuation["qty"]).sum()) if len(valuation) else 0.0)
    idx, _ = shared.load_long("VNINDEX")
    bench = benchmark.compare(flows, vs["total"], idx) if share else None
    open_t = trades[trades["exit_price"].isna()] if len(trades) else None
    risk_s = risk_table.build(valuation, open_t, pf["cash"], settings["risk_pct"], capital)[1] if len(valuation) else None
    page = chat_context.describe_page(st.session_state.get("current_page"), st.session_state)
    viewing = [page["ma_dang_xem"]] if page and page.get("ma_dang_xem") else []
    watch_syms = list(dict.fromkeys(viewing + list(valuation["symbol"] if len(valuation) else []) + settings["watch"]))
    snaps, _ = shared.snapshot(tuple(watch_syms))
    held_syms = list(valuation["symbol"]) if len(valuation) else []
    try:
        items = shared.news_items() if held_syms else []
    except Exception:  # noqa: BLE001
        items = []
    news = {sym: newsmod.match_symbol(items, sym) for sym in held_syms}
    last = updater.last_data_date(["VNINDEX"])
    return chat_context.compose(now, settings, valuation, vs, pf["cash"], trades, flows, cf, divs, dsum, bench, snaps,
                                alert_banner.current() if share else [], risk_s, news, last, page, health_view.gather() if share else [])


def _user_bubble(text: str) -> None:
    """Tin nhắn của bạn, tự vẽ bằng phần tử .chat-u (không phụ thuộc khung nội bộ của Streamlit nên không bị cắt). Nội dung được escape nên không bao giờ chạy HTML."""
    with st.chat_message("user", avatar=AVATAR["user"]):
        st.markdown(f'<div class="chat-u">{html.escape(text)}</div>', unsafe_allow_html=True)


def _tee(entry: dict, pieces):
    """Vừa chuyển từng đoạn chữ cho giao diện, vừa ghi dần vào tin nhắn trong lịch sử, để lỡ bị ngắt giữa chừng
    (trang làm mới, bấm sang chỗ khác, mất mạng) thì câu hỏi và phần trả lời đã có vẫn còn, không biến mất."""
    for piece in pieces:
        entry["content"] += piece
        yield piece


def _stream_answer(ctx, q: str) -> None:
    """Hiện câu hỏi, rồi hiện câu trả lời của AI từng đoạn chữ ngay khi có. Câu hỏi được lưu NGAY; câu trả lời được lưu dần.
    Không sửa ô nhập ở đây (Streamlit cấm sửa widget sau khi đã tạo)."""
    s = st.session_state
    hist = s.setdefault("chat_hist", [])
    prior = [m for m in hist if m.get("content") and not m.get("partial")]
    hist.append({"role": "user", "content": q})
    entry = {"role": "assistant", "content": "", "partial": True}
    hist.append(entry)
    s["chat_busy_until"] = time.time() + BUSY_SECONDS
    try:
        _user_bubble(q)
        with st.chat_message("assistant", avatar=AVATAR["assistant"]):
            try:
                with st.spinner("Đang đọc dữ liệu của bạn..."):
                    context = gather(ctx, bool(s.get("chat_share", True)))
                st.write_stream(_tee(entry, llm.smooth(llm.chat_stream(q, prior, context))))
            except Exception as e:  # noqa: BLE001
                entry["content"] += ("\n\n" if entry["content"] else "") + f"Mình chưa trả lời được ({type(e).__name__}). Bạn thử lại sau ít phút nhé."
                st.markdown(entry["content"])
        entry.pop("partial", None)  # chạy xong trọn vẹn
        if not entry["content"].strip():
            entry["content"] = "Mình chưa có câu trả lời."
    finally:
        s["chat_busy_until"] = 0.0
        chat_store.save(hist)  # lưu cả khi bị ngắt giữa chừng (phần đã có vẫn còn)


# ---------- ghi lệnh bằng chat: bản nháp, bạn duyệt rồi mới ghi ----------
def _find_sell_target(symbol: str, qty: int):
    """Lệnh đang mở trong Nhật ký khớp đúng mã và số lượng. Trả (lệnh hoặc None, giải thích nếu không khớp)."""
    t = journal.list_trades()
    op = t[(t["exit_price"].isna()) & (t["symbol"] == symbol)] if not t.empty else t
    if op is None or len(op) == 0:
        return None, f"Nhật ký không có lệnh đang mở của {symbol}."
    same = op[op["qty"] == qty].sort_values("id")
    if len(same):
        return same.iloc[0], ""
    have = ", ".join(f"{int(r.qty)} cp" for r in op.itertuples())
    return None, f"Nhật ký có lệnh đang mở của {symbol} ({have}) nhưng không có lệnh đúng {qty} cổ phiếu. Bán một phần chưa hỗ trợ ở đây: vào trang Nhật ký để xử lý."


def _say(text: str) -> None:
    """Thêm một tin nhắn của trợ lý vào cuộc trò chuyện (dùng trong callback, chạy trước khi khung chat vẽ lại)."""
    hist = st.session_state.setdefault("chat_hist", [])
    hist.append({"role": "assistant", "content": text})
    chat_store.save(hist)


def _discard_draft() -> None:
    st.session_state.pop("chat_draft", None)
    _say("Đã bỏ bản nháp. Chưa ghi gì vào Nhật ký.")


def _confirm_draft() -> None:
    s = st.session_state
    d = s.get("chat_draft")
    if not d:
        return
    k = lambda n: s.get(f"chat_d{d['id']}_{n}")  # noqa: E731
    try:
        day = pd_date(k("day"))
        if d["side"] == "buy":
            stop, target = float(k("stop") or 0), float(k("target") or 0)
            tid = journal.add_trade(d["symbol"], int(k("qty")), float(k("price")), stop, target or None, (k("reason") or "").strip() or "Ghi qua chatbot", day)
            msg = (f"Đã ghi lệnh MUA {d['symbol']} {int(k('qty'))} cổ phiếu giá {explain.vnd(float(k('price')))} vào Nhật ký (lệnh #{tid}). "
                   "Danh mục chưa tự đổi: vào trang Danh mục, tab “Từ nhật ký” nếu bạn muốn cập nhật.")
        else:
            row, why = _find_sell_target(d["symbol"], int(k("qty")))
            if row is None:
                _say(why)
                return
            journal.close_trade(int(row.id), float(k("price")), day, "Ghi qua chatbot")
            msg = f"Đã đóng lệnh #{int(row.id)} ({d['symbol']}, {int(row.qty)} cổ phiếu) với giá bán {explain.vnd(float(k('price')))} trong Nhật ký. Danh mục chưa tự đổi."
    except (ValueError, TypeError) as e:
        _say(f"Chưa ghi được: {e}")
        return
    s.pop("chat_draft", None)
    _say(msg)


def pd_date(v) -> str:
    return (v.isoformat() if hasattr(v, "isoformat") else str(v))


def _draft_card(d: dict) -> None:
    """Thẻ nháp lệnh: sửa được mọi ô; chỉ khi bấm “Ghi vào Nhật ký” mới ghi."""
    buy = d["side"] == "buy"
    i = d["id"]
    with st.container(border=True, key=f"chat_draftbox_{i}"):
        st.markdown(f"**Nháp lệnh {'MUA' if buy else 'BÁN'} {d['symbol']}**")
        for n in d.get("notes", []):
            st.caption(n)
        c1, c2 = st.columns(2)
        qty = c1.number_input("Số cổ phiếu", min_value=1, value=int(d["qty"]), step=100, key=f"chat_d{i}_qty")
        price = c2.number_input("Giá (đồng)", min_value=0.0, value=float(d["price"] or 0.0), step=50.0, format="%.0f", key=f"chat_d{i}_price")
        stop = target = 0.0
        if buy:
            c3, c4 = st.columns(2)
            stop = c3.number_input("Cắt lỗ (0 = chưa đặt)", min_value=0.0, value=float(d["stop"] or 0.0), step=50.0, format="%.0f", key=f"chat_d{i}_stop")
            target = c4.number_input("Mục tiêu (0 = bỏ trống)", min_value=0.0, value=float(d["target"] or 0.0), step=50.0, format="%.0f", key=f"chat_d{i}_target")
            st.text_input("Lý do mua (bắt buộc)", value=d.get("reason", ""), key=f"chat_d{i}_reason", placeholder="Vì sao bạn mua mã này?")
        st.date_input("Ngày", value=d["date"], max_value=dt.date.today(), format="DD/MM/YYYY", key=f"chat_d{i}_day")
        problems = []
        if price <= 0:
            problems.append("Nhập giá.")
        if buy:
            if not (st.session_state.get(f"chat_d{i}_reason") or "").strip():
                problems.append("Nhập lý do mua.")
            if stop and price and stop >= price:
                problems.append("Cắt lỗ phải thấp hơn giá mua.")
            if target and price and target <= price:
                problems.append("Mục tiêu phải cao hơn giá mua.")
            if qty % 100:
                st.caption("Số cổ phiếu không chia hết cho 100 (lô). Kiểm tra lại nếu bạn mua trên sàn HOSE.")
        else:
            row, why = _find_sell_target(d["symbol"], int(qty))
            if row is None:
                problems.append(why)
            else:
                st.caption(f"Sẽ đóng lệnh #{int(row.id)}: mua {int(row.qty)} cổ phiếu giá {explain.vnd(float(row.entry))}.")
        for p in problems:
            st.caption(f":red[{p}]")
        a, b = st.columns([3, 1])
        a.button(":material/check: Ghi vào Nhật ký", type="primary", key=f"chat_d{i}_ok", on_click=_confirm_draft, disabled=bool(problems), width="stretch")
        b.button("Bỏ", key=f"chat_d{i}_no", on_click=_discard_draft, width="stretch")


def _handle_draft(q: str, d: dict) -> None:
    """Câu bạn gõ giống một lệnh: không gọi AI, chỉ soạn nháp để bạn duyệt."""
    s = st.session_state
    hist = s.setdefault("chat_hist", [])
    d = {**d, "id": int(time.time() * 1000)}
    s["chat_draft"] = d
    hist.append({"role": "user", "content": q})
    reply = (f"Mình hiểu bạn muốn ghi lệnh {'MUA' if d['side'] == 'buy' else 'BÁN'} {d['symbol']}. Mình chưa ghi gì cả: bạn kiểm tra và sửa các ô bên dưới, "
             "rồi bấm “Ghi vào Nhật ký”.")
    hist.append({"role": "assistant", "content": reply})
    chat_store.save(hist)
    _user_bubble(q)
    with st.chat_message("assistant", avatar=AVATAR["assistant"]):
        st.markdown(reply)
    _draft_card(d)


def _clear_chat() -> None:
    """Chạy trước khi khung chat vẽ lại, nên không cần st.rerun."""
    st.session_state["chat_hist"] = []
    st.session_state.pop("chat_draft", None)
    chat_store.save([])


def suggestions() -> list:
    """Câu gợi ý theo trang bạn đang xem (mã đang xem, số đang nhập)."""
    s = st.session_state
    page = s.get("current_page")
    sym = {"stock": s.get("symbol"), "calc": s.get("calc_symbol"), "ask": s.get("ask_sym")}.get(page)
    if page == "stock" and sym:
        return [f"{sym} có đáng mua lúc này không?", f"Rủi ro chính của {sym} là gì?", f"{sym} so với các mã tôi đang giữ thế nào?"]
    if page == "calc":
        return ["Với giá mua và cắt lỗ này tôi nên mua bao nhiêu?", "Mức cắt lỗ này có hợp lý không?", "Lệnh này có vi phạm quy tắc của tôi không?"]
    if page == "portfolio":
        return ["Danh mục của tôi đang có rủi ro gì?", "Tôi có đang dồn quá nhiều vào một mã không?", "Tôi lỗ bao nhiêu và mã nào chưa có cắt lỗ?"]
    if page == "journal":
        return ["Tôi đã mắc lỗi gì trong các lệnh vừa rồi?", "Lệnh nào đang gần cắt lỗ?", "Lệnh nào tôi chưa ghi lý do?"]
    return SUGGEST


def _header(sharing: bool) -> str:
    status = ('<span class="dot on"></span>Đang đọc dữ liệu của bạn' if sharing else '<span class="dot"></span>Chỉ dùng giá thị trường')
    return ('<div class="chat-root"></div><div class="chat-head"><div class="chat-logo"><span class="material-symbols-rounded">auto_awesome</span></div>'
            f'<div><div class="tt">Trợ lý AI</div><div class="st">{status}</div></div></div>')


def _empty(sharing: bool) -> str:
    d = ("Mình đọc được danh mục, nhật ký, tiền nạp/rút, cổ tức và giá hiện tại của bạn để trả lời sát." if sharing
         else "Đang tắt quyền đọc dữ liệu cá nhân, nên mình chỉ biết giá thị trường.")
    return ('<div class="chat-empty"><div class="chat-logo"><span class="material-symbols-rounded">auto_awesome</span></div>'
            f'<div class="t">Xin chào, mình giúp được gì?</div><div class="d">{d}</div></div>')


@st.fragment
def render(ctx) -> None:
    """Là một fragment: gửi câu hỏi, stream câu trả lời, xoá chat... chỉ chạy lại KHUNG CHAT, không chạy lại cả trang, nên phần trang phía sau
    không bị mờ/đứng khi AI đang trả lời (và không bị ngắt giữa chừng khi bạn bấm chỗ khác)."""
    with st.container(key="chatfab"):
        with st.popover(":material/chat_bubble: Hỏi AI", help="Chatbot đọc dữ liệu của bạn để trả lời"):
            if not shared.ai_ready():
                st.markdown(_header(False), unsafe_allow_html=True)
                st.info("Chưa bật AI. Xem trang Hướng dẫn, mục “Bật AI”.")
                return
            if "chat_hist" not in st.session_state:
                st.session_state["chat_hist"] = chat_store.load()  # nạp lại cuộc trò chuyện đã lưu trên máy
            hist = st.session_state["chat_hist"]
            sharing = bool(st.session_state.get("chat_share", True))
            question = ""
            hd, cl = st.columns([6, 1], vertical_alignment="center")
            hd.markdown(_header(sharing), unsafe_allow_html=True)
            cl.button(":material/delete_sweep:", key="chat_clear", help="Xoá cuộc trò chuyện", on_click=_clear_chat, disabled=not hist)
            with st.expander(":material/shield: Quyền riêng tư", expanded=False):
                st.toggle("Cho AI đọc dữ liệu của tôi", key="chat_share", value=True,
                          help="Bật: danh mục, nhật ký, tiền nạp/rút, cổ tức, cài đặt và giá hiện tại được gửi cho nhà cung cấp AI cùng câu hỏi để trả lời sát. "
                               "Tắt: chỉ gửi giá thị trường. Khoá API, mã PIN và thông tin đăng nhập broker không bao giờ được gửi.")
                st.caption("AI chỉ trả lời, không đặt lệnh hay sửa dữ liệu của bạn.")
            box = st.container(height=310, border=False, key="chatbox")
            with box:
                intro = st.empty()  # phần chào + câu gợi ý: biến mất ngay khi bạn gửi câu hỏi đầu tiên
                if not hist:
                    with intro.container():
                        st.markdown(_empty(sharing), unsafe_allow_html=True)
                        for i, sug in enumerate(suggestions()):
                            if st.button(sug, key=f"chat_sug{i}", width="stretch", icon=":material/arrow_outward:"):
                                question = sug
                for m in hist:
                    if m["role"] == "user":
                        _user_bubble(m["content"])
                        continue
                    with st.chat_message("assistant", avatar=AVATAR["assistant"]):
                        st.markdown(m["content"] or "…")
                        if m.get("partial"):
                            st.caption("Câu trả lời bị ngắt giữa chừng (trang vừa làm mới). Bạn hỏi lại nếu cần.")
                if st.session_state.get("chat_draft"):
                    _draft_card(st.session_state["chat_draft"])
            with st.form("chat_form", clear_on_submit=True, border=False):
                a, b = st.columns([8, 1], vertical_alignment="center", gap="small")
                a.text_input("Câu hỏi", key="chat_q", placeholder="Hỏi về danh mục, giá, có nên mua...", max_chars=600, label_visibility="collapsed")
                if b.form_submit_button(":material/arrow_upward:", key="chat_send", type="primary"):
                    question = (st.session_state.get("chat_q") or "").strip()
            st.markdown('<div class="chat-foot">AI có thể sai. Đây là quan điểm tham khảo, bạn là người quyết định.</div>', unsafe_allow_html=True)
            if question:  # stream vào khung chat đã có ở trên: chữ hiện dần, không cần chạy lại cả trang
                intro.empty()
                known = list(ctx.watchlist) + [h["symbol"] for h in portfolio.load()["holdings"]]
                draft = trade_parse.parse(question[:600], dt.date.today(), known)
                with box:
                    if draft:
                        _handle_draft(question[:600], draft)
                    else:
                        _stream_answer(ctx, question[:600])
