"""
agents/analysis/stock_picker.py — Suggests top 3 stocks for users who don't know what to trade.

Uses Alpaca market data (top movers) + LLM reasoning to recommend stocks.
"""
from __future__ import annotations
from typing import Optional
from agents.llm_router import llm_call, LLMConfig, default_config
from broker import alpaca_client

SYSTEM_PROMPT = (
    "You are a senior financial analyst helping a beginner investor pick stocks to analyze. "
    "You are practical, clear, and avoid jargon. You suggest stocks that are interesting "
    "for analysis — ones with active price movement, recent news, or upcoming catalysts."
)

PICK_PROMPT = """Based on the following market data, suggest exactly 3 stocks for a beginner investor to analyze today.

MARKET DATA:
{market_data}

For each stock, provide:
1. The ticker symbol
2. The company name
3. A brief 1-2 sentence reason why it's interesting to analyze right now

Respond in this exact format (no markdown, no extra text):
STOCK 1: [TICKER] | [Company Name] | [Reason]
STOCK 2: [TICKER] | [Company Name] | [Reason]
STOCK 3: [TICKER] | [Company Name] | [Reason]
"""


def _gather_market_context() -> str:
    """Gather market data from Alpaca to inform stock suggestions."""
    lines = []

    # Get some well-known tickers with recent price action
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "AMD", "NFLX", "JPM"]
    for t in tickers:
        try:
            trade = alpaca_client.get_latest_trade(t)
            price = float(trade["trade"]["p"])
            bars = alpaca_client.get_bars(t, timeframe="1Day", limit=5)
            bar_list = bars.get("bars", [])
            if bar_list:
                prev_close = float(bar_list[-2]["c"]) if len(bar_list) >= 2 else price
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
                lines.append(f"{t}: ${price:.2f} ({change_pct:+.1f}% today)")
        except Exception:
            continue

    # Get news for context
    for t in ["AAPL", "NVDA", "TSLA"]:
        try:
            news = alpaca_client.get_news(t, limit=2)
            if isinstance(news, list):
                for n in news[:2]:
                    lines.append(f"NEWS [{t}]: {n.get('headline', '')}")
        except Exception:
            continue

    return "\n".join(lines) if lines else "No market data available — suggest based on general knowledge."


def suggest_stocks(config: Optional[LLMConfig] = None) -> list[dict]:
    """
    Returns list of 3 stock suggestions:
    [{"ticker": "AAPL", "name": "Apple Inc.", "reason": "..."}]
    """
    if config is None:
        config = default_config(label="Stock Picker", max_tokens=300)

    market_data = _gather_market_context()
    prompt = PICK_PROMPT.format(market_data=market_data)

    raw = llm_call(prompt, system=SYSTEM_PROMPT, config=config)

    # Parse response
    suggestions = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or "STOCK" not in line.upper():
            continue
        # Remove the "STOCK N:" prefix
        parts = line.split(":", 1)
        if len(parts) < 2:
            continue
        data = parts[1].strip()
        fields = [f.strip() for f in data.split("|")]
        if len(fields) >= 3:
            suggestions.append({
                "ticker": fields[0].upper().strip(),
                "name": fields[1].strip(),
                "reason": fields[2].strip(),
            })
        elif len(fields) == 2:
            suggestions.append({
                "ticker": fields[0].upper().strip(),
                "name": fields[0].upper().strip(),
                "reason": fields[1].strip(),
            })

    # Fallback if parsing fails
    if not suggestions:
        suggestions = [
            {"ticker": "AAPL", "name": "Apple Inc.", "reason": "High-profile tech stock with consistent movement."},
            {"ticker": "NVDA", "name": "NVIDIA Corp.", "reason": "AI chip leader with volatile price action."},
            {"ticker": "TSLA", "name": "Tesla Inc.", "reason": "Always newsworthy with significant daily swings."},
        ]

    return suggestions[:3]
