"""Thu thập tin tức (RSS) và số liệu thị trường thế giới."""
from __future__ import annotations

from typing import Dict, List

import feedparser

RSS_FEEDS = {
    "CafeF": "https://cafef.vn/thi-truong-chung-khoan.rss",
    "VnExpress": "https://vnexpress.net/rss/kinh-doanh.rss",
    "Vietstock": "https://vietstock.vn/830/chung-khoan/co-phieu.rss",
}

GLOBAL_TICKERS = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Chỉ số USD (DXY)": "DX-Y.NYB",
    "Dầu WTI": "CL=F",
    "Vàng": "GC=F",
    "Lợi suất TP Mỹ 10Y": "^TNX",
    "USD/VND": "VND=X",
}


def fetch_news(limit_per_feed: int = 15) -> List[Dict]:
    items: List[Dict] = []
    for name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:limit_per_feed]:
                items.append({
                    "source": name,
                    "title": e.get("title", "").strip(),
                    "summary": (e.get("summary", "") or "")[:300],
                    "link": e.get("link", ""),
                    "published": e.get("published", ""),
                })
        except Exception:
            continue
    return items


def filter_news(items: List[Dict], symbols: List[str]) -> List[Dict]:
    """Giữ tin nhắc tới mã đang theo dõi hoặc từ khoá vĩ mô quan trọng."""
    keys = [s.upper() for s in symbols]
    macro = ["lãi suất", "fed", "tỷ giá", "vn-index", "vnindex", "margin", "trái phiếu",
             "gdp", "lạm phát", "cpi", "khối ngoại", "nâng hạng", "thuế quan", "dầu"]
    out = []
    for it in items:
        text = (it["title"] + " " + it["summary"]).lower()
        if any(k.lower() in text.split() or f" {k.lower()} " in f" {text} " for k in keys) \
                or any(m in text for m in macro):
            out.append(it)
    return out


def fetch_global_snapshot() -> List[Dict]:
    """Biến động 1 phiên của các chỉ số/hàng hoá thế giới ảnh hưởng thị trường VN."""
    rows: List[Dict] = []
    try:
        import yfinance as yf
    except Exception:
        return rows
    for name, tk in GLOBAL_TICKERS.items():
        try:
            h = yf.Ticker(tk).history(period="5d")["Close"].dropna()
            if len(h) >= 2:
                rows.append({"name": name, "last": float(h.iloc[-1]),
                             "change_pct": float((h.iloc[-1] / h.iloc[-2] - 1) * 100)})
        except Exception:
            continue
    return rows
