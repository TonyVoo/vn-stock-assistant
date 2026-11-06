"""Gom TOÀN BỘ dữ liệu cá nhân và giá hiện tại thành một bản tóm tắt gọn cho chatbot AI.

Chỉ gồm dữ liệu bạn đã nhập vào app (danh mục, nhật ký, tiền nạp/rút, cổ tức, cài đặt) và giá/tin công khai.
KHÔNG BAO GIỜ gồm khoá API, mã PIN, hay thông tin đăng nhập TCBS. Giới hạn độ dài để câu hỏi không quá lớn: lệnh cũ nhất bị bỏ trước.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional

import pandas as pd

MAX_CHARS = 30_000
PAGE_TITLES = {"overview": "Tổng quan", "stock": "Tra cứu cổ phiếu", "ask": "Hỏi trợ lý", "calc": "Tính lệnh mua", "dca": "Mua dần",
               "portfolio": "Danh mục", "journal": "Nhật ký giao dịch", "report": "Báo cáo tháng", "research": "Nghiên cứu (nâng cao)",
               "guide": "Hướng dẫn", "settings": "Cài đặt"}


def describe_page(page: Optional[str], state: Dict) -> Optional[Dict]:
    """Người dùng đang ở trang nào, đang xem mã nào, đang nhập số gì. Để chatbot hiểu “mã này”, “số này”, “ở đây”."""
    if not page or page not in PAGE_TITLES:
        return None
    info: Dict = {"ten_trang": PAGE_TITLES[page]}
    sym = {"stock": state.get("symbol"), "calc": state.get("calc_symbol"), "ask": state.get("ask_sym")}.get(page)
    if sym:
        info["ma_dang_xem"] = str(sym).upper()
    if page == "calc":
        info["thong_so_nguoi_dung_dang_nhap"] = {"gia_mua": state.get("calc_entry"), "gia_cat_lo": state.get("calc_stop"), "gia_muc_tieu": state.get("calc_target")}
    elif page == "ask":
        info["thong_so_nguoi_dung_dang_nhap"] = {"so_tien_dinh_bo_ra": state.get("ask_budget"), "chia_lan_mua": state.get("ask_tr")}
    elif page == "dca":
        info["thong_so_nguoi_dung_dang_nhap"] = {"cac_ma": state.get("dca_syms"), "so_tien_moi_thang": state.get("dca_budget"), "so_thang": state.get("dca_months")}
    info["huong_dan"] = "Khi người dùng nói “mã này”, “ở đây”, “số này” hãy hiểu theo trang đang xem này."
    return info
MAX_CLOSED, MAX_FLOWS, MAX_DIVS = 40, 24, 20


def _r(x, nd: int = 0):
    if x is None:
        return None
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), nd) if nd else int(round(float(x)))
    except (TypeError, ValueError):
        return None


def _d(x) -> Optional[str]:
    try:
        return pd.Timestamp(x).date().isoformat()
    except (ValueError, TypeError):
        return None if x in (None, "", "Không rõ") else str(x)


def _text(x, n: int = 200) -> str:
    return "" if x is None or (isinstance(x, float) and x != x) else str(x)[:n]


def compose(now, settings: Dict, valuation: pd.DataFrame, val_summary: Dict, pf_cash: float, trades: pd.DataFrame,
            flows: pd.DataFrame, cf_summary: Dict, divs: pd.DataFrame, div_summary: Dict, bench: Optional[Dict],
            snaps: List[Dict], alert_items: List[Dict], risk_summary: Optional[Dict], news: Dict[str, List[Dict]],
            last_data_date=None, page: Optional[Dict] = None, health: Optional[List[Dict]] = None) -> Dict:
    held = []
    for r in valuation.itertuples() if len(valuation) else []:
        held.append({"ma": r.symbol, "so_luong": _r(r.qty), "gia_von": _r(r.avg_cost), "gia_hien_tai": _r(r.price), "nguon_gia": r.price_src,
                     "gia_tri": _r(r.value), "lai_lo_pct": _r(r.pnl_pct * 100, 1) if r.pnl_pct is not None else None, "ty_trong_pct": _r(r.weight * 100, 1)})
    open_t, closed_t = [], []
    if trades is not None and len(trades):
        for t in trades.itertuples():
            base = {"id": int(t.id), "ma": t.symbol, "so_luong": int(t.qty), "gia_mua": _r(t.entry), "ngay_mua": _d(t.opened),
                    "cat_lo": _r(t.stop) or None, "muc_tieu": _r(t.target) if t.target == t.target and t.target else None,
                    "ly_do": _text(t.reason), "the": _text(getattr(t, "tags", "")).replace("|", ", ")}
            if t.exit_price == t.exit_price and t.exit_price is not None:
                base.update({"gia_ban": _r(t.exit_price), "ngay_ban": _d(t.closed), "lai_lo_sau_phi": _r(t.pnl), "ghi_chu_khi_ban": _text(t.note)})
                closed_t.append(base)
            else:
                open_t.append(base)
    held_syms = [h["ma"] for h in held]
    journal_open = {t["ma"] for t in open_t}
    no_stop_in_journal = sorted({t["ma"] for t in open_t if not t["cat_lo"]})
    base = val_summary.get("base") or val_summary.get("total") or 0
    pnl = val_summary.get("pnl")
    precomputed = {
        "luu_y": "Đây là các con số đã được tính sẵn và đã gắn nhãn đúng nghĩa. Hãy trích lại đúng nhãn, không tự tính lại hay đổi nghĩa.",
        "lai_lo_cua_phan_co_phieu_so_voi_gia_von_pct": _r(val_summary["pnl_pct"] * 100, 1) if val_summary.get("pnl_pct") is not None else None,
        "lai_lo_cua_phan_co_phieu_dong": _r(pnl),
        "lai_lo_so_voi_TONG_tai_san_pct": _r(pnl / base * 100, 1) if (pnl is not None and base) else None,
        "co_phieu_chiem_pct_tong_tai_san": _r(val_summary.get("stock_value", 0) / base * 100, 1) if base else None,
        "tien_chua_dau_tu_chiem_pct_tong_tai_san": _r((pf_cash + val_summary.get("assumed_cash", 0)) / base * 100, 1) if base else None,
        "ty_trong_tung_ma_pct": {h["ma"]: h["ty_trong_pct"] for h in held},
        "ma_dang_giu_nhung_CHUA_co_lenh_trong_nhat_ky": sorted(set(held_syms) - journal_open),
        "ma_co_lenh_trong_nhat_ky_nhung_CHUA_dat_cat_lo": no_stop_in_journal,
        "ma_co_lenh_trong_nhat_ky_va_da_dat_cat_lo": sorted(journal_open - set(no_stop_in_journal)),
    }
    ctx = {
        "trang_hien_tai": page,
        "van_de_du_lieu_can_xem": [f"{h['title']}: {h['detail']}" for h in (health or [])],
        "bay_gio": now.strftime("%Y-%m-%d %H:%M") + " (giờ Việt Nam)",
        "du_lieu_gia_den_ngay": _d(last_data_date),
        "cai_dat": {"von_cai_dat": _r(settings.get("capital_m", 0) * 1e6), "chap_nhan_mat_moi_lenh_pct": settings.get("risk_pct"),
                    "ty_trong_toi_da_mot_ma_pct": settings.get("max_alloc"), "ma_theo_doi": list(settings.get("watch", []))},
        "so_lieu_da_tinh_san": precomputed,
        "danh_muc": {"tong_tai_san_theo_von_nguoi_dung_dat": _r(val_summary.get("base", val_summary.get("total"))),
                     "chi_tiet_tong_tai_san": "Người dùng chỉ đầu tư MỘT PHẦN tổng tài sản. Mọi tỷ trọng tính trên tổng tài sản này; phần chưa ghi trong Danh mục coi là tiền chưa đầu tư.",
                     "da_ghi_trong_danh_muc": _r(val_summary.get("total")), "tien_chua_dau_tu_chua_ghi": _r(val_summary.get("assumed_cash", 0)),
                     "gia_tri_co_phieu": _r(val_summary.get("stock_value")), "tien_mat_da_ghi": _r(pf_cash),
                     "lai_lo_cua_phan_co_phieu_so_voi_gia_von_pct": _r(val_summary["pnl_pct"] * 100, 1) if val_summary.get("pnl_pct") is not None else None,
                     "dang_giu": held, "canh_bao": list(val_summary.get("warnings", []))},
        "rui_ro": ({"mat_neu_cham_cat_lo": _r(risk_summary.get("loss_to_stop")), "ma_chua_dat_cat_lo": risk_summary.get("n_unprotected"),
                    "ma_da_cham_cat_lo": risk_summary.get("n_hit"), "tien_mat_pct": _r(risk_summary.get("cash_pct", 0) * 100, 1)} if risk_summary else None),
        "lenh_dang_giu_trong_nhat_ky": open_t,
        "lenh_da_ban_gan_day": closed_t[:MAX_CLOSED],
        "canh_bao_gia_hien_tai": [a["message"] for a in alert_items],
        "tien_nap_rut": {"tom_tat": ({"tien_rong_da_bo_vao": _r(cf_summary.get("net_in")), "lai_lo_that": _r(cf_summary.get("pnl")),
                                      "lai_lo_that_pct": _r(cf_summary["pnl_pct"] * 100, 1) if cf_summary.get("pnl_pct") is not None else None,
                                      "ty_suat_quy_nam_pct": _r(cf_summary["annual"] * 100, 1) if cf_summary.get("annual") is not None else None}
                                     if cf_summary.get("n") else None),
                         "gan_day": [{"ngay": _d(r.day), "so_tien": _r(r.amount), "ghi_chu": _text(getattr(r, "note", ""), 100)}
                                     for r in (flows.tail(MAX_FLOWS).itertuples() if len(flows) else [])]},
        "so_voi_vn_index": ({"tai_san_cua_ban": _r(bench["your_value"]), "neu_bo_vao_vn_index": _r(bench["index_value"]), "chenh_lech": _r(bench["diff"]),
                             "ban_dang_hon_chi_so": bool(bench["ahead"]), "tu_ngay": _d(bench["first_day"])} if bench and bench.get("ok") else None),
        "co_tuc": {"tong_tien_mat_da_nhan": _r(div_summary.get("cash_total")), "12_thang": _r(div_summary.get("cash_12m")),
                   "gan_day": [{"ngay": _d(r.day), "ma": r.symbol, "loai": "tiền mặt" if r.kind == "tien" else "cổ phiếu thưởng", "so": _r(r.amount)}
                               for r in (divs.head(MAX_DIVS).itertuples() if len(divs) else [])]},
        "gia_thi_truong": [{"ma": s["symbol"], "gia": _r(s["close"]), "doi_hom_nay_pct": _r(s["change"] * 100, 2), "diem_ky_thuat_0_100": _r(s["score"]) if s["score"] is not None else None,
                            "rsi": _r(s["rsi"]) if s.get("rsi") is not None else None, "ngay_du_lieu": _d(s["last_date"]), "tam_thoi": bool(s.get("partial"))} for s in snaps],
        "tin_tuc_nhac_dich_danh_ma": {sym: [{"nguon": n["source"], "tieu_de": n["title"]} for n in items[:4]] for sym, items in news.items() if items},
    }
    return trim(ctx)


def trim(ctx: Dict) -> Dict:
    """Giữ bản tóm tắt dưới MAX_CHARS: bỏ dần lệnh đã bán cũ nhất, rồi tin tức, rồi tiền nạp/rút cũ."""
    for key, path in (("lenh_da_ban_gan_day", None), ("tin_tuc_nhac_dich_danh_ma", None)):
        while len(json.dumps(ctx, ensure_ascii=False)) > MAX_CHARS:
            v = ctx.get(key)
            if isinstance(v, list) and v:
                v.pop()
            elif isinstance(v, dict) and v:
                v.pop(next(iter(v)))
            else:
                break
    while len(json.dumps(ctx, ensure_ascii=False)) > MAX_CHARS and ctx["tien_nap_rut"]["gan_day"]:
        ctx["tien_nap_rut"]["gan_day"].pop(0)
    return ctx
