"""
broker/order_manager.py — Place and track orders; sync with Alpaca.
"""
from datetime import datetime
from broker import alpaca_client
from core.models import Trade, RiskLog
from core import events
from core.database import SessionLocal


def place_and_record(order_params: dict, analysis_id=None, source="manual", loop=None) -> dict:
    """Place order on Alpaca and record in DB. Returns order dict."""
    result = alpaca_client.place_order(
        ticker=order_params["ticker"],
        side=order_params["side"],
        qty=order_params["qty"],
        order_type=order_params.get("order_type", "market"),
        time_in_force=order_params.get("time_in_force", "day"),
        limit_price=order_params.get("limit_price"),
    )

    db = SessionLocal()
    try:
        trade = Trade(
            order_id=result["id"],
            ticker=order_params["ticker"],
            side=order_params["side"],
            qty=order_params["qty"],
            price=order_params.get("limit_price"),
            status=result.get("status", "accepted"),
            source=source,
            analysis_id=analysis_id,
        )
        db.add(trade)
        db.commit()
    finally:
        db.close()

    # Broadcast fill event
    msg = {
        "type": events.EVT_TRADE_FILL,
        "order_id": result["id"],
        "ticker": order_params["ticker"],
        "side": order_params["side"],
        "qty": order_params["qty"],
        "status": result.get("status"),
        "timestamp": datetime.utcnow().isoformat(),
    }
    if loop:
        events.manager.broadcast_sync(msg, loop)

    return result


def cancel_and_record(order_id: str) -> bool:
    alpaca_client.cancel_order(order_id)
    db = SessionLocal()
    try:
        trade = db.query(Trade).filter(Trade.order_id == order_id).first()
        if trade:
            trade.status = "cancelled"
            db.commit()
    finally:
        db.close()
    return True


def sync_open_orders():
    """Sync all open orders from Alpaca to DB."""
    try:
        orders = alpaca_client.get_orders(status="open")
        db = SessionLocal()
        try:
            for o in orders:
                trade = db.query(Trade).filter(Trade.order_id == o["id"]).first()
                if trade:
                    trade.status = o["status"]
                    if o.get("filled_at"):
                        trade.filled_at = datetime.fromisoformat(
                            o["filled_at"].replace("Z", "+00:00")
                        )
                    if o.get("filled_avg_price"):
                        trade.price = float(o["filled_avg_price"])
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[OrderManager] sync error: {e}")
