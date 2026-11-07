"""Market service: bọc lõi chứng khoán (src/) thành HTTP API cho backend Node của finwise.

Chỉ backend gọi service này (không để mobile gọi thẳng). Nếu đặt MARKET_API_KEY thì mọi
endpoint trừ /v1/health yêu cầu header `X-Api-Key` khớp. Không có endpoint nào trả lời khuyên
mua/bán: chỉ số liệu, điểm lọc và phép tính khối lượng.
"""
from __future__ import annotations

import math
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src import data, llm, news, risk, signals

load_dotenv()

DISCLAIMER = "Công cụ hỗ trợ ra quyết định, không phải lời khuyên đầu tư."
YEAR_SESSIONS = 250
SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,10}$")

app = FastAPI(title="VN market service", version="0.1.0")


def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("MARKET_API_KEY")
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid api key")


def clean_symbol(raw: str) -> str:
    symbol = raw.upper().strip()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="invalid symbol")
    return symbol


def finite(value: Any) -> Any:
    """JSON không có NaN/Inf: đổi thành None, đệ quy qua dict/list."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    return value


def load_prices(symbol: str, days: int) -> tuple[pd.DataFrame, str]:
    df, source = data.get_prices(symbol, days)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="no price data")
    # Giá giả lập chỉ dành cho chế độ thử (DEMO_MODE=1). Nếu không, một mã gõ nhầm sẽ nhận về
    # cả biểu đồ bịa ra: thà trả "không có dữ liệu" còn hơn đưa số không có thật.
    if source == "demo" and os.getenv("DEMO_MODE") != "1":
        raise HTTPException(status_code=404, detail="no price data")
    return df.sort_values("date").reset_index(drop=True), source


@app.get("/v1/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "demo_mode": os.getenv("DEMO_MODE") == "1"}


@app.get("/v1/quotes/{symbol}", dependencies=[Depends(require_key)])
def quote(symbol: str, days: int = Query(default=250, ge=2, le=2500)) -> Dict[str, Any]:
    symbol = clean_symbol(symbol)
    # Vùng 52 tuần luôn tính trên ~1 năm giá, dù người gọi chỉ xin vài phiên để vẽ.
    full, source = load_prices(symbol, max(days, YEAR_SESSIONS))
    df = full.tail(days)
    last = df.iloc[-1]
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else None
    close = float(last["close"])
    change_pct = (close / prev_close - 1) if prev_close else None
    series: List[Dict[str, Any]] = [
        {"date": pd.Timestamp(r.date).strftime("%Y-%m-%d"), "close": float(r.close),
         "volume": float(r.volume)}
        for r in df.itertuples()
    ]
    return finite({
        "symbol": symbol,
        "source": source,
        "demo": source == "demo",
        "as_of": series[-1]["date"],
        "close": close,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "high_52w": float(full["close"].tail(YEAR_SESSIONS).max()),
        "low_52w": float(full["close"].tail(YEAR_SESSIONS).min()),
        "series": series,
    })


@app.get("/v1/signals/{symbol}", dependencies=[Depends(require_key)])
def signal(symbol: str) -> Dict[str, Any]:
    symbol = clean_symbol(symbol)
    df, source = load_prices(symbol, 400)
    index_df = None
    if symbol not in data.INDEX_SYMBOLS:
        try:
            index_df, _ = load_prices("VNINDEX", 400)
        except HTTPException:
            index_df = None
    result = signals.score_stock(df, index_df)
    return finite({
        "symbol": symbol,
        "source": source,
        "demo": source == "demo",
        "label": signals.label(result.get("score")),
        "disclaimer": DISCLAIMER,
        **result,
    })


class PositionSizeIn(BaseModel):
    capital: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    risk_pct: float = Field(default=0.015, gt=0, le=0.1)
    max_alloc: float = Field(default=0.30, gt=0, le=1)


@app.post("/v1/risk/position-size", dependencies=[Depends(require_key)])
def position_size(body: PositionSizeIn) -> Dict[str, Any]:
    result = risk.position_size(body.capital, body.entry, body.stop,
                                risk_pct=body.risk_pct, max_alloc=body.max_alloc)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return finite({"disclaimer": DISCLAIMER, **result})


# --- Tin tức và bản tin sáng ---------------------------------------------------------------------------------------
# Tin lấy từ RSS (chậm, và không nên gọi dồn dập), nên giữ trong bộ nhớ vài phút. Chỉ ghép tin với mã khi tin NHẮC ĐÍCH
# DANH mã đó (xem news.match_symbol): không đoán tin liên quan.

NEWS_TTL_SECONDS = 10 * 60
BRIEF_TTL_SECONDS = 30 * 60
MAX_SYMBOLS = 20
_cache: Dict[str, tuple[float, Any]] = {}


def cached(key: str, ttl: int, load):
    hit = _cache.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    value = load()
    _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    _cache.clear()


def symbols_param(raw: str) -> List[str]:
    """`VNM,FPT` thành danh sách mã đã kiểm tra, không trùng, tối đa MAX_SYMBOLS."""
    out: List[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        symbol = clean_symbol(part)
        if symbol not in out:
            out.append(symbol)
    if not out:
        raise HTTPException(status_code=422, detail="no symbols")
    return out[:MAX_SYMBOLS]


def feed_items() -> List[Dict[str, Any]]:
    return cached("feed", NEWS_TTL_SECONDS, lambda: news.fetch_news())


@app.get("/v1/news", dependencies=[Depends(require_key)])
def stock_news(symbols: str = Query(...), limit: int = Query(default=5, ge=1, le=10)) -> Dict[str, Any]:
    wanted = symbols_param(symbols)
    items = feed_items()
    result = []
    for symbol in wanted:
        for item in news.match_symbol(items, symbol, limit):
            result.append({
                "symbol": symbol,
                "source": item.get("source", ""),
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "published": item.get("published", ""),
            })
    return {"items": result}


@app.get("/v1/brief", dependencies=[Depends(require_key)])
def morning_brief(symbols: str = Query(...)) -> Dict[str, Any]:
    """Bản tin sáng do AI viết từ tin tức, thị trường thế giới và điểm kỹ thuật của các mã. 503 nếu chưa cấu hình AI."""
    wanted = symbols_param(symbols)
    if not llm.has_key():
        raise HTTPException(status_code=503, detail="no llm configured")

    def build() -> Dict[str, Any]:
        watch = []
        for symbol in wanted:
            try:
                df, _ = load_prices(symbol, 400)
            except HTTPException:
                continue
            result = signals.score_stock(df, None)
            watch.append({"symbol": symbol, "score": result.get("score"), "close": result.get("close"),
                          "rsi": result.get("rsi"), "warnings": result.get("warnings", [])})
        raw = llm.morning_brief(news.filter_news(feed_items(), wanted), news.fetch_global_snapshot(), watch)
        return {
            "overview": raw.get("tong_quan", ""),
            "worldLink": raw.get("ket_noi_the_gioi", ""),
            "topNews": [
                {"title": n.get("tieu_de", ""), "symbols": n.get("ma_lien_quan", []),
                 "impact": n.get("tac_dong", "trung_tinh"), "level": n.get("muc_do", "thap"),
                 "comment": n.get("nhan_xet", "")}
                for n in raw.get("tin_quan_trong", [])[:6]
            ],
            "notes": [{"symbol": n.get("ma", ""), "comment": n.get("nhan_xet", "")} for n in raw.get("luu_y_danh_muc", [])],
            "risks": list(raw.get("rui_ro_can_theo_doi", [])),
            "confidence": raw.get("do_tin_cay_du_lieu", ""),
            "disclaimer": DISCLAIMER,
        }

    try:
        return cached("brief:" + ",".join(sorted(wanted)), BRIEF_TTL_SECONDS, build)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="brief failed")


class AssistantIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    context: str = Field(min_length=1, max_length=6000)


@app.post("/v1/assistant", dependencies=[Depends(require_key)])
def assistant(body: AssistantIn) -> Dict[str, Any]:
    """Trả lời một câu hỏi về tài chính của người dùng từ bản tóm tắt họ gửi. Không lưu gì. 503 nếu chưa cấu hình AI."""
    if not llm.has_key():
        raise HTTPException(status_code=503, detail="no llm configured")
    try:
        answer = llm.assistant_answer(body.question.strip(), body.context)
    except Exception:
        raise HTTPException(status_code=502, detail="assistant failed")
    if not answer:
        raise HTTPException(status_code=502, detail="assistant failed")
    return {"answer": answer, "disclaimer": DISCLAIMER}
