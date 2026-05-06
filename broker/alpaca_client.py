"""
broker/alpaca_client.py — Full Alpaca REST wrapper using requests only (no Alpaca SDK).
"""
import requests
from core.config import settings

BASE = settings.ALPACA_BASE_URL
DATA_BASE = settings.ALPACA_DATA_URL
HEADERS = {
    "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
    "Content-Type": "application/json",
}


class AlpacaError(Exception):
    pass


def _get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=10)
    if not r.ok:
        raise AlpacaError(f"{r.status_code}: {r.text}")
    return r.json()


def _post(url, body):
    r = requests.post(url, headers=HEADERS, json=body, timeout=10)
    if not r.ok:
        raise AlpacaError(f"{r.status_code}: {r.text}")
    return r.json()


def _delete(url):
    r = requests.delete(url, headers=HEADERS, timeout=10)
    if r.status_code == 204:
        return True
    if not r.ok:
        raise AlpacaError(f"{r.status_code}: {r.text}")
    return True


def get_account():
    return _get(f"{BASE}/account")


def get_positions():
    return _get(f"{BASE}/positions")


def get_position(ticker):
    return _get(f"{BASE}/positions/{ticker}")


def get_orders(status="all", limit=50):
    return _get(f"{BASE}/orders", params={"status": status, "limit": limit})


def place_order(ticker, side, qty, order_type="market", time_in_force="day",
                limit_price=None, trail_percent=None):
    body = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if limit_price:
        body["limit_price"] = str(limit_price)
    if trail_percent:
        body["trail_percent"] = str(trail_percent)
    return _post(f"{BASE}/orders", body)


def cancel_order(order_id):
    return _delete(f"{BASE}/orders/{order_id}")


def cancel_all_orders():
    r = requests.delete(f"{BASE}/orders", headers=HEADERS, timeout=10)
    if r.status_code == 207:
        return r.json()
    if r.status_code == 204:
        return []
    return r.json() if r.text else []


def get_latest_quote(ticker):
    return _get(f"{DATA_BASE}/stocks/{ticker}/quotes/latest")


def get_latest_trade(ticker):
    return _get(f"{DATA_BASE}/stocks/{ticker}/trades/latest")


def get_bars(ticker, timeframe="1Day", limit=30):
    return _get(
        f"{DATA_BASE}/stocks/{ticker}/bars",
        params={"timeframe": timeframe, "limit": limit, "feed": "iex"},
    )


def get_news(ticker, limit=5):
    try:
        return _get(f"{BASE}/news", params={"symbols": ticker, "limit": limit})
    except Exception:
        return []


def get_clock():
    return _get(f"{BASE}/clock")


def get_calendar(start=None, end=None):
    params = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return _get(f"{BASE}/calendar", params=params)
