"""Tín hiệu xếp hạng giữa các mã (cross-sectional), kiểm tra bằng dữ liệu giá thật.

Mỗi kỳ (h phiên): cuối phiên t xếp hạng các mã đủ thanh khoản theo tín hiệu, mua `n_top` mã đứng đầu (tỷ trọng đều)
ở GIÁ MỞ CỬA phiên t+1, giữ đến giá mở cửa phiên t+1+h. Đường cơ sở: tỷ trọng đều toàn bộ mã đủ thanh khoản.

Chống tự lừa mình:
- Danh sách giả thuyết (SIGNALS) cố định trước khi chạy, không chỉnh tham số theo kết quả.
- Phí/thuế tính theo mức thay đổi danh mục. Đường cơ sở KHÔNG bị tính phí (bất lợi cho chiến lược, thận trọng).
- Phép thử hoán vị: so với việc chọn n_top mã NGẪU NHIÊN ở cùng các kỳ -> p-value cho "kỹ năng chọn mã" (trước phí).
- Train/test: kỳ chỉ thuộc train nếu thoát trước ngày cắt, thuộc test nếu vào từ ngày cắt.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from .risk import FEE_RATE, SELL_TAX

SIGNALS: Dict[str, Dict] = {
    "mom_6_1":     {"fn": lambda c: c.shift(21) / c.shift(126) - 1, "h": 21,
                    "desc": "Động lượng 6 tháng (bỏ tháng gần nhất)"},
    "mom_12_1":    {"fn": lambda c: c.shift(21) / c.shift(252) - 1, "h": 21,
                    "desc": "Động lượng 12 tháng (bỏ tháng gần nhất)"},
    "reversal_1w": {"fn": lambda c: -(c / c.shift(5) - 1), "h": 5,
                    "desc": "Đảo chiều ngắn hạn: mua mã giảm mạnh nhất tuần qua"},
    "low_vol":     {"fn": lambda c: -c.pct_change().rolling(60).std(), "h": 21,
                    "desc": "Biến động thấp (độ lệch chuẩn 60 phiên nhỏ nhất)"},
    "high_52w":    {"fn": lambda c: c / c.rolling(252).max(), "h": 21,
                    "desc": "Gần đỉnh 52 tuần nhất"},
}


def build_panel(prices: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    dates = sorted(set().union(*[set(d["date"]) for d in prices.values()]))
    idx = pd.DatetimeIndex(dates)

    def piv(col):
        return pd.DataFrame({s: d.set_index("date")[col].reindex(idx) for s, d in prices.items()})

    close, opn, vol = piv("close"), piv("open"), piv("volume")
    close, opn = close.ffill(limit=3), opn.ffill(limit=3)
    return {"close": close, "open": opn, "value": (close * vol).rolling(20).mean()}


def run_signal(panel: Dict[str, pd.DataFrame], score: pd.DataFrame, h: int, n_top: int = 5,
               min_value: float = 5e9, max_price: Optional[float] = None) -> Dict:
    """max_price: chỉ xét mã có giá đóng cửa <= max_price TẠI THỜI ĐIỂM đó (mô phỏng giới hạn vốn nhỏ, mua đủ lô)."""
    o, val = panel["open"], panel["value"]
    n = len(o)
    rows, prev_w = [], pd.Series(dtype=float)
    t = 0
    while t < n - h - 2:
        s = score.iloc[t].dropna()
        s = s[val.iloc[t].reindex(s.index) >= min_value]
        if max_price is not None:
            s = s[panel["close"].iloc[t].reindex(s.index) <= max_price]
        if len(s) < 2 * n_top or t < 260:
            t += 1
            continue
        entry, exit_ = t + 1, t + 1 + h
        r = (o.iloc[exit_] / o.iloc[entry] - 1).reindex(s.index)
        if r.isna().any():
            r = r.dropna()
            s = s.reindex(r.index)
            if len(s) < 2 * n_top:
                t += h
                continue
        picks = s.nlargest(n_top).index
        w = pd.Series(1.0 / n_top, index=picks)
        union = w.index.union(prev_w.index)
        wn, wo = w.reindex(union).fillna(0), prev_w.reindex(union).fillna(0)
        buys, sells = (wn - wo).clip(lower=0).sum(), (wo - wn).clip(lower=0).sum()
        cost = buys * FEE_RATE + sells * (FEE_RATE + SELL_TAX)
        rows.append({"entry": o.index[entry], "exit": o.index[exit_],
                     "gross": float(r[picks].mean()), "bench": float(r.mean()), "cost": float(cost),
                     "elig_ret": r.to_numpy(), "picks": list(picks)})
        prev_w = w
        t += h
    return {"rows": rows, "h": h, "n_top": n_top}


def _slice(rows: List[Dict], split: Optional[pd.Timestamp], part: str) -> List[Dict]:
    if split is None or part == "all":
        return rows
    if part == "train":
        return [r for r in rows if r["exit"] < split]
    return [r for r in rows if r["entry"] >= split]


def placebo_p(rows: List[Dict], n_top: int, sims: int = 2000, seed: int = 0) -> float:
    """P(chọn ngẫu nhiên cho excess TRƯỚC PHÍ >= excess thực tế)."""
    if not rows:
        return float("nan")
    rng = np.random.default_rng(seed)
    actual = np.mean([r["gross"] - r["bench"] for r in rows])
    tot = np.zeros(sims)
    for r in rows:
        er = r["elig_ret"]
        pick_idx = np.argpartition(rng.random((sims, len(er))), n_top, axis=1)[:, :n_top]
        tot += er[pick_idx].mean(axis=1) - r["bench"]
    sim = tot / len(rows)
    return float((sim >= actual).mean())


def stats(rows: List[Dict], h: int, n_top: int) -> Dict:
    if len(rows) < 3:
        return {"periods": len(rows)}
    gross = np.array([r["gross"] for r in rows])
    bench = np.array([r["bench"] for r in rows])
    cost = np.array([r["cost"] for r in rows])
    net_ex = gross - cost - bench
    se = net_ex.std(ddof=1) / np.sqrt(len(net_ex))
    return {
        "periods": len(rows),
        "ann_net_excess": float(net_ex.mean() * 252 / h),
        "gross_excess_per_period": float((gross - bench).mean()),
        "net_excess_per_period": float(net_ex.mean()),
        "t_net": float(net_ex.mean() / se) if se > 0 else float("nan"),
        "hit_rate": float((net_ex > 0).mean()),
        "avg_cost": float(cost.mean()),
        "placebo_p": placebo_p(rows, n_top),
    }


def evaluate_all(prices: Dict[str, pd.DataFrame], split_date="2025-01-01", n_top: int = 5,
                 signals: Optional[Dict[str, Dict]] = None, max_price: Optional[float] = None) -> pd.DataFrame:
    panel = build_panel(prices)
    split = pd.Timestamp(split_date)
    out = []
    for name, spec in (signals or SIGNALS).items():
        res = run_signal(panel, spec["fn"](panel["close"]), spec["h"], n_top, max_price=max_price)
        for part in ("train", "test", "all"):
            st = stats(_slice(res["rows"], split, part), spec["h"], n_top)
            out.append({"signal": name, "part": part, "h": spec["h"], **st})
    return pd.DataFrame(out)


def rank_now(panel: Dict[str, pd.DataFrame], name: str, n_top: int = 5, min_value: float = 5e9) -> pd.DataFrame:
    """Xếp hạng các mã đủ thanh khoản theo tín hiệu `name` tại phiên cuối của dữ liệu."""
    score = SIGNALS[name]["fn"](panel["close"]).iloc[-1].dropna()
    val = panel["value"].iloc[-1].reindex(score.index)
    score = score[val >= min_value].sort_values(ascending=False)
    out = pd.DataFrame({"symbol": score.index, "score": score.values})
    out["rank"] = np.arange(1, len(out) + 1)
    out["close"] = panel["close"].iloc[-1].reindex(out["symbol"]).to_numpy()
    out["top"] = out["rank"] <= n_top
    return out.reset_index(drop=True)
