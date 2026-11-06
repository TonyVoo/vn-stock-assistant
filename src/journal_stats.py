"""Phân tích Nhật ký: thẻ lỗi, thời gian giữ, có/không cắt lỗ, và nhận xét tự động (chỉ khi đủ số lệnh).

Nguyên tắc trung thực với dữ liệu ít: luôn kèm số lệnh (n); cảnh báo khi dưới 20 lệnh; nhận xét chỉ được đưa ra khi mỗi nhóm so sánh có >= 3 lệnh;
mọi nhận xét chỉ MÔ TẢ số liệu của bạn, không chứng minh nguyên nhân.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from . import journal

MISTAKE_TAGS = ["Mua vì tin đồn", "Mua đuổi giá (FOMO)", "Không đặt cắt lỗ", "Không tuân thủ cắt lỗ", "Bán quá sớm",
                "Giữ lỗ quá lâu", "Dồn quá nhiều vào một mã", "Mua khi chưa có lý do rõ ràng"]
GOOD_TAGS = ["Đúng kế hoạch", "Cắt lỗ đúng hạn", "Chốt lời đúng mục tiêu", "Mua theo xu hướng"]
ALL_TAGS = MISTAKE_TAGS + GOOD_TAGS
TAG_NO_STOP = "Không đặt cắt lỗ"       # tự nhận khi lệnh chưa có mức cắt lỗ
TAG_NO_REASON = "Chưa ghi lý do mua"   # tự nhận khi lệnh chưa có lý do
MIN_TRADES_RELIABLE = 20
MIN_GROUP = 3
HOLD_BINS = [(0, 7, "Tối đa 7 ngày"), (8, 30, "8 đến 30 ngày"), (31, 90, "31 đến 90 ngày"), (91, 10_000, "Trên 90 ngày")]


def _date(s):
    try:
        return pd.Timestamp(str(s)).normalize() if str(s) not in ("", "None", "nan", "Không rõ") else pd.NaT
    except (ValueError, TypeError):
        return pd.NaT


def enrich(trades: pd.DataFrame) -> pd.DataFrame:
    """Chỉ giữ lệnh ĐÃ BÁN và thêm: số ngày giữ, tỷ suất lãi/lỗ (sau phí, thuế), thắng/thua, danh sách thẻ (tự ghi + tự nhận)."""
    cols = ["id", "symbol", "days", "ret", "pnl", "win", "tag_list", "has_stop"]
    if trades is None or trades.empty:
        return pd.DataFrame(columns=cols)
    d = trades[trades["exit_price"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    opened, closed = d["opened"].map(_date), d["closed"].map(_date)
    d["days"] = (closed - opened).dt.days
    d.loc[d["days"] < 0, "days"] = np.nan
    d["ret"] = d["pnl"] / (d["entry"] * d["qty"])
    d["win"] = d["pnl"] > 0
    d["has_stop"] = d["stop"] > 0
    tags_col = d["tags"] if "tags" in d.columns else pd.Series([""] * len(d), index=d.index)

    def build(row_tags, has_stop, reason):
        tags = journal.split_tags(row_tags)
        r = str(reason or "")
        r = r.split("]", 1)[1].strip() if r.startswith("[sao kê") and "]" in r else r.strip()
        if not has_stop and TAG_NO_STOP not in tags:
            tags.append(TAG_NO_STOP)
        if (not r or r.startswith(journal.PLACEHOLDER_REASON)) and TAG_NO_REASON not in tags:
            tags.append(TAG_NO_REASON)
        return tags

    d["tag_list"] = [build(t, h, r) for t, h, r in zip(tags_col, d["has_stop"], d["reason"])]
    return d[cols].reset_index(drop=True)


def _group(df: pd.DataFrame, label: str) -> Dict:
    return {label: None, "n": int(len(df)), "win_rate": float(df["win"].mean()) if len(df) else np.nan,
            "avg_ret": float(df["ret"].mean()) if len(df) else np.nan, "total_pnl": float(df["pnl"].sum()) if len(df) else 0.0,
            "small": len(df) < 5}


def summary(d: pd.DataFrame) -> Dict:
    if d.empty:
        return {"n": 0}
    wins, losses = d[d["win"]], d[~d["win"]]
    avg_win, avg_loss = (float(wins["ret"].mean()) if len(wins) else np.nan), (float(losses["ret"].mean()) if len(losses) else np.nan)
    return {"n": int(len(d)), "win_rate": float(d["win"].mean()), "avg_ret": float(d["ret"].mean()),
            "avg_win": avg_win, "avg_loss": avg_loss,
            "payoff": (avg_win / abs(avg_loss)) if len(wins) and len(losses) and avg_loss else np.nan,
            "avg_days": float(d["days"].mean()) if d["days"].notna().any() else np.nan, "total_pnl": float(d["pnl"].sum()),
            "reliable": len(d) >= MIN_TRADES_RELIABLE}


def by_tag(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tag in sorted({t for tl in d["tag_list"] for t in tl}):
        g = d[d["tag_list"].map(lambda tl, t=tag: t in tl)]
        row = _group(g, "tag")
        row["tag"] = tag
        row["good"] = tag in GOOD_TAGS
        rows.append(row)
    df = pd.DataFrame(rows, columns=["tag", "n", "win_rate", "avg_ret", "total_pnl", "small", "good"])
    return df.sort_values("total_pnl").reset_index(drop=True) if len(df) else df


def by_holding(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lo, hi, label in HOLD_BINS:
        g = d[d["days"].between(lo, hi)]
        if len(g):
            row = _group(g, "bucket")
            row["bucket"] = label
            rows.append(row)
    return pd.DataFrame(rows, columns=["bucket", "n", "win_rate", "avg_ret", "total_pnl", "small"])


def by_stop(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for flag, label in ((True, "Có đặt cắt lỗ"), (False, "Chưa đặt cắt lỗ")):
        g = d[d["has_stop"] == flag]
        if len(g):
            row = _group(g, "group")
            row["group"] = label
            rows.append(row)
    return pd.DataFrame(rows, columns=["group", "n", "win_rate", "avg_ret", "total_pnl", "small"])


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%".replace(".", ",")


def insights(d: pd.DataFrame) -> List[str]:
    """Nhận xét từ số liệu của bạn. Chỉ nêu khi mỗi nhóm so sánh có đủ lệnh; không kết luận nguyên nhân."""
    out: List[str] = []
    if d.empty:
        return out
    gaps = []
    for tag in {t for tl in d["tag_list"] for t in tl}:
        has = d["tag_list"].map(lambda tl, t=tag: t in tl)
        a, b = d[has], d[~has]
        if len(a) >= MIN_GROUP and len(b) >= MIN_GROUP and tag not in GOOD_TAGS:
            gaps.append((a["ret"].mean() - b["ret"].mean(), tag, len(a), a["ret"].mean(), len(b), b["ret"].mean()))
    for gap, tag, na, ma, nb, mb in sorted(gaps)[:3]:
        if gap < -0.02:
            out.append(f"Các lệnh gắn “{tag}” ({na} lệnh) có kết quả trung bình {_pct(ma)}, kém hơn các lệnh khác ({nb} lệnh, {_pct(mb)}).")
    win_d, lose_d = d[d["win"] & d["days"].notna()], d[~d["win"] & d["days"].notna()]
    if len(win_d) >= MIN_GROUP and len(lose_d) >= MIN_GROUP and lose_d["days"].mean() > 1.5 * win_d["days"].mean():
        out.append(f"Bạn giữ lệnh lỗ lâu hơn lệnh lãi: trung bình {lose_d['days'].mean():.0f} ngày so với {win_d['days'].mean():.0f} ngày. "
                   "Đây là dấu hiệu thường gặp của việc “giữ lỗ chờ hồi”.")
    hold = by_holding(d)
    worst = hold[hold["n"] >= MIN_GROUP].sort_values("avg_ret").head(1)
    if len(hold[hold["n"] >= MIN_GROUP]) >= 2 and len(worst) and worst.iloc[0]["avg_ret"] < 0:
        w = worst.iloc[0]
        out.append(f"Nhóm thời gian giữ yếu nhất là “{w['bucket']}”: {int(w['n'])} lệnh, trung bình {_pct(w['avg_ret'])}.")
    if len(d) < MIN_TRADES_RELIABLE:
        out.append(f"Mới có {len(d)} lệnh đã bán nên các nhận xét trên chỉ mang tính tham khảo (cần khoảng {MIN_TRADES_RELIABLE} lệnh trở lên).")
    elif not out:
        out.append("Chưa thấy nhóm nào lệch rõ rệt so với phần còn lại. Cứ tiếp tục ghi thẻ cho từng lệnh.")
    return out
