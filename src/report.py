"""Báo cáo tháng: gom số liệu của một tháng và xuất ra Excel hoặc PDF (tiếng Việt có dấu).

Mọi số liệu lấy từ dữ liệu có sẵn trên máy bạn (Danh mục, Nhật ký, Tiền nạp/rút, Cổ tức); báo cáo KHÔNG tự suy đoán thêm.
Lãi/lỗ lệnh đã bán tính sau phí và thuế (giống trang Nhật ký).
"""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import cashflow, dividends, explain, journal, journal_stats, portfolio

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _font(cands: List[str]) -> Optional[str]:
    return next((c for c in cands if Path(c).exists()), None)


def pdf_available() -> bool:
    try:
        import fpdf  # noqa: F401
    except ImportError:
        return False
    return _font(FONT_CANDIDATES) is not None


def month_range(year: int, month: int):
    start = pd.Timestamp(year=year, month=month, day=1)
    return start, start + pd.offsets.MonthBegin(1)


def _in_month(series: pd.Series, start, end) -> pd.Series:
    d = pd.to_datetime(series, errors="coerce")
    return (d >= start) & (d < end)


def collect(year: int, month: int, last_price: Callable[[str], Optional[float]], jpath=None, cpath=None, dpath=None,
            pf_path=None, today: Optional[date] = None) -> Dict:
    """Gom dữ liệu của tháng. Các đường dẫn chỉ dùng khi kiểm thử."""
    if not 1 <= month <= 12:
        raise ValueError("Tháng phải từ 1 đến 12.")
    start, end = month_range(year, month)
    pf = portfolio.load(pf_path)
    val, s = portfolio.valuate(pf, last_price)
    trades = journal.list_trades(jpath)
    if trades.empty:
        closed = opened = pd.DataFrame()
    else:
        closed = trades[trades["exit_price"].notna() & _in_month(trades["closed"], start, end)].copy()
        opened = trades[_in_month(trades["opened"], start, end)].copy()
    flows = cashflow.list_flows(cpath)
    m_flows = flows[(flows["day"] >= start) & (flows["day"] < end)] if len(flows) else flows
    cf = cashflow.summary(flows, s["total"], today)
    divs = dividends.list_all(dpath)
    m_divs = divs[(divs["day"] >= start) & (divs["day"] < end)] if len(divs) else divs
    enriched = journal_stats.enrich(closed) if len(closed) else journal_stats.enrich(None)
    return {"year": year, "month": month, "start": start, "end": end, "summary": s, "valuation": val, "cash": pf["cash"],
            "cashflow_summary": cf, "flows": m_flows, "closed": closed, "opened": opened, "dividends": m_divs,
            "journal": journal_stats.summary(enriched), "insights": journal_stats.insights(enriched) if len(enriched) else [],
            "realized": float(closed["pnl"].sum()) if len(closed) else 0.0,
            "div_cash": float(m_divs.loc[m_divs["kind"] == dividends.CASH, "amount"].sum()) if len(m_divs) else 0.0}


def _tables(d: Dict) -> Dict[str, pd.DataFrame]:
    """Các bảng dùng chung cho Excel và PDF (đã đặt tên cột tiếng Việt, số giữ nguyên dạng số)."""
    v = d["valuation"]
    out = {
        "Danh mục hiện tại": pd.DataFrame({"Mã": v["symbol"], "Số lượng": v["qty"], "Giá vốn": v["avg_cost"], "Giá hiện tại": v["price"],
                                           "Giá trị": v["value"], "Lãi/lỗ": v["pnl"], "Tỷ trọng": v["weight"]}) if len(v) else pd.DataFrame(),
    }
    c = d["closed"]
    out["Lệnh đã bán trong tháng"] = (pd.DataFrame({"Mã": c["symbol"], "Ngày mua": c["opened"], "Ngày bán": c["closed"], "Số lượng": c["qty"],
                                                    "Giá mua": c["entry"], "Giá bán": c["exit_price"], "Lãi/lỗ sau phí": c["pnl"]})
                                      if len(c) else pd.DataFrame())
    o = d["opened"]
    out["Lệnh mở trong tháng"] = (pd.DataFrame({"Mã": o["symbol"], "Ngày mua": o["opened"], "Số lượng": o["qty"], "Giá mua": o["entry"],
                                                "Cắt lỗ": o["stop"], "Lý do": o["reason"]}) if len(o) else pd.DataFrame())
    f = d["flows"]
    out["Tiền nạp/rút"] = (pd.DataFrame({"Ngày": f["day"].dt.strftime("%d/%m/%Y"), "Số tiền": f["amount"], "Ghi chú": f.get("note", "")})
                           if len(f) else pd.DataFrame())
    dv = d["dividends"]
    out["Cổ tức"] = (pd.DataFrame({"Ngày": dv["day"].dt.strftime("%d/%m/%Y"), "Mã": dv["symbol"], "Loại": dv["kind"].map(dividends.LABEL),
                                   "Số nhận": dv["amount"]}) if len(dv) else pd.DataFrame())
    return out


def _overview_rows(d: Dict) -> List[tuple]:
    s, cf, j = d["summary"], d["cashflow_summary"], d["journal"]
    rows = [("Tổng tài sản hiện tại", explain.vnd(s["total"])), ("Giá trị cổ phiếu", explain.vnd(s["stock_value"])),
            ("Tiền mặt", explain.vnd(s["cash"])), ("Lãi/lỗ chưa bán (theo giá vốn)", explain.vnd(s["pnl"]))]
    if cf.get("n"):
        rows += [("Tiền ròng đã bỏ vào (từ trước đến nay)", explain.vnd(cf["net_in"])), ("Lãi/lỗ thật (từ trước đến nay)", explain.vnd(cf["pnl"]))]
    rows += [("Lãi/lỗ lệnh đã bán trong tháng (sau phí)", explain.vnd(d["realized"])), ("Số lệnh đã bán trong tháng", str(len(d["closed"]))),
             ("Số lệnh mở trong tháng", str(len(d["opened"]))), ("Cổ tức tiền mặt nhận trong tháng", explain.vnd(d["div_cash"]))]
    if j.get("n"):
        rows.append(("Tỷ lệ lệnh thắng trong tháng", f"{j['win_rate'] * 100:.0f}% ({j['n']} lệnh)".replace(".", ",")))
    return rows


def to_excel(d: Dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(_overview_rows(d), columns=["Chỉ tiêu", f"Tháng {d['month']:02d}/{d['year']}"]).to_excel(xw, sheet_name="Tổng quan", index=False)
        for name, df in _tables(d).items():
            (df if len(df) else pd.DataFrame({"Thông báo": ["Không có dữ liệu trong tháng này"]})).to_excel(xw, sheet_name=re.sub(r"[\\/*?:\[\]]", "-", name)[:31], index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 3, 48)
    return buf.getvalue()


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, float):
        return explain.num(v, 2) if abs(v) < 1 else explain.num(v)
    return str(v)


def to_pdf(d: Dict) -> bytes:
    if not pdf_available():
        raise RuntimeError("Chưa thể tạo PDF (thiếu thư viện fpdf2 hoặc phông chữ hỗ trợ tiếng Việt). Hãy dùng Excel.")
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, 15)
    regular, bold = _font(FONT_CANDIDATES), _font(FONT_BOLD_CANDIDATES) or _font(FONT_CANDIDATES)
    pdf.add_font("VN", "", regular)
    pdf.add_font("VN", "B", bold)
    pdf.add_page()
    pdf.set_font("VN", "B", 18)
    pdf.cell(0, 10, f"Báo cáo tháng {d['month']:02d}/{d['year']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("VN", "", 9)
    pdf.set_text_color(110)
    pdf.cell(0, 6, f"Tạo ngày {date.today():%d/%m/%Y} từ dữ liệu trên máy bạn. Chỉ để tham khảo, không phải lời khuyên đầu tư.",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(3)
    pdf.set_font("VN", "B", 12)
    pdf.cell(0, 8, "Tổng quan", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("VN", "", 10)
    for k, v in _overview_rows(d):
        pdf.cell(120, 6.5, k)
        pdf.cell(0, 6.5, v, align="R", new_x="LMARGIN", new_y="NEXT")
    for name, df in _tables(d).items():
        pdf.ln(4)
        pdf.set_font("VN", "B", 12)
        pdf.cell(0, 8, name, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("VN", "", 9)
        if not len(df):
            pdf.cell(0, 6, "Không có dữ liệu trong tháng này.", new_x="LMARGIN", new_y="NEXT")
            continue
        cols = [c for c in df.columns if c != "Lý do"] if name == "Lệnh mở trong tháng" else list(df.columns)
        w = 190 / len(cols)
        pdf.set_font("VN", "B", 9)
        for c in cols:
            pdf.cell(w, 6.5, c, border="B")
        pdf.ln()
        pdf.set_font("VN", "", 9)
        for _, r in df.head(60).iterrows():
            for c in cols:
                pdf.cell(w, 6, _cell(r[c])[:22])
            pdf.ln()
    if d["insights"]:
        pdf.ln(4)
        pdf.set_font("VN", "B", 12)
        pdf.cell(0, 8, "Nhận xét từ Nhật ký", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("VN", "", 10)
        for t in d["insights"]:
            pdf.multi_cell(0, 6, "- " + t, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
