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
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src import data, risk, signals

load_dotenv()

DISCLAIMER = "Công cụ hỗ trợ ra quyết định, không phải lời khuyên đầu tư."
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
    return df.sort_values("date").reset_index(drop=True), source


@app.get("/v1/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "demo_mode": os.getenv("DEMO_MODE") == "1"}


@app.get("/v1/quotes/{symbol}", dependencies=[Depends(require_key)])
def quote(symbol: str, days: int = Query(default=250, ge=2, le=2500)) -> Dict[str, Any]:
    symbol = clean_symbol(symbol)
    df, source = load_prices(symbol, days)
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
        "high_52w": float(df["close"].tail(250).max()),
        "low_52w": float(df["close"].tail(250).min()),
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
