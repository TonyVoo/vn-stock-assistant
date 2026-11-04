"""Sổ giả lập (paper trading) cho tín hiệu xếp hạng: ghi danh mục đầu kỳ, rồi đo kết quả khi kỳ kết thúc.

Không có tiền thật. Mục đích: kiểm chứng tín hiệu trên dữ liệu MỚI mà backtest chưa từng thấy.
Phí tính đầy đủ một vòng mua-bán mỗi kỳ (thận trọng, không giả định giữ lại mã từ kỳ trước).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .risk import FEE_RATE, SELL_TAX

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "paper.db"
ROUND_TRIP = 2 * FEE_RATE + SELL_TAX

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    asof TEXT NOT NULL,
    signal TEXT NOT NULL,
    picks TEXT NOT NULL,
    h INTEGER NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (asof, signal)
)
"""


def _conn(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.execute(SCHEMA)
    return c


def save_snapshot(asof: str, signal: str, picks, h: int, path: Optional[Path] = None) -> bool:
    """Trả về False nếu đã có bản ghi cho (asof, signal)."""
    with _conn(path) as c:
        cur = c.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?)",
                        (asof, signal, ",".join(picks), int(h), pd.Timestamp.now().isoformat(timespec="seconds")))
        return cur.rowcount == 1


def list_snapshots(path: Optional[Path] = None) -> pd.DataFrame:
    with _conn(path) as c:
        return pd.read_sql_query("SELECT * FROM snapshots ORDER BY asof DESC, signal", c)


def evaluate(snaps: pd.DataFrame, panel: Dict[str, pd.DataFrame], min_value: float = 5e9) -> pd.DataFrame:
    """Kết quả từng bản ghi: mua ở giá mở cửa phiên SAU ngày asof, bán ở giá mở cửa h phiên sau đó."""
    o, val = panel["open"], panel["value"]
    idx = o.index
    rows = []
    for _, s in snaps.iterrows():
        asof = pd.Timestamp(s["asof"])
        picks = s["picks"].split(",")
        pos = idx.searchsorted(asof, side="right")  # phiên đầu tiên SAU asof
        row = {"asof": s["asof"], "signal": s["signal"], "picks": s["picks"], "h": s["h"],
               "status": "chờ phiên kế tiếp", "gross": np.nan, "bench": np.nan, "net_excess": np.nan}
        if pos < len(idx):
            end = pos + int(s["h"])
            final = end < len(idx)
            exit_px = o.iloc[end] if final else panel["close"].iloc[-1]
            r = (exit_px / o.iloc[pos] - 1)
            at = idx.searchsorted(asof, side="right") - 1
            elig = val.iloc[at][val.iloc[at] >= min_value].index
            gross, bench = float(r.reindex(picks).mean()), float(r.reindex(elig).mean())
            row.update(status="đã xong" if final else "đang giữ (tạm tính theo giá đóng cửa)",
                       gross=gross, bench=bench, net_excess=gross - ROUND_TRIP - bench)
        rows.append(row)
    return pd.DataFrame(rows)
