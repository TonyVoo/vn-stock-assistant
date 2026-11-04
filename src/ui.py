"""Thành phần giao diện dùng chung: bảng màu, CSS, huy hiệu, thẻ giá, dải chỉ số...

Phong cách: Simplize (dữ liệu dày, dải chỉ số, huy hiệu % có nền) + Linear (nền tối trung tính, viền mảnh 1px,
chữ nhỏ gọn, một màu nhấn duy nhất, không bóng đổ, không emoji).
Màu theo thị trường Việt Nam: xanh = tăng, đỏ = giảm, vàng = đứng giá/lưu ý.
Mọi chuỗi động (đặc biệt từ AI) đều được escape trước khi chèn vào HTML.
"""
from __future__ import annotations

import html
from string import Template
from typing import Dict, Iterable, List, Optional, Tuple

import streamlit as st

DARK: Dict[str, str] = dict(
    bg="#0A0B0D", card="#101114", card2="#15171B", line="#1D2026", ink="#F2F3F5", soft="#8B909A", brand="#5E6AD2",
    up="#3DD68C", up_bg="rgba(61,214,140,.12)", down="#F2555A", down_bg="rgba(242,85,90,.12)",
    flat="#E5B64A", flat_bg="rgba(229,182,74,.12)", info="#8C99F2", info_bg="rgba(94,106,210,.16)",
    muted="#9BA1AB", muted_bg="rgba(255,255,255,.06)", grid="#15181D",
    chart_up="#3DD68C", chart_down="#F2555A", chart_flat="#E5B64A",
    c_info_bg="rgba(94,106,210,.10)", c_info_bd="rgba(94,106,210,.45)", c_info_fg="#C7CCF7",
    c_warn_bg="rgba(229,182,74,.08)", c_warn_bd="rgba(229,182,74,.45)", c_warn_fg="#F1D58C",
    c_bad_bg="rgba(242,85,90,.08)", c_bad_bd="rgba(242,85,90,.45)", c_bad_fg="#F8B4B6",
    c_good_bg="rgba(61,214,140,.08)", c_good_bd="rgba(61,214,140,.45)", c_good_fg="#A7EBCB",
)
THEMES: Dict[str, Dict[str, str]] = {"dark": DARK}


def theme_type() -> str:
    return "dark"


def tokens() -> Dict[str, str]:
    return DARK


CSS = Template("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, .stApp, .stApp p, .stApp label, .stApp button, .stApp input, .stApp textarea, .stApp h1, .stApp h2, .stApp h3, .stApp h4
{font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;}
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"]{font-family:'Material Symbols Rounded' !important;}
.stApp{font-variant-numeric:tabular-nums;font-size:14px;color:$ink;-webkit-font-smoothing:antialiased;}
[data-testid="stAppDeployButton"], [data-testid="stDecoration"], footer{display:none !important;}
[data-testid="stHeader"]{background:$bg;border-bottom:1px solid $line;}
.block-container{max-width:1280px;padding-top:4.4rem;padding-bottom:4rem;}
h1,h2,h3,h4{color:$ink;letter-spacing:-0.015em;font-weight:600;}
h3{margin-top:1.6rem;font-size:1.05rem;} h4{font-size:.95rem;}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:10px;border:1px solid $line;background:$card;box-shadow:none;}
[data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"]{border-radius:8px !important;border-color:$line !important;}
.stButton>button,.stFormSubmitButton>button{border-radius:8px;font-weight:500;font-size:.86rem;min-height:2.15rem;}
.stButton>button[kind="secondary"]{background:transparent;border:1px solid $line;color:$ink;}
.stButton>button[kind="secondary"]:hover{background:$card2;border-color:#2A2E36;}
[data-baseweb="tab-list"]{border-bottom:1px solid $line;gap:4px;}
[data-baseweb="tag"]{background:$info_bg !important;border-radius:6px !important;}
[data-baseweb="tag"] span{color:$info !important;}
[data-testid="stMetric"]{background:$card;border:1px solid $line;border-radius:10px;padding:12px 14px;}
[data-testid="stExpander"]{border-radius:10px;border:1px solid $line;background:$card;}
.eyebrow{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:$soft;font-weight:600;}
.page-title{font-size:1.5rem;font-weight:600;margin:0 0 .15rem 0;color:$ink;letter-spacing:-0.02em;}
.page-sub{color:$soft;font-size:.9rem;margin-bottom:1.1rem;}
.card{background:$card;border:1px solid $line;border-radius:10px;padding:14px 16px;margin-bottom:10px;}
.stat .label{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:$soft;font-weight:600;}
.stat .value{font-size:1.45rem;font-weight:600;color:$ink;line-height:1.3;margin-top:2px;}
.stat .sub{font-size:.8rem;color:$soft;margin-top:2px;}
.stat .sub.up{color:$up;} .stat .sub.down{color:$down;} .stat .sub.flat{color:$flat;}
.badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.72rem;font-weight:500;white-space:nowrap;line-height:1.5;}
.b-up{background:$up_bg;color:$up;} .b-down{background:$down_bg;color:$down;} .b-flat{background:$flat_bg;color:$flat;}
.b-info{background:$info_bg;color:$info;} .b-muted{background:$muted_bg;color:$muted;}
.chg::before{content:"";display:inline-block;margin-right:5px;vertical-align:1px;border-left:4px solid transparent;border-right:4px solid transparent;}
.chg.b-up::before{border-bottom:6px solid currentColor;} .chg.b-down::before{border-top:6px solid currentColor;}
.chg.b-flat::before{border:0;width:7px;height:2px;border-radius:1px;background:currentColor;vertical-align:3px;}
.up{color:$up;} .down{color:$down;} .flat{color:$flat;}
.strip{display:flex;gap:8px;overflow-x:auto;padding:2px 0 14px 0;scrollbar-width:none;}
.strip::-webkit-scrollbar{display:none;}
.tk{display:flex;align-items:center;gap:8px;white-space:nowrap;background:$card;border:1px solid $line;border-radius:8px;padding:5px 10px;font-size:.78rem;}
.tk .n{color:$soft;font-weight:500;} .tk .v{color:$ink;font-weight:600;}
.hero .row1{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.hero .sym{font-size:1.5rem;font-weight:600;color:$ink;letter-spacing:-0.02em;}
.hero .tag{font-size:.68rem;font-weight:600;color:$muted;background:$muted_bg;border-radius:5px;padding:2px 7px;letter-spacing:.04em;}
.hero .row2{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-top:4px;}
.hero .px{font-size:2.3rem;font-weight:600;color:$ink;letter-spacing:-0.03em;line-height:1.15;}
.hero .abs{font-size:1rem;font-weight:500;}
.hero .pillbig{font-size:.82rem;padding:3px 9px;}
.hero .note{color:$soft;font-size:.8rem;margin-top:4px;}
.rangebar{margin:10px 0 2px 0;} .rangebar .track{height:4px;border-radius:99px;background:$muted_bg;position:relative;}
.rangebar .fill{position:absolute;top:0;bottom:0;border-radius:99px;background:linear-gradient(90deg,$down,$flat,$up);opacity:.7;left:0;right:0;}
.rangebar .dot{position:absolute;top:-4px;width:12px;height:12px;border-radius:50%;background:$ink;border:2px solid $card;transform:translateX(-50%);}
.rangebar .ends{display:flex;justify-content:space-between;font-size:.74rem;color:$soft;margin-top:8px;}
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px 18px;}
.sgrid .l{font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:$soft;font-weight:600;} .sgrid .v{font-size:.95rem;font-weight:600;color:$ink;margin-top:2px;}
.assess .r{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid $line;}
.assess .r:last-child{border-bottom:none;} .assess .k{color:$ink;font-size:.86rem;font-weight:500;}
.callout{border-radius:8px;padding:11px 14px;margin:8px 0 14px 0;font-size:.9rem;line-height:1.55;border:1px solid;border-left-width:3px;}
.c-info{background:$c_info_bg;border-color:$c_info_bd;color:$c_info_fg;} .c-warn{background:$c_warn_bg;border-color:$c_warn_bd;color:$c_warn_fg;}
.c-bad{background:$c_bad_bg;border-color:$c_bad_bd;color:$c_bad_fg;} .c-good{background:$c_good_bg;border-color:$c_good_bd;color:$c_good_fg;}
.big{font-size:1.9rem;font-weight:600;line-height:1.2;color:$ink;letter-spacing:-0.02em;} .bigsub{color:$soft;font-size:.88rem;}
.kv{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid $line;font-size:.88rem;}
.kv:last-child{border-bottom:none;} .kv span:first-child{color:$soft;} .kv span:last-child{font-weight:600;color:$ink;}
.item{padding:10px 0;border-bottom:1px solid $line;} .item:last-child{border-bottom:none;}
.item .t{font-weight:600;color:$ink;font-size:.9rem;} .item .d{color:$soft;font-size:.85rem;margin-top:2px;}
.hint{color:$soft;font-size:.8rem;}
.sec{display:flex;justify-content:space-between;align-items:baseline;margin:1.5rem 0 .5rem 0;}
.sec .h{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;font-weight:600;color:$soft;} .sec .s{color:$soft;font-size:.8rem;}
.steps .st{display:flex;gap:12px;align-items:flex-start;padding:7px 0;}
.steps .n{flex:0 0 22px;height:22px;border-radius:6px;background:$info_bg;color:$info;font-weight:600;font-size:.75rem;display:flex;align-items:center;justify-content:center;}
.steps .tx{color:$ink;font-size:.88rem;line-height:1.5;padding-top:1px;}
</style>
""")


def inject_css() -> None:
    st.markdown(CSS.safe_substitute(tokens()), unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def badge(text: str, kind: str = "muted") -> str:
    return f'<span class="badge b-{kind}">{esc(text)}</span>'


def change_kind(x: Optional[float]) -> str:
    if x is None or x != x:
        return "muted"
    return "up" if x > 0 else "down" if x < 0 else "flat"


def change_pill(frac: Optional[float], decimals: int = 2, big: bool = False) -> str:
    """Huy hiệu % có nền tô nhạt; mũi tên là hình tam giác vẽ bằng CSS (không dùng emoji/ký tự đặc biệt)."""
    from . import explain
    if frac is None or frac != frac:
        return badge("—", "muted")
    k = change_kind(frac)
    cls = "badge chg b-%s%s" % (k, " pillbig" if big else "")
    return f'<span class="{cls}">{explain.pct(abs(frac), decimals, signed=False)}</span>'


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="page-title">{esc(title)}</div><div class="page-sub">{esc(subtitle)}</div>',
                unsafe_allow_html=True)


def section(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="sec"><span class="h">{esc(title)}</span><span class="s">{esc(sub)}</span></div>',
                unsafe_allow_html=True)


def callout(text: str, kind: str = "info", title: Optional[str] = None) -> None:
    """kind: info | warn | bad | good. `text` được escape; xuống dòng bằng \\n."""
    body = esc(text).replace("\n", "<br>")
    head = f"<b>{esc(title)}</b><br>" if title else ""
    st.markdown(f'<div class="callout c-{kind}">{head}{body}</div>', unsafe_allow_html=True)


def stat_card(label: str, value: str, sub: str = "", kind: str = "") -> None:
    st.markdown(f'<div class="card stat"><div class="label">{esc(label)}</div>'
                f'<div class="value">{esc(value)}</div><div class="sub {kind}">{esc(sub)}</div></div>',
                unsafe_allow_html=True)


def kv_rows(rows: Iterable[tuple]) -> str:
    return "".join(f'<div class="kv"><span>{esc(k)}</span><span>{esc(v)}</span></div>' for k, v in rows)


def steps(items: List[str]) -> None:
    body = "".join(f'<div class="st"><div class="n">{i}</div><div class="tx">{t}</div></div>'
                   for i, t in enumerate(items, 1))  # t là HTML tin cậy do code viết, không phải dữ liệu ngoài
    st.markdown(f'<div class="card steps">{body}</div>', unsafe_allow_html=True)


def ticker_strip(items: List[Tuple[str, str, Optional[float]]]) -> None:
    """Dải chỉ số ở đầu trang: (tên, giá trị đã định dạng, thay đổi dạng phân số hoặc None)."""
    if not items:
        return
    cells = "".join(f'<div class="tk"><span class="n">{esc(n)}</span><span class="v">{esc(v)}</span>'
                    f'{change_pill(c) if c is not None else ""}</div>' for n, v, c in items)
    st.markdown(f'<div class="strip">{cells}</div>', unsafe_allow_html=True)


def price_hero(symbol: str, tags: List[str], price: str, abs_change: str, frac: float, note: str = "") -> None:
    k = change_kind(frac)
    tg = "".join(f'<span class="tag">{esc(t)}</span>' for t in tags)
    st.markdown(f'<div class="hero"><div class="row1"><span class="sym">{esc(symbol)}</span>{tg}</div>'
                f'<div class="row2"><span class="px">{esc(price)}</span><span class="abs {k}">{esc(abs_change)}</span>'
                f'{change_pill(frac, 2, big=True)}</div><div class="note">{esc(note)}</div></div>', unsafe_allow_html=True)


def range_bar(low: float, high: float, last: float, left: str, right: str) -> str:
    span = (high - low) or 1.0
    pos = min(max((last - low) / span, 0.0), 1.0) * 100
    return (f'<div class="rangebar"><div class="track"><div class="fill"></div><div class="dot" style="left:{pos:.1f}%"></div></div>'
            f'<div class="ends"><span>{esc(left)}</span><span>{esc(right)}</span></div></div>')


def stat_grid(rows: List[Tuple[str, str]]) -> str:
    return '<div class="sgrid">' + "".join(f'<div><div class="l">{esc(l)}</div><div class="v">{esc(v)}</div></div>'
                                           for l, v in rows) + "</div>"


def sparkline(values, kind: str = "flat", w: int = 220, h: int = 44) -> str:
    vals = [float(v) for v in values if v == v]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pts = [(i * (w - 4) / (len(vals) - 1) + 2, h - 4 - (v - lo) / span * (h - 8)) for i, v in enumerate(vals)]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    t = tokens()
    color = {"up": t["chart_up"], "down": t["chart_down"]}.get(kind, t["chart_flat"])
    area = f"2,{h} " + path + f" {w - 2},{h}"
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none">'
            f'<polygon points="{area}" fill="{color}" opacity=".10"/>'
            f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')
