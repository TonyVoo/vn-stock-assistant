"""Backtest điểm số kỹ thuật, đi theo từng phiên, không nhìn trước tương lai.

Quy tắc mô phỏng (đều nằm trong tham số):
- Cuối phiên t: tính điểm chỉ bằng dữ liệu đến hết phiên t. Nếu điểm >= ngưỡng và đủ thanh khoản -> báo hiệu mua.
- Tuỳ chọn `regime`: chỉ mua khi VN-Index đang trên MA50/MA200 của chính nó.
- Mua ở GIÁ MỞ CỬA phiên t+1 (không mua được ở giá đóng cửa của phiên đã có tín hiệu).
- Cắt lỗ = giá đóng cửa phiên t - atr_mult × ATR. Không bán được trong min_hold phiên đầu (T+2).
- Tuỳ chọn `trail`: cuối mỗi phiên, kéo cắt lỗ lên theo (giá đóng cửa - atr_mult × ATR), không bao giờ hạ xuống.
- Thoát: mở cửa thấp hơn cắt lỗ -> bán ở giá mở cửa (gap); giá thấp nhất chạm cắt lỗ -> bán ở cắt lỗ;
  giữ đủ hold_days phiên -> bán ở giá đóng cửa.
- Phí môi giới + thuế bán được trừ vào mọi lệnh. Một vị thế mỗi mã tại một thời điểm.

Kiểm tra train/test (`split_evaluation`): chọn tham số bằng dữ liệu TRƯỚC ngày cắt, rồi chỉ nhìn kết quả SAU ngày cắt.
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .risk import FEE_RATE, SELL_TAX
from .signals import add_indicators, score_indicators

TRADE_COLS = ["symbol", "entry_date", "exit_date", "entry", "exit", "stop", "days",
              "ret", "r_multiple", "reason", "score"]

DEFAULT_GRID = {
    "threshold": [60, 70, 80],
    "hold_days": [10, 20, 40],
    "atr_mult": [1.5, 2.0, 3.0],
    "regime": [None, 200],
    "trail": [False, True],
}
_EXIT_KEYS = ("hold_days", "atr_mult", "trail", "min_hold")


def _align_index(index_df: Optional[pd.DataFrame], dates: pd.Series) -> Optional[pd.DataFrame]:
    if index_df is None or index_df.empty:
        return None
    s = index_df.set_index("date")["close"]
    s = s[~s.index.duplicated()]
    aligned = s.reindex(pd.DatetimeIndex(dates)).ffill()
    return pd.DataFrame({"close": aligned.values})


def prepare(symbol: str, df: pd.DataFrame, index_df: Optional[pd.DataFrame] = None,
            warmup: int = 200) -> Dict:
    """Tính điểm từng phiên MỘT lần (chỉ dùng dữ liệu quá khứ của mỗi phiên). Dùng lại cho nhiều tham số."""
    d = add_indicators(df).reset_index(drop=True)
    idx = _align_index(index_df, d["date"])
    n = len(d)
    start = max(warmup, 60)
    score = np.full(n, np.nan)
    liquid = np.zeros(n, dtype=bool)
    for i in range(start, n - 1):
        sig = score_indicators(d.iloc[: i + 1], None if idx is None else idx.iloc[: i + 1])
        if sig["score"] is not None:
            score[i] = sig["score"]
            liquid[i] = sig["liquid"]
    regime = {}
    if idx is not None:
        ic = idx["close"]
        for m in (50, 200):
            regime[m] = (ic > ic.rolling(m).mean()).to_numpy()
    return {"symbol": symbol, "start": start, "n": n, "score": score, "liquid": liquid,
            "regime": regime, "date": d["date"].to_numpy(),
            "o": d["open"].to_numpy(float), "h": d["high"].to_numpy(float),
            "l": d["low"].to_numpy(float), "c": d["close"].to_numpy(float),
            "atr": d["atr14"].to_numpy(float)}


def simulate(p: Dict, threshold: float = 70, hold_days: int = 20, atr_mult: float = 2.0,
             min_hold: int = 2, require_liquid: bool = True, regime: Optional[int] = None,
             trail: bool = False) -> pd.DataFrame:
    o, l, c, atr, score, liquid = p["o"], p["l"], p["c"], p["atr"], p["score"], p["liquid"]
    reg = p["regime"].get(regime) if regime else None
    n = p["n"]
    rows = []
    i = p["start"]
    while i < n - 1:
        s = score[i]
        ok = (not np.isnan(s)) and s >= threshold and (liquid[i] or not require_liquid)
        if ok and regime:
            ok = reg is not None and bool(reg[i])
        if not ok:
            i += 1
            continue
        entry_i = i + 1
        entry = o[entry_i]
        stop = c[i] - atr_mult * atr[i]
        if not np.isfinite(stop) or entry <= stop:  # mở cửa đã thủng điểm cắt lỗ: bỏ qua
            i += 1
            continue
        init_stop = stop
        exit_i, exit_p, reason = None, None, None
        for j in range(entry_i + min_hold, n):
            if o[j] <= stop:
                exit_i, exit_p, reason = j, o[j], "cắt lỗ (gap)"
            elif l[j] <= stop:
                exit_i, exit_p, reason = j, stop, "cắt lỗ"
            elif j - entry_i >= hold_days:
                exit_i, exit_p, reason = j, c[j], "hết thời gian giữ"
            if exit_i is not None:
                break
            if trail:
                stop = max(stop, c[j] - atr_mult * atr[j])
        if exit_i is None:  # vị thế chưa đóng khi hết dữ liệu: không tính vào kết quả
            break
        ret = exit_p * (1 - FEE_RATE - SELL_TAX) / (entry * (1 + FEE_RATE)) - 1
        rows.append({"symbol": p["symbol"], "entry_date": pd.Timestamp(p["date"][entry_i]),
                     "exit_date": pd.Timestamp(p["date"][exit_i]), "entry": entry, "exit": exit_p,
                     "stop": init_stop, "days": exit_i - entry_i, "ret": ret,
                     "r_multiple": (exit_p - entry) / (entry - init_stop), "reason": reason,
                     "score": s})
        i = exit_i  # tín hiệu mới chỉ xét sau khi đã thoát lệnh
    return pd.DataFrame(rows, columns=TRADE_COLS)


def backtest_symbol(symbol: str, df: pd.DataFrame, index_df: Optional[pd.DataFrame] = None,
                    warmup: int = 200, **kw) -> pd.DataFrame:
    return simulate(prepare(symbol, df, index_df, warmup), **kw)


def run_prepared(prepared: List[Dict], **kw) -> pd.DataFrame:
    parts = [simulate(p, **kw) for p in prepared]
    parts = [x for x in parts if not x.empty]
    if not parts:
        return pd.DataFrame(columns=TRADE_COLS)
    return pd.concat(parts, ignore_index=True).sort_values("exit_date").reset_index(drop=True)


def prepare_all(prices: Dict[str, pd.DataFrame], index_df: Optional[pd.DataFrame] = None,
                warmup: int = 200) -> List[Dict]:
    return [prepare(s, df, index_df, warmup) for s, df in prices.items()]


def run_backtest(prices: Dict[str, pd.DataFrame], index_df: Optional[pd.DataFrame] = None,
                 warmup: int = 200, **kw) -> pd.DataFrame:
    return run_prepared(prepare_all(prices, index_df, warmup), **kw)


def summarize(trades: pd.DataFrame, alloc: float = 0.20) -> Dict:
    """Thống kê. Đường vốn là ƯỚC LƯỢNG: mỗi lệnh dùng `alloc` vốn, bỏ qua giới hạn số lệnh đồng thời."""
    if trades.empty:
        return {"trades": 0}
    r = trades["ret"]
    wins, losses = r[r > 0], r[r <= 0]
    equity = (1 + alloc * r).cumprod()
    dd = (equity / equity.cummax() - 1).min()
    return {
        "trades": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "avg_ret": float(r.mean()),
        "median_ret": float(r.median()),
        "avg_r": float(trades["r_multiple"].mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "avg_days": float(trades["days"].mean()),
        "total_ret_est": float(equity.iloc[-1] - 1),
        "max_drawdown_est": float(dd),
        "equity": equity.to_numpy(),
    }


def compare_with_baseline(prices: Dict[str, pd.DataFrame], index_df: Optional[pd.DataFrame] = None,
                          **kw) -> Tuple[pd.DataFrame, pd.DataFrame, Dict, Dict]:
    """So chiến lược với đường cơ sở: vào lệnh bất kỳ phiên nào theo cùng quy tắc thoát.

    Nếu lãi trung bình mỗi lệnh của chiến lược không cao hơn đường cơ sở thì điểm số CHƯA chứng minh có lợi thế.
    """
    prepared = prepare_all(prices, index_df)
    strat = run_prepared(prepared, **kw)
    base = run_prepared(prepared, **dict(kw, threshold=0, require_liquid=False, regime=None))
    return strat, base, summarize(strat), summarize(base)


# ---------------------------------------------------------------- train / test
def _split(trades: pd.DataFrame, split: pd.Timestamp) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Train: vào VÀ thoát trước ngày cắt (không rò thông tin sau ngày cắt). Test: vào từ ngày cắt trở đi."""
    train = trades[(trades["entry_date"] < split) & (trades["exit_date"] < split)]
    test = trades[trades["entry_date"] >= split]
    return train, test


def edge_stats(strat: pd.Series, base: pd.Series) -> Dict:
    """Chênh lệch lãi TB giữa chiến lược và đường cơ sở, kèm sai số và z (xấp xỉ).

    Các lệnh giữa các mã tương quan (cùng thị trường) nên sai số thật LỚN hơn con số này: z chỉ là ước lượng lạc quan.
    """
    if len(strat) < 2 or len(base) < 2:
        return {"edge": float("nan"), "se": float("nan"), "z": float("nan")}
    edge = float(strat.mean() - base.mean())
    se = float(np.sqrt(strat.var(ddof=1) / len(strat) + base.var(ddof=1) / len(base)))
    return {"edge": edge, "se": se, "z": edge / se if se > 0 else float("nan")}


def split_evaluation(prepared: List[Dict], split_date, grid: Optional[Dict] = None,
                     min_train_trades: int = 150) -> pd.DataFrame:
    """Thử mọi tổ hợp tham số: xếp hạng theo edge TRAIN, báo kèm kết quả TEST.

    Đường cơ sở dùng cùng quy tắc thoát nhưng vào lệnh không lọc (không ngưỡng điểm, không regime).
    """
    split = pd.Timestamp(split_date)
    grid = grid or DEFAULT_GRID
    keys = list(grid)
    base_cache: Dict[tuple, pd.DataFrame] = {}
    rows = []
    for combo in itertools.product(*grid.values()):
        cfg = dict(zip(keys, combo))
        exit_kw = {k: cfg[k] for k in _EXIT_KEYS if k in cfg}
        bk = tuple(sorted(exit_kw.items()))
        if bk not in base_cache:
            base_cache[bk] = run_prepared(prepared, threshold=0, require_liquid=False, regime=None, **exit_kw)
        strat = run_prepared(prepared, **cfg)
        tr_s, te_s = _split(strat, split)
        tr_b, te_b = _split(base_cache[bk], split)
        a, b = edge_stats(tr_s["ret"], tr_b["ret"]), edge_stats(te_s["ret"], te_b["ret"])
        rows.append({**cfg, "train_n": len(tr_s), "train_ret": tr_s["ret"].mean() if len(tr_s) else np.nan,
                     "train_edge": a["edge"], "train_z": a["z"],
                     "test_n": len(te_s), "test_ret": te_s["ret"].mean() if len(te_s) else np.nan,
                     "test_base_ret": te_b["ret"].mean() if len(te_b) else np.nan,
                     "test_edge": b["edge"], "test_z": b["z"]})
    out = pd.DataFrame(rows)
    out["eligible"] = out["train_n"] >= min_train_trades
    return out.sort_values(["eligible", "train_edge"], ascending=[False, False]).reset_index(drop=True)
