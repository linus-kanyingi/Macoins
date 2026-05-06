"""chat/context_builder.py — Builds dynamic system prompt with live portfolio context."""
from broker import alpaca_client
from core.config import settings


def build_system_prompt() -> str:
    try:
        account   = alpaca_client.get_account()
        positions = alpaca_client.get_positions()
        clock     = alpaca_client.get_clock()

        equity       = float(account.get("equity",       0))
        buying_power = float(account.get("buying_power", 0))
        market_open  = clock.get("is_open", False)

        pos_lines = []
        for p in positions:
            pl    = float(p.get("unrealized_pl",   0))
            plpc  = float(p.get("unrealized_plpc", 0)) * 100
            pos_lines.append(
                f"  - {p['symbol']}: {p['qty']} shares @ avg ${float(p['avg_entry_price']):.2f} | "
                f"P&L ${pl:+.2f} ({plpc:+.1f}%)"
            )
        portfolio_section = "\n".join(pos_lines) if pos_lines else "  No open positions"

    except Exception:
        equity = buying_power = 0
        market_open           = False
        portfolio_section     = "  (Unable to fetch portfolio — Alpaca may be unavailable)"

    return f"""You are the AI Command Center for a paper trading platform powered by multi-agent debate analysis.

## Current State
- Market: {"🟢 OPEN" if market_open else "🔴 CLOSED"}
- Account Equity: ${equity:,.2f}
- Buying Power: ${buying_power:,.2f}

## Current Positions:
{portfolio_section}

## Risk Limits
- Max position size: {settings.MAX_POSITION_PCT * 100:.0f}% of equity per trade
- Max open positions: {settings.MAX_OPEN_POSITIONS}
- Min confidence to auto-execute: {settings.MIN_CONFIDENCE_TO_EXECUTE * 100:.0f}%
- Stop loss threshold: {settings.STOP_LOSS_PCT * 100:.0f}%

## Your Capabilities
You can: run multi-agent stock debate analysis, place/cancel orders, check portfolio and positions, get live quotes, view order history, check market status, and schedule recurring analysis jobs.

## Behavior Guidelines
- This is PAPER TRADING — educational simulation, no real money at risk
- Always explain your reasoning before taking action
- For large or risky trades, briefly summarize the risk
- When analyzing stocks, prefer running a debate analysis first
- If the market is closed, orders will queue for next open
- Be concise but informative. Use bullet points for lists.
- When you run analysis, tell the user to watch the Analysis tab for the live debate"""
