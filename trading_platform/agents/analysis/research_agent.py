"""
agents/analysis/research_agent.py — Dynamically spawned to research a single factor.

One instance is created per factor identified by the Factor Identifier.
Each produces a concise research report with findings and impact assessment.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from agents.llm_router import llm_call, LLMConfig, default_config


@dataclass
class ResearchReport:
    factor_name: str
    findings: str
    impact: str          # bullish / bearish / neutral
    confidence: str      # high / medium / low
    summary: str         # 1-sentence summary

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "findings": self.findings,
            "impact": self.impact,
            "confidence": self.confidence,
            "summary": self.summary,
        }


SYSTEM_PROMPT = (
    "You are a specialized equity research analyst. You have been assigned ONE specific "
    "factor to research for a stock. You produce concise, evidence-based research reports. "
    "You assess whether your factor is bullish, bearish, or neutral for the stock. "
    "Be specific, cite data when available, and state your confidence level honestly."
)

RESEARCH_PROMPT = """You are researching {ticker} with a focus on this specific factor:

FACTOR: {factor_name}
DESCRIPTION: {factor_description}
RESEARCH QUESTION: {research_prompt}

AVAILABLE MARKET DATA:
{market_data}

Write a research report on this factor. Include:
1. KEY FINDINGS: What you found about this factor (2-3 bullet points, be specific)
2. IMPACT: Is this factor BULLISH, BEARISH, or NEUTRAL for {ticker}? Why?
3. CONFIDENCE: Rate your confidence as HIGH, MEDIUM, or LOW
4. SUMMARY: One sentence summarizing your conclusion

Format your response exactly like this:
FINDINGS:
- [finding 1]
- [finding 2]
- [finding 3]

IMPACT: [BULLISH/BEARISH/NEUTRAL] — [brief explanation]

CONFIDENCE: [HIGH/MEDIUM/LOW]

SUMMARY: [one sentence]
"""


def research_factor(ticker: str, factor: dict, market_data: str = "",
                    config: Optional[LLMConfig] = None,
                    token_callback=None) -> ResearchReport:
    """
    Research a single factor for a stock.
    
    Args:
        ticker: Stock ticker
        factor: Dict with factor_name, description, research_prompt
        market_data: Pre-built evidence packet
        config: Optional LLM config override
        token_callback: Optional callback for streaming tokens
    
    Returns: ResearchReport
    """
    if config is None:
        config = default_config(
            label=f"Research: {factor.get('factor_name', 'Unknown')}",
            max_tokens=400,
        )

    prompt = RESEARCH_PROMPT.format(
        ticker=ticker.upper(),
        factor_name=factor.get("factor_name", "Unknown"),
        factor_description=factor.get("description", ""),
        research_prompt=factor.get("research_prompt", ""),
        market_data=market_data or "No additional market data available.",
    )

    raw = llm_call(prompt, system=SYSTEM_PROMPT, config=config, token_callback=token_callback)

    # Parse response
    return _parse_report(raw, factor.get("factor_name", "Unknown"))


def _parse_report(raw: str, factor_name: str) -> ResearchReport:
    """Parse structured research report from LLM output."""
    findings = ""
    impact = "neutral"
    confidence = "medium"
    summary = ""

    lines = raw.strip().split("\n")
    current_section = None

    findings_lines = []
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()

        if upper.startswith("FINDINGS:"):
            current_section = "findings"
            rest = stripped[9:].strip()
            if rest:
                findings_lines.append(rest)
            continue
        elif upper.startswith("IMPACT:"):
            current_section = "impact"
            rest = stripped[7:].strip()
            if "BULLISH" in rest.upper():
                impact = "bullish"
            elif "BEARISH" in rest.upper():
                impact = "bearish"
            else:
                impact = "neutral"
            # Keep the explanation
            findings = "\n".join(findings_lines)
            continue
        elif upper.startswith("CONFIDENCE:"):
            current_section = "confidence"
            rest = stripped[11:].strip().upper()
            if "HIGH" in rest:
                confidence = "high"
            elif "LOW" in rest:
                confidence = "low"
            else:
                confidence = "medium"
            continue
        elif upper.startswith("SUMMARY:"):
            current_section = "summary"
            summary = stripped[8:].strip()
            continue

        if current_section == "findings" and stripped:
            findings_lines.append(stripped)
        elif current_section == "summary" and stripped and not summary:
            summary = stripped

    if findings_lines and not findings:
        findings = "\n".join(findings_lines)

    # Fallback if parsing failed
    if not findings:
        findings = raw[:500]
    if not summary:
        summary = findings[:100] + "..." if len(findings) > 100 else findings

    return ResearchReport(
        factor_name=factor_name,
        findings=findings,
        impact=impact,
        confidence=confidence,
        summary=summary,
    )
