"""
agents/analysis/judge_agent.py — Final verdict judge(s).

Evaluates the debate transcript + research reports to produce a final
BUY/SELL/HOLD decision with confidence score and reasoning.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional
from agents.llm_router import llm_call, LLMConfig, default_config


@dataclass
class Verdict:
    decision: str           # BUY / SELL / HOLD
    confidence: float       # 0.0 - 1.0
    confidence_label: str   # HIGH / MODERATE / LOW / UNCERTAIN
    reasoning: str          # 2-3 sentence explanation
    bull_score: int         # 1-10
    bear_score: int         # 1-10

    def to_dict(self) -> dict:
        return {
            "final_decision": self.decision,
            "confidence_score": round(self.confidence, 3),
            "confidence_label": self.confidence_label,
            "reasoning": self.reasoning,
            "bull_score": self.bull_score,
            "bear_score": self.bear_score,
        }


SYSTEM_PROMPT = (
    "You are the CHIEF INVESTMENT OFFICER — the final decision maker. "
    "You evaluate research reports and debate arguments objectively. "
    "You judge argument QUALITY, not your personal views. "
    "You are decisive but honest about uncertainty. "
    "Respond ONLY with valid JSON — no markdown, no extra text."
)

JUDGE_PROMPT = """You are making the final investment decision for {ticker}.

RESEARCH REPORTS:
{research_summary}

DEBATE TRANSCRIPT:
{debate_transcript}

TASK — FINAL VERDICT:
1. Score BULL's argument quality (1-10)
2. Score BEAR's argument quality (1-10)
3. Decide: BUY, SELL, or HOLD
4. State your confidence (0.0 to 1.0)
5. Explain in 2-3 sentences

Rules:
- HOLD if arguments are too close or evidence is mixed
- BUY only if bull's case is clearly stronger AND evidence supports it
- SELL only if bear's case is clearly stronger AND evidence supports it
- Confidence below 0.4 should always be HOLD

Respond ONLY with this JSON:
{{
  "decision": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0-1.0,
  "reasoning": "2-3 sentence explanation",
  "bull_score": 1-10,
  "bear_score": 1-10
}}

JSON:"""


def judge_debate(ticker: str,
                 research_reports: list[dict],
                 debate_transcript: list[dict],
                 config: Optional[LLMConfig] = None,
                 token_callback=None) -> Verdict:
    """
    Judge the debate and produce a final verdict.

    Args:
        ticker: Stock ticker
        research_reports: List of research report dicts
        debate_transcript: List of debate argument dicts
        config: Optional LLM config (use a stronger model for judging)
        token_callback: Optional callback for streaming tokens
    """
    if config is None:
        config = default_config(label="Judge", max_tokens=300)

    # Format research
    research_lines = []
    for r in research_reports:
        impact = r.get("impact", "neutral").upper()
        research_lines.append(
            f"[{r['factor_name']}] Impact: {impact} | "
            f"Confidence: {r.get('confidence', 'medium')} | "
            f"{r.get('summary', '')}"
        )
    research_summary = "\n".join(research_lines)

    # Format debate
    debate_lines = []
    for arg in debate_transcript:
        side = arg.get("side", "unknown").upper()
        phase = arg.get("phase", "").upper()
        debate_lines.append(f"[{side} — {phase}]\n{arg.get('content', '')}")
    debate_text = "\n\n".join(debate_lines)

    prompt = JUDGE_PROMPT.format(
        ticker=ticker.upper(),
        research_summary=research_summary,
        debate_transcript=debate_text[:2000],
    )

    raw = llm_call(prompt, system=SYSTEM_PROMPT, config=config, token_callback=token_callback)
    return _parse_verdict(raw)


def _parse_verdict(raw: str) -> Verdict:
    """Parse judge's JSON verdict."""
    raw = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)

    if match:
        try:
            obj = json.loads(match.group())
            decision = str(obj.get("decision", "HOLD")).upper().strip()
            if decision not in ("BUY", "SELL", "HOLD"):
                decision = "HOLD"

            confidence = float(obj.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            # Force HOLD for low confidence
            if confidence < 0.4:
                decision = "HOLD"

            return Verdict(
                decision=decision,
                confidence=confidence,
                confidence_label=_confidence_label(confidence),
                reasoning=str(obj.get("reasoning", ""))[:500],
                bull_score=max(1, min(10, int(obj.get("bull_score", 5)))),
                bear_score=max(1, min(10, int(obj.get("bear_score", 5)))),
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Fallback
    return Verdict(
        decision="HOLD",
        confidence=0.3,
        confidence_label="UNCERTAIN",
        reasoning="Judge could not produce a clear verdict. Defaulting to HOLD.",
        bull_score=5,
        bear_score=5,
    )


def _confidence_label(score: float) -> str:
    if score >= 0.75: return "HIGH"
    if score >= 0.55: return "MODERATE"
    if score >= 0.35: return "LOW"
    return "UNCERTAIN"
