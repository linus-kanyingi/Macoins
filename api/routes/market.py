"""api/routes/market.py — Market data endpoints."""
from fastapi import APIRouter, HTTPException
from broker import alpaca_client

router = APIRouter()


@router.get("/api/market/quote/{ticker}")
def get_quote(ticker: str):
    try:
        trade = alpaca_client.get_latest_trade(ticker.upper())
        return {"ticker": ticker.upper(), "price": float(trade["trade"]["p"]), "timestamp": trade["trade"]["t"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/market/bars/{ticker}")
def get_bars(ticker: str, timeframe: str = "1Day", limit: int = 30):
    try:
        data = alpaca_client.get_bars(ticker.upper(), timeframe=timeframe, limit=limit)
        return {"ticker": ticker.upper(), "bars": data.get("bars", [])}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/market/clock")
def get_clock():
    try:
        return alpaca_client.get_clock()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/market/news/{ticker}")
def get_news(ticker: str, limit: int = 5):
    try:
        return {"ticker": ticker.upper(), "news": alpaca_client.get_news(ticker.upper(), limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
