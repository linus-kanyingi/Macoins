"""
agents/analysis/debate_agent.py — Bull vs Bear debate agents.

Unlike the old fixed debate system, these agents receive ALL research reports
and debate based on the dynamic research findings.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from agents.llm_router import llm_call, LLMConfig, default_config


@dataclass
class DebateArgument:
    side: str           # bull / bear
    phase: str          # opening / rebuttal / closing
    content: str

    def to_dict(self) -> dict:
        return {"side": self.side, "phase": self.phase, "content": self.content}


BULL_SYSTEM = (
    "You are BULL — a senior equity analyst who argues FOR buying this stock. "
    "You use specific findings from the research reports to build a compelling case. "
    "You are confident, data-driven, and persuasive. You always argue for BUY."
)

BEAR_SYSTEM = (
    "You are BEAR — a senior equity analyst who argues AGAINST buying this stock. "
    "You use specific findings from the research reports to highlight risks and downsides. "
    "You are cautious, evidence-based, and risk-aware. You always argue for SELL or avoid."
)


def _build_research_summary(research_reports: list[dict]) -> str:
    """Format research reports into a readable summary for debate agents."""
    lines = []
    for r in research_reports:
        impact_icon = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(r.get("impact", ""), "❓")
        lines.append(
            f"[{impact_icon} {r['factor_name']}] ({r.get('impact', 'neutral').upper()}, "
            f"confidence: {r.get('confidence', 'medium')})\n"
            f"  {r.get('summary', r.get('findings', '')[:100])}"
        )
    return "\n\n".join(lines)


OPENING_PROMPT = """You are debating whether to BUY or SELL {ticker}.

RESEARCH REPORTS FROM ANALYSTS:
{research_summary}

MARKET DATA:
{market_data}

TASK — OPENING ARGUMENT:
Give 2-3 strong, evidence-backed arguments for YOUR stance ({side}).
Reference specific findings from the research reports.
Max 150 words. Be compelling and cite data.
"""

REBUTTAL_PROMPT = """You are debating whether to BUY or SELL {ticker}.

RESEARCH REPORTS:
{research_summary}

YOUR OPPONENT ({opponent_side}) JUST ARGUED:
{opponent_argument}

TASK — REBUTTAL:
1. Counter ONE specific point from your opponent's argument
2. Reinforce your strongest evidence-backed argument for {side}
Max 120 words. Stay on YOUR side.
"""

CLOSING_PROMPT = """You are debating whether to BUY or SELL {ticker}.

TASK — CLOSING STATEMENT:
State your final recommendation: {side}.
Give ONE most compelling reason backed by the research.
Max 60 words. End with "My recommendation: {side}."
"""


def debate_opening(ticker: str, side: str,
                   research_reports: list[dict],
                   market_data: str = "",
                   config: Optional[LLMConfig] = None,
                   token_callback=None) -> DebateArgument:
    """Generate opening argument for bull or bear side."""
    if config is None:
        config = default_config(label=f"Debate {side.upper()}", max_tokens=200)

    system = BULL_SYSTEM if side == "bull" else BEAR_SYSTEM
    research_summary = _build_research_summary(research_reports)

    prompt = OPENING_PROMPT.format(
        ticker=ticker.upper(), side=side.upper(),
        research_summary=research_summary, market_data=market_data[:800],
    )

    content = llm_call(prompt, system=system, config=config, token_callback=token_callback)
    return DebateArgument(side=side, phase="opening", content=content)


def debate_rebuttal(ticker: str, side: str,
                    research_reports: list[dict],
                    opponent_argument: str,
                    config: Optional[LLMConfig] = None,
                    token_callback=None) -> DebateArgument:
    """Generate rebuttal argument."""
    if config is None:
        config = default_config(label=f"Debate {side.upper()}", max_tokens=180)

    system = BULL_SYSTEM if side == "bull" else BEAR_SYSTEM
    opponent_side = "BEAR" if side == "bull" else "BULL"
    research_summary = _build_research_summary(research_reports)

    prompt = REBUTTAL_PROMPT.format(
        ticker=ticker.upper(), side=side.upper(),
        opponent_side=opponent_side,
        research_summary=research_summary,
        opponent_argument=opponent_argument[:400],
    )

    content = llm_call(prompt, system=system, config=config, token_callback=token_callback)
    return DebateArgument(side=side, phase="rebuttal", content=content)


def debate_closing(ticker: str, side: str,
                   config: Optional[LLMConfig] = None,
                   token_callback=None) -> DebateArgument:
    """Generate closing statement."""
    if config is None:
        config = default_config(label=f"Debate {side.upper()}", max_tokens=80)

    system = BULL_SYSTEM if side == "bull" else BEAR_SYSTEM

    prompt = CLOSING_PROMPT.format(ticker=ticker.upper(), side=side.upper())
    content = llm_call(prompt, system=system, config=config, token_callback=token_callback)
    return DebateArgument(side=side, phase="closing", content=content)
