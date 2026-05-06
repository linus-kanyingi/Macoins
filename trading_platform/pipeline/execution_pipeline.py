"""pipeline/execution_pipeline.py — Converts debate verdict into Alpaca orders."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from broker import alpaca_client, order_manager
from agents.trading.execution_agent import execution_agent
from core import events

_executor = ThreadPoolExecutor(max_workers=2)


async def execute_verdict(verdict_dict: dict, ticker: str,
                          analysis_id: int = None, loop=None):
    loop = loop or asyncio.get_event_loop()

    def _get_market():
        account   = alpaca_client.get_account()
        positions = alpaca_client.get_positions()
        try:
            trade = alpaca_client.get_latest_trade(ticker)
            price = float(trade["trade"]["p"])
        except Exception:
            price = 0.0
        return account, positions, price

    account, positions, current_price = await loop.run_in_executor(_executor, _get_market)

    equity       = float(account.get("equity",       0))
    buying_power = float(account.get("buying_power", 0))
    open_count   = len(positions)

    order_params = execution_agent.verdict_to_order_params(
        verdict=verdict_dict, ticker=ticker,
        account_equity=equity, buying_power=buying_power,
        open_position_count=open_count, current_price=current_price,
    )

    if not order_params:
        await events.manager.broadcast({
            "type":   events.EVT_CHAT_ACTION,
            "action": "execution_skipped",
            "ticker": ticker,
            "reason": "HOLD, low confidence, or risk limits blocked execution",
        })
        return None

    def _place():
        return order_manager.place_and_record(
            order_params={
                "ticker":      order_params.ticker,
                "side":        order_params.side,
                "qty":         order_params.qty,
                "order_type":  order_params.order_type,
                "time_in_force": order_params.time_in_force,
            },
            analysis_id=analysis_id,
            source="analysis",
            loop=loop,
        )

    result = await loop.run_in_executor(_executor, _place)

    await events.manager.broadcast({
        "type":        events.EVT_TRADE_FILL,
        "ticker":      ticker,
        "side":        order_params.side,
        "qty":         order_params.qty,
        "order_id":    result.get("id"),
        "analysis_id": analysis_id,
    })
    return result


async def emergency_flatten(ticker: str, loop=None):
    """Market-sell entire position in ticker immediately."""
    loop = loop or asyncio.get_event_loop()

    def _flatten():
        try:
            pos  = alpaca_client.get_position(ticker)
            qty  = abs(float(pos["qty"]))
            side = "sell" if pos.get("side") == "long" else "buy"
            return order_manager.place_and_record(
                {"ticker": ticker, "side": side, "qty": qty}, loop=loop
            )
        except Exception as e:
            return {"error": str(e)}

    return await loop.run_in_executor(_executor, _flatten)
