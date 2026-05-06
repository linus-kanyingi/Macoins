"""
agents/expert/expert_agent.py — User-configured autonomous trading agent.

An experienced user creates an agent with:
  - A specific stock ticker
  - Strategy instructions (free text, e.g. "Buy when RSI < 30, sell when RSI > 70")
  - A schedule (cron expression)
  - An LLM model of their choice

On each scheduled run, the agent:
  1. Queries current market data from Alpaca
  2. Applies the user's strategy via LLM
  3. Decides action (BUY / SELL / HOLD)
  4. Optionally executes via Alpaca
  5. Logs reasoning and decision
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from agents.llm_router import llm_call, LLMConfig, default_config
from agents.trading.market_data_agent import market_data_agent
from core.database import SessionLocal
from core.models import ExpertAgent, ExpertAgentLog


SYSTEM_PROMPT = (
    "You are an autonomous trading agent executing a specific strategy "
    "defined by your operator. You follow their instructions precisely. "
    "You are disciplined, data-driven, and risk-aware. "
    "You make ONE clear decision: BUY, SELL, or HOLD. "
    "Respond ONLY with valid JSON — no markdown, no extra text."
)

STRATEGY_PROMPT = """You are an autonomous trading agent for {ticker}.

YOUR OPERATOR'S STRATEGY:
{strategy}

CURRENT MARKET DATA:
{market_data}

Based on the strategy and current market conditions, make a trading decision.

Respond with this exact JSON format:
{{
  "decision": "BUY" or "SELL" or "HOLD",
  "reasoning": "2-3 sentence explanation of why, referencing the strategy and data",
  "confidence": 0.0-1.0
}}

JSON:"""


@dataclass
class AgentDecision:
    decision: str       # BUY / SELL / HOLD
    reasoning: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
        }


def run_expert_agent(agent_id: int) -> dict:
    """
    Execute a single run of an expert agent.
    Called by the scheduler or manually via API.
    Returns the decision dict.
    """
    db = SessionLocal()
    try:
        agent = db.query(ExpertAgent).filter(ExpertAgent.id == agent_id).first()
        if not agent:
            return {"error": f"Agent {agent_id} not found"}
        if not agent.enabled:
            return {"error": f"Agent {agent_id} is disabled"}

        ticker = agent.ticker.upper()
        strategy = agent.strategy

        # Parse LLM config
        try:
            config_dict = json.loads(agent.llm_config) if agent.llm_config else {}
            config = LLMConfig.from_dict(config_dict) if config_dict else default_config()
        except Exception:
            config = default_config()
        config.label = f"Expert: {agent.name}"
        config.max_tokens = 300

        # Get market data
        try:
            scenario = market_data_agent.build_scenario(ticker)
            market_data = scenario.evidence_packet()
        except Exception as e:
            market_data = f"Error fetching market data: {e}"

        # Run LLM decision
        prompt = STRATEGY_PROMPT.format(
            ticker=ticker,
            strategy=strategy,
            market_data=market_data,
        )

        raw = llm_call(prompt, system=SYSTEM_PROMPT, config=config)
        decision = _parse_decision(raw)

        # Log the run
        log = ExpertAgentLog(
            agent_id=agent_id,
            market_data=market_data[:2000],
            reasoning=decision.reasoning,
            decision=decision.decision,
            executed=False,
        )

        # Auto-execute if enabled
        order_id = None
        if agent.auto_execute and decision.decision != "HOLD" and decision.confidence >= 0.5:
            try:
                order_id = _execute_decision(ticker, decision)
                log.executed = True
                log.order_id = order_id
            except Exception as e:
                log.error = str(e)

        db.add(log)
        agent.last_run = datetime.utcnow()
        db.commit()

        result = decision.to_dict()
        result["agent_id"] = agent_id
        result["agent_name"] = agent.name
        result["ticker"] = ticker
        result["executed"] = log.executed
        result["order_id"] = order_id
        return result

    except Exception as e:
        # Log error
        try:
            error_log = ExpertAgentLog(
                agent_id=agent_id,
                error=str(e),
                decision="ERROR",
            )
            db.add(error_log)
            db.commit()
        except Exception:
            pass
        return {"error": str(e), "agent_id": agent_id}
    finally:
        db.close()


def _parse_decision(raw: str) -> AgentDecision:
    """Parse JSON decision from LLM response."""
    raw = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)

    if match:
        try:
            obj = json.loads(match.group())
            decision = str(obj.get("decision", "HOLD")).upper().strip()
            if decision not in ("BUY", "SELL", "HOLD"):
                decision = "HOLD"
            confidence = max(0.0, min(1.0, float(obj.get("confidence", 0.5))))
            return AgentDecision(
                decision=decision,
                reasoning=str(obj.get("reasoning", ""))[:500],
                confidence=confidence,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    return AgentDecision(
        decision="HOLD",
        reasoning="Could not parse agent decision. Defaulting to HOLD.",
        confidence=0.3,
    )


def _execute_decision(ticker: str, decision: AgentDecision) -> Optional[str]:
    """Execute a trade decision via Alpaca. Returns order ID."""
    from broker import alpaca_client, order_manager

    side = "buy" if decision.decision == "BUY" else "sell"

    # Determine quantity based on account
    account = alpaca_client.get_account()
    equity = float(account.get("equity", 0))
    trade_data = alpaca_client.get_latest_trade(ticker)
    price = float(trade_data["trade"]["p"])

    if price <= 0 or equity <= 0:
        return None

    # Use 3% of equity per trade
    max_value = equity * 0.03
    qty = int(max_value / price)
    if qty < 1:
        return None

    result = order_manager.place_and_record(
        order_params={"ticker": ticker, "side": side, "qty": qty},
        source="expert",
    )
    return result.get("id")
