"""agents/trading/execution_agent.py — Converts debate verdict into executable order params."""
from dataclasses import dataclass
from typing import Optional
from agents.trading.risk_agent import risk_agent, RiskDecision
from core.config import settings


@dataclass
class OrderParams:
    ticker: str
    side: str
    qty: int
    order_type: str = "market"
    time_in_force: str = "day"
    limit_price: Optional[float] = None


class ExecutionAgent:
    def verdict_to_order_params(
        self,
        verdict: dict,
        ticker: str,
        account_equity: float,
        buying_power: float,
        open_position_count: int,
        current_price: float,
    ) -> Optional[OrderParams]:
        decision   = verdict.get("final_decision", "HOLD")
        confidence = verdict.get("confidence_score", 0.0)

        if decision == "HOLD":
            return None
        if confidence < settings.MIN_CONFIDENCE_TO_EXECUTE:
            return None
        if current_price <= 0:
            return None

        max_value = account_equity * settings.MAX_POSITION_PCT
        qty       = int(max_value / current_price)
        if qty < 1:
            return None

        side = "buy" if decision == "BUY" else "sell"

        risk = risk_agent.approve_trade(
            ticker=ticker, side=side, qty=qty, price=current_price,
            account_equity=account_equity, open_position_count=open_position_count,
        )
        if not risk.approved:
            return None

        final_qty = risk.adjusted_qty or qty
        return OrderParams(ticker=ticker, side=side, qty=final_qty)


execution_agent = ExecutionAgent()
