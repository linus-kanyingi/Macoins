"""
broker/portfolio_tracker.py — Sync portfolio from Alpaca and broadcast updates.
"""
from broker import alpaca_client
from core import events


def sync_portfolio(loop=None):
    """Fetch positions and account from Alpaca, broadcast update."""
    try:
        account = alpaca_client.get_account()
        positions = alpaca_client.get_positions()

        payload = {
            "type": events.EVT_PORTFOLIO_UPDATE,
            "account": {
                "equity": float(account.get("equity", 0)),
                "buying_power": float(account.get("buying_power", 0)),
                "cash": float(account.get("cash", 0)),
                "portfolio_value": float(account.get("portfolio_value", 0)),
                "daytrade_count": account.get("daytrade_count", 0),
            },
            "positions": [
                {
                    "ticker": p["symbol"],
                    "qty": float(p["qty"]),
                    "avg_entry_price": float(p["avg_entry_price"]),
                    "current_price": float(p.get("current_price", 0)),
                    "market_value": float(p.get("market_value", 0)),
                    "unrealized_pl": float(p.get("unrealized_pl", 0)),
                    "unrealized_plpc": float(p.get("unrealized_plpc", 0)),
                    "side": p.get("side", "long"),
                }
                for p in positions
            ],
        }

        if loop:
            events.manager.broadcast_sync(payload, loop)
        return payload
    except Exception as e:
        print(f"[PortfolioTracker] error: {e}")
        return None
