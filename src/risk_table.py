"""Bảng rủi ro danh mục: nếu giá giảm, bạn có thể mất bao nhiêu?

Dữ liệu vào: định giá danh mục (từ portfolio.valuate) + các lệnh ĐANG GIỮ trong Nhật ký (có mức cắt lỗ).
Quy ước: mức cắt lỗ của một mã = trung bình gia quyền (theo số lượng) các mức cắt lỗ đã đặt của các lệnh đang giữ mã đó.
Phần số lượng trong Danh mục KHÔNG có lệnh nào đặt cắt lỗ phủ tới được coi là "chưa có cắt lỗ" (rủi ro không giới hạn trong bảng này).
"Mất nếu chạm cắt lỗ" tính TỪ GIÁ HIỆN TẠI xuống mức cắt lỗ, tức là phần tài sản bạn còn có thể mất thêm, không phải lỗ so với giá vốn.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

SCENARIOS = (5, 10, 20, 30)  # % cổ phiếu giảm thêm


def _stop_info(symbol: str, qty: float, open_trades: Optional[pd.DataFrame]) -> Tuple[Optional[float], float]:
    """(mức cắt lỗ trung bình gia quyền, số lượng được phủ bởi lệnh có cắt lỗ). Không có thì (None, 0)."""
    if open_trades is None or open_trades.empty:
        return None, 0.0
    lots = open_trades[(open_trades["symbol"] == symbol) & (open_trades["stop"] > 0)]
    if lots.empty:
        return None, 0.0
    total_q = float(lots["qty"].sum())
    stop = float((lots["qty"] * lots["stop"]).sum() / total_q)
    return stop, min(float(qty), total_q)


def build(valuation: pd.DataFrame, open_trades: Optional[pd.DataFrame], cash: float, risk_pct: float = 2.0) -> Tuple[pd.DataFrame, Dict]:
    """risk_pct: mức % tài sản bạn chấp nhận mất cho MỖI mã (cài đặt “Chấp nhận mất tối đa”)."""
    stock_value = float(valuation["value"].sum()) if len(valuation) else 0.0
    total = stock_value + float(cash)
    rows = []
    for r in valuation.itertuples():
        price = float(r.price) if r.price else 0.0
        stop, covered = _stop_info(r.symbol, r.qty, open_trades)
        uncovered = float(r.qty) - covered
        hit = bool(stop and price and price <= stop)
        loss = 0.0 if (stop is None or hit or not price) else covered * (price - stop)
        pct_assets = loss / total if total else 0.0
        if stop is None:
            status, level = "Chưa đặt cắt lỗ", "bad"
        elif hit:
            status, level = "Đã chạm cắt lỗ", "bad"
        elif uncovered > 0:
            status, level = f"{int(uncovered)} cp chưa có cắt lỗ", "warn"
        elif pct_assets * 100 > risk_pct:
            status, level = f"Vượt mức bạn chấp nhận ({pct_assets * 100:.1f}% > {risk_pct:.1f}%)", "warn"
        else:
            status, level = "Trong mức chấp nhận", "ok"
        rows.append({"symbol": r.symbol, "qty": float(r.qty), "price": price, "value": float(r.value), "weight": float(r.weight),
                     "stop": stop, "covered": covered, "uncovered": uncovered,
                     "dist_pct": ((price - stop) / price) if (stop and price) else None,
                     "loss": loss, "pct_assets": pct_assets, "hit": hit, "status": status, "level": level,
                     "unprotected_value": uncovered * price if price else 0.0})
    df = pd.DataFrame(rows, columns=["symbol", "qty", "price", "value", "weight", "stop", "covered", "uncovered", "dist_pct", "loss",
                                     "pct_assets", "hit", "status", "level", "unprotected_value"])
    total_loss = float(df["loss"].sum()) if len(df) else 0.0
    unprot = float(df["unprotected_value"].sum()) if len(df) else 0.0
    summary = {
        "total": total, "stock_value": stock_value, "cash": float(cash),
        "loss_to_stop": total_loss, "loss_to_stop_pct": (total_loss / total) if total else 0.0,
        "unprotected_value": unprot, "unprotected_share": (unprot / stock_value) if stock_value else 0.0,
        "n_hit": int(df["hit"].sum()) if len(df) else 0,
        "n_over": int(df["status"].str.startswith("Vượt").sum()) if len(df) else 0,
        "n_unprotected": int((df["stop"].isna()).sum()) if len(df) else 0,
        "cash_pct": (float(cash) / total) if total else 0.0,
        "scenarios": [{"drop": d, "loss": stock_value * d / 100, "pct_assets": (stock_value * d / 100 / total) if total else 0.0}
                      for d in SCENARIOS],
    }
    summary["verdict"] = verdict(summary)
    return df, summary


def verdict(s: Dict) -> Tuple[str, str, str]:
    """(nhãn, mức, giải thích) — quy tắc kinh nghiệm để người mới có hình dung, KHÔNG phải ngưỡng chuẩn."""
    if s["stock_value"] <= 0:
        return "Chưa có cổ phiếu", "muted", "Danh mục chưa có cổ phiếu nên chưa có rủi ro giá."
    if s["unprotected_share"] > 0.5:
        return "Rủi ro cao", "bad", "Hơn một nửa giá trị cổ phiếu chưa có mức cắt lỗ, nên không biết có thể mất tối đa bao nhiêu."
    if s["loss_to_stop_pct"] > 0.10 or s["n_hit"]:
        return "Rủi ro cao", "bad", ("Có mã đã chạm mức cắt lỗ. Hãy xem lại kế hoạch." if s["n_hit"]
                                     else "Nếu các mã chạm cắt lỗ, bạn mất hơn 10% tài sản.")
    if s["unprotected_share"] > 0 or s["loss_to_stop_pct"] > 0.05 or s["n_over"]:
        return "Cần chú ý", "warn", "Còn mã chưa phủ hết cắt lỗ, hoặc mức mất tiềm năng vượt 5% tài sản, hoặc có mã vượt mức bạn chấp nhận."
    return "Trong tầm kiểm soát", "ok", "Mọi mã đều có cắt lỗ và mức mất tiềm năng nhỏ so với tài sản."
