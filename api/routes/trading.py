"""api/routes/trading.py — Account, positions, and orders endpoints."""
from __future__ import annotations
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from broker import alpaca_client, order_manager
from core.database import get_session
from core.models import Trade

router = APIRouter()


class OrderRequest(BaseModel):
    ticker: str
    side: str
    qty: int
    order_type: str = "market"
    time_in_force: str = "day"
    limit_price: Optional[float] = None
    trail_percent: Optional[float] = None
    source: str = "manual"  # manual / analysis / expert


# ── Account ────────────────────────────────────────────────────────────────────

@router.get("/api/account")
def get_account():
    try:
        account = alpaca_client.get_account()
        clock   = alpaca_client.get_clock()
        return {
            "equity":          float(account.get("equity",          0)),
            "buying_power":    float(account.get("buying_power",    0)),
            "cash":            float(account.get("cash",             0)),
            "portfolio_value": float(account.get("portfolio_value", 0)),
            "daytrade_count":  account.get("daytrade_count",         0),
            "market_open":     clock.get("is_open", False),
            "next_open":       clock.get("next_open"),
            "next_close":      clock.get("next_close"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Positions ──────────────────────────────────────────────────────────────────

@router.get("/api/positions")
def get_positions():
    try:
        return {"positions": alpaca_client.get_positions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Orders ─────────────────────────────────────────────────────────────────────

@router.get("/api/orders")
def get_orders(status: str = "all", limit: int = 50,
               source: Optional[str] = None,
               db: Session = Depends(get_session)):
    """Get orders merged from Alpaca + local DB (which has source info)."""
    try:
        # Fetch from Alpaca
        alpaca_orders = alpaca_client.get_orders(status=status, limit=limit)

        # Build a lookup from local DB by order_id
        query = db.query(Trade)
        if source:
            query = query.filter(Trade.source == source)
        local_trades = {t.order_id: t for t in query.all()}

        # If filtering by source, only return orders that match
        merged = []
        for o in alpaca_orders:
            order_id = o.get("id")
            local = local_trades.get(order_id)

            if source and not local:
                continue  # Skip orders not in local DB when filtering by source

            merged.append({
                "id":             order_id,
                "ticker":         o.get("symbol", ""),
                "side":           o.get("side", ""),
                "qty":            o.get("qty", "0"),
                "filled_qty":     o.get("filled_qty", "0"),
                "type":           o.get("type", "market"),
                "time_in_force":  o.get("time_in_force", "day"),
                "status":         o.get("status", ""),
                "limit_price":    o.get("limit_price"),
                "filled_avg_price": o.get("filled_avg_price"),
                "submitted_at":   o.get("submitted_at"),
                "filled_at":      o.get("filled_at"),
                "source":         local.source if local else "unknown",
                "analysis_id":    local.analysis_id if local else None,
            })

        # Also include local-only orders (not yet in Alpaca response, if any)
        alpaca_ids = {o.get("id") for o in alpaca_orders}
        for order_id, trade in local_trades.items():
            if order_id not in alpaca_ids:
                merged.append({
                    "id":             order_id,
                    "ticker":         trade.ticker,
                    "side":           trade.side,
                    "qty":            str(int(trade.qty)) if trade.qty else "0",
                    "filled_qty":     "0",
                    "type":           "market",
                    "time_in_force":  "day",
                    "status":         trade.status or "unknown",
                    "limit_price":    trade.price,
                    "filled_avg_price": None,
                    "submitted_at":   trade.created_at.isoformat() if trade.created_at else None,
                    "filled_at":      trade.filled_at.isoformat() if trade.filled_at else None,
                    "source":         trade.source or "unknown",
                    "analysis_id":    trade.analysis_id,
                })

        return {"orders": merged}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/orders")
async def place_order(req: OrderRequest):
    """Place a new order. Works when market is open (fills immediately) or
    closed (queued as a day order for next open)."""
    loop = asyncio.get_event_loop()
    try:
        params = {
            "ticker":        req.ticker.upper(),
            "side":          req.side.lower(),
            "qty":           req.qty,
            "order_type":    req.order_type,
            "time_in_force": req.time_in_force,
            "limit_price":   req.limit_price,
        }
        # Run blocking Alpaca HTTP call in a thread so we don't block the event loop
        result = await loop.run_in_executor(
            None,
            lambda: order_manager.place_and_record(
                order_params=params, source=req.source, loop=loop
            ),
        )
        return result
    except Exception as e:
        error_msg = str(e)
        # Give a friendly message for common Alpaca rejections
        if "insufficient" in error_msg.lower() or "buying power" in error_msg.lower():
            raise HTTPException(status_code=400, detail="Insufficient buying power for this order.")
        if "wash" in error_msg.lower():
            raise HTTPException(status_code=400, detail="Wash trade detected — cancel the opposing open order first.")
        if "short" in error_msg.lower():
            raise HTTPException(status_code=400, detail="Cannot short sell — a long order is still open for this symbol.")
        raise HTTPException(status_code=400, detail=error_msg)


@router.delete("/api/orders")
async def cancel_all_orders():
    """Cancel ALL open orders."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, alpaca_client.cancel_all_orders)
        return {"success": True, "cancelled": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/orders/emergency-stop")
async def emergency_stop_route():
    """Cancel all orders and flatten all positions at market."""
    loop = asyncio.get_event_loop()
    try:
        from pipeline.execution_pipeline import emergency_flatten
        await emergency_flatten(loop=loop)
        return {"success": True, "message": "Emergency stop executed — all positions flattened."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/orders/{order_id}")
async def cancel_order(order_id: str):
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: order_manager.cancel_and_record(order_id))
        return {"success": True, "order_id": order_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
