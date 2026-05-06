"""
agents/analysis/factor_identifier.py — The "meta-agent" that determines what factors
matter for a specific stock.

This is the key agentic behavior: the system dynamically decides WHAT to research
based on the specific company, industry, and current market conditions.
"""
from __future__ import annotations
import json
import re
from typing import Optional
from agents.llm_router import llm_call, LLMConfig, default_config
from broker import alpaca_client
from agents.trading.market_data_agent import market_data_agent

SYSTEM_PROMPT = (
    "You are a senior equity research director. Your job is to identify the key "
    "factors that will most impact a specific stock's price in the near term. "
    "You think about what is UNIQUE to this company — its industry, competitors, "
    "supply chain, regulatory environment, and current events. "
    "You do NOT give generic factors; every factor must be specific and actionable."
)

FACTOR_PROMPT = """Analyze {ticker} ({name}) and identify the 4 most important factors that will impact its stock price in the near term.

CURRENT MARKET DATA:
{market_data}

Think about what is specific to this company:
- What industry is it in? What affects that industry?
- Who are its main competitors? Any recent moves?
- What regulatory or policy changes could impact it?
- What macroeconomic forces affect its specific business?
- Any upcoming earnings, product launches, or events?

Respond with EXACTLY this JSON format (no markdown, no extra text):
[
  {{
    "factor_name": "short name (3-5 words)",
    "description": "1-2 sentence description of why this factor matters for {ticker}",
    "research_prompt": "A specific question to research about this factor and its impact on {ticker}"
  }},
  ...
]

Return exactly 4 factors. JSON:"""


def identify_factors(ticker: str, config: Optional[LLMConfig] = None,
                     token_callback=None) -> list[dict]:
    """
    Identify key factors affecting a stock.
    Returns: [{"factor_name": "...", "description": "...", "research_prompt": "..."}]
    """
    if config is None:
        config = default_config(label="Factor Identifier", max_tokens=500)

    # Build market context
    ticker = ticker.upper()
    try:
        scenario = market_data_agent.build_scenario(ticker)
        market_data = scenario.evidence_packet()
        name = scenario.asset_name
    except Exception:
        market_data = f"Unable to fetch live data for {ticker}."
        name = ticker

    prompt = FACTOR_PROMPT.format(ticker=ticker, name=name, market_data=market_data)
    raw = llm_call(prompt, system=SYSTEM_PROMPT, config=config, token_callback=token_callback)

    # Parse JSON response
    factors = _parse_factors(raw)

    # Fallback if parsing fails
    if not factors:
        factors = [
            {
                "factor_name": "Price Action & Technicals",
                "description": f"Current price trends and technical indicators for {ticker}.",
                "research_prompt": f"What do the current technical indicators (RSI, MACD, moving averages) suggest about {ticker}'s near-term direction?",
            },
            {
                "factor_name": "Industry Competition",
                "description": f"Competitive landscape affecting {ticker}'s market position.",
                "research_prompt": f"How are {ticker}'s main competitors performing and what competitive threats exist?",
            },
            {
                "factor_name": "Macroeconomic Environment",
                "description": f"Broader economic factors affecting {ticker}'s sector.",
                "research_prompt": f"How do current interest rates, inflation, and GDP growth affect {ticker}'s business?",
            },
            {
                "factor_name": "Recent News & Catalysts",
                "description": f"Recent news events and upcoming catalysts for {ticker}.",
                "research_prompt": f"What recent news or upcoming events could significantly move {ticker}'s stock price?",
            },
        ]

    return factors


def _parse_factors(raw: str) -> list[dict]:
    """Parse JSON array of factors from LLM response."""
    # Strip markdown code fences
    raw = re.sub(r"```json|```", "", raw).strip()

    # Try to find JSON array
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        return []

    try:
        factors = json.loads(match.group())
        if not isinstance(factors, list):
            return []

        valid = []
        for f in factors:
            if isinstance(f, dict) and "factor_name" in f:
                valid.append({
                    "factor_name": str(f.get("factor_name", "")),
                    "description": str(f.get("description", "")),
                    "research_prompt": str(f.get("research_prompt", "")),
                })
        return valid[:5]  # Cap at 5 factors
    except (json.JSONDecodeError, TypeError):
        return []
