"""chat/command_parser.py — Executes Claude tool calls against real system functions."""
from __future__ import annotations
import asyncio
import json
from broker import alpaca_client, order_manager
from core.database import SessionLocal
from core.models import Analysis, Trade
from core import events


async def execute_tool(tool_name: str, tool_input: dict, loop=None) -> dict:
    loop = loop or asyncio.get_event_loop()
    try:
        if tool_name == "get_portfolio":
            account   = alpaca_client.get_account()
            positions = alpaca_client.get_positions()
            return {
                "account": {
                    "equity":        float(account.get("equity",        0)),
                    "buying_power":  float(account.get("buying_power",  0)),
                    "cash":          float(account.get("cash",           0)),
                },
                "positions": [
                    {
                        "ticker":         p["symbol"],
                        "qty":            float(p["qty"]),
                        "avg_entry":      float(p["avg_entry_price"]),
                        "current_price":  float(p.get("current_price",   0)),
                        "unrealized_pl":  float(p.get("unrealized_pl",   0)),
                        "unrealized_plpc": float(p.get("unrealized_plpc", 0)),
                    }
                    for p in positions
                ],
            }

        elif tool_name == "get_account":
            a = alpaca_client.get_account()
            return {
                "equity":          float(a.get("equity",          0)),
                "buying_power":    float(a.get("buying_power",    0)),
                "cash":            float(a.get("cash",             0)),
                "portfolio_value": float(a.get("portfolio_value", 0)),
                "daytrade_count":  a.get("daytrade_count",         0),
            }

        elif tool_name == "get_quote":
            ticker = tool_input["ticker"].upper()
            trade  = alpaca_client.get_latest_trade(ticker)
            return {"ticker": ticker, "price": float(trade["trade"]["p"]), "timestamp": trade["trade"]["t"]}

        elif tool_name == "get_market_status":
            clock = alpaca_client.get_clock()
            return {
                "is_open":    clock.get("is_open",    False),
                "next_open":  clock.get("next_open"),
                "next_close": clock.get("next_close"),
            }

        elif tool_name == "place_order":
            ticker      = tool_input["ticker"].upper()
            side        = tool_input["side"]
            qty         = int(tool_input["qty"])
            order_type  = tool_input.get("order_type",  "market")
            limit_price = tool_input.get("limit_price")
            result = order_manager.place_and_record(
                order_params={"ticker": ticker, "side": side, "qty": qty,
                              "order_type": order_type, "limit_price": limit_price},
                loop=loop,
            )
            return {"success": True, "order_id": result.get("id"),
                    "status": result.get("status"), "ticker": ticker, "side": side, "qty": qty}

        elif tool_name == "cancel_order":
            order_manager.cancel_and_record(tool_input["order_id"])
            return {"success": True, "order_id": tool_input["order_id"]}

        elif tool_name == "cancel_all_orders":
            result = alpaca_client.cancel_all_orders()
            return {"success": True, "cancelled": result}

        elif tool_name == "get_orders":
            status = tool_input.get("status", "all")
            orders = alpaca_client.get_orders(status=status, limit=20)
            return {
                "orders": [
                    {"order_id": o["id"], "ticker": o["symbol"], "side": o["side"],
                     "qty": o["qty"], "status": o["status"], "type": o["type"],
                     "created_at": o["created_at"]}
                    for o in orders
                ]
            }

        elif tool_name == "get_analysis_history":
            limit = tool_input.get("limit", 10)
            db    = SessionLocal()
            try:
                rows = db.query(Analysis).order_by(Analysis.timestamp.desc()).limit(limit).all()
                return {
                    "analyses": [
                        {"id": a.id, "ticker": a.ticker, "decision": a.final_decision,
                         "confidence": a.confidence_score, "label": a.confidence_label,
                         "status": a.status, "timestamp": a.timestamp.isoformat() if a.timestamp else None}
                        for a in rows
                    ]
                }
            finally:
                db.close()

        elif tool_name == "run_analysis":
            ticker        = tool_input["ticker"].upper()
            rounds        = tool_input.get("rounds",         1)
            include_hold  = tool_input.get("include_hold",   False)
            auto_execute  = tool_input.get("auto_execute",   False)
            skip_judges   = tool_input.get("skip_judges",    False)
            skip_factcheck = tool_input.get("skip_factcheck", False)

            db = SessionLocal()
            try:
                analysis = Analysis(ticker=ticker, status="queued")
                db.add(analysis)
                db.commit()
                analysis_id = analysis.id
            finally:
                db.close()

            from pipeline.analysis_pipeline import run_analysis
            asyncio.ensure_future(run_analysis(
                ticker=ticker, analysis_id=analysis_id,
                rounds=rounds, include_hold=include_hold,
                skip_judges=skip_judges, skip_factcheck=skip_factcheck,
                auto_execute=auto_execute, loop=loop,
            ))
            return {
                "success":     True,
                "analysis_id": analysis_id,
                "ticker":      ticker,
                "message":     f"Debate analysis started for {ticker}. Watch the Analysis tab for live results.",
                "auto_execute": auto_execute,
            }

        elif tool_name == "emergency_stop":
            ticker = tool_input["ticker"].upper()
            from pipeline.execution_pipeline import emergency_flatten
            result = await emergency_flatten(ticker, loop=loop)
            return {"success": True, "ticker": ticker, "result": result}

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        return {"error": str(e), "tool": tool_name}
