"""
core/events.py — WebSocket broadcast manager and event type constants.
"""
from fastapi import WebSocket
import asyncio
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

    def broadcast_sync(self, message: dict, loop: asyncio.AbstractEventLoop):
        """Call from sync/thread context. Schedules broadcast on the event loop and
        discards the future — fire-and-forget for WebSocket push."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is loop:
            loop.create_task(self.broadcast(message))
        else:
            try:
                future = asyncio.run_coroutine_threadsafe(self.broadcast(message), loop)
                # Don't wait, but add a done-callback so any exception is swallowed cleanly
                future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
            except RuntimeError:
                pass  # loop not running (e.g. during shutdown)


manager = ConnectionManager()

# ── Analysis pipeline events ──────────────────────────────────────────────────
EVT_ANALYSIS_STARTED       = "analysis_started"
EVT_STOCK_SUGGESTIONS      = "stock_suggestions"
EVT_FACTORS_IDENTIFIED     = "factors_identified"
EVT_RESEARCH_STARTED       = "research_started"
EVT_RESEARCH_REPORT        = "research_report"
EVT_DEBATE_ARGUMENT        = "debate_argument"
EVT_VERDICT                = "verdict"
EVT_ANALYSIS_COMPLETE      = "analysis_complete"
EVT_ANALYSIS_ERROR         = "analysis_error"
EVT_ANALYSIS_TOKEN         = "analysis_token"

# ── Trading events ────────────────────────────────────────────────────────────
EVT_PORTFOLIO_UPDATE       = "portfolio_update"
EVT_TRADE_FILL             = "trade_fill"
EVT_PRICE_TICK             = "price_tick"
EVT_RISK_WARNING           = "risk_warning"

# ── Expert agent events ───────────────────────────────────────────────────────
EVT_EXPERT_AGENT_RUN       = "expert_agent_run"
EVT_EXPERT_AGENT_DECISION  = "expert_agent_decision"

# ── System events ─────────────────────────────────────────────────────────────
EVT_SCHEDULER_RUN          = "scheduler_run"
