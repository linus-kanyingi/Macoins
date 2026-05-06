"""
agents/judges/base_judge.py — Shared rubric, prompt builder, and JSON parser for financial judging.
Adapted from findebate/judges/base_judge.py to import from core.config.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Optional

# Financial judging criteria (6 criteria x 10 pts each = 60 max per side)
CRITERIA = [
    "reasoning_quality",    # logical, structured financial reasoning
    "evidence_usage",       # cited specific data from evidence packet
    "factual_reliability",  # claims consistent with evidence
    "rebuttal_quality",     # effectively addressed opponent's points
    "risk_awareness",       # acknowledged downside/upside risks appropriately
    "decision_clarity",     # clear, well-justified BUY/SELL/HOLD recommendation
]

VALID_WINNERS = {"BUY", "SELL", "HOLD", "DRAW"}


@dataclass
class JudgeScore:
    judge_name: str
    buy_scores: dict = field(default_factory=dict)    # criterion -> score (1-10)
    sell_scores: dict = field(default_factory=dict)
    winner: str = "HOLD"                               # BUY | SELL | HOLD | DRAW
    reasoning: str = ""
    error: Optional[str] = None

    # Aliases so aggregator backward-compat code still works
    @property
    def pro_scores(self):
        return self.buy_scores

    @property
    def con_scores(self):
        return self.sell_scores

    def buy_total(self) -> float:
        return sum(self.buy_scores.values())

    def sell_total(self) -> float:
        return sum(self.sell_scores.values())

    def pro_total(self) -> float:
        return self.buy_total()

    def con_total(self) -> float:
        return self.sell_total()

    def to_dict(self) -> dict:
        return {
            "judge_name": self.judge_name,
            "buy_scores": self.buy_scores,
            "sell_scores": self.sell_scores,
            "buy_total": self.buy_total(),
            "sell_total": self.sell_total(),
            "winner": self.winner,
            "reasoning": self.reasoning,
            "error": self.error,
        }


# ── Prompt builder ─────────────────────────────────────────────────────────────

JUDGE_SYSTEM = (
    "You are an expert financial analysis evaluator. "
    "Your task is to judge the quality of financial arguments made by two analysts "
    "debating whether to BUY or SELL an asset. "
    "You evaluate reasoning quality, evidence usage, and decision clarity — "
    "NOT whether you personally agree with the recommendation. "
    "Be objective, consistent, and strict. "
    "Respond ONLY with valid JSON — no preamble, no markdown."
)

_RUBRIC = "\n".join(
    f"  - {c}: score 1-10 for both BUY and SELL analyst" for c in CRITERIA
)

JUDGE_PROMPT_TMPL = """You are judging a financial debate between a BUY analyst and a SELL analyst.

TRANSCRIPT:
{transcript}

{fc_section}

SCORING RUBRIC (score each criterion 1-10 for both BUY and SELL analyst):
{rubric}

Respond ONLY with this exact JSON structure:
{{
  "buy_scores":  {{{score_keys}}},
  "sell_scores": {{{score_keys}}},
  "winner": "BUY" or "SELL" or "HOLD" or "DRAW",
  "reasoning": "2-3 sentence explanation of your decision"
}}

Rules:
- winner = "HOLD" if the debate is inconclusive or evidence is too mixed to favour either side
- winner = "DRAW" only if scores are truly equal
- Base scores ONLY on argument quality, not your own market views
- If fact-check results are provided, penalise the analyst who made false claims

JSON:"""


def build_judge_prompt(transcript_text: str,
                       factcheck_summary: Optional[str] = None) -> str:
    score_keys = ", ".join(f'"{c}": <score>' for c in CRITERIA)
    fc_section = ""
    if factcheck_summary:
        fc_section = f"FACT-CHECK RESULTS (use to penalise false claims):\n{factcheck_summary}\n"

    # Handle Transcript object or plain string
    if hasattr(transcript_text, "full_text"):
        text = transcript_text.full_text()
    elif hasattr(transcript_text, "to_dict"):
        d = transcript_text.to_dict()
        lines = [f"FINANCIAL DEBATE: {d.get('topic', '')}"]
        for t in d.get("turns", []):
            lines.append(f"\n[{t['speaker']} - {t['turn_type'].upper()}]")
            lines.append(t["content"])
        text = "\n".join(lines)
    else:
        text = str(transcript_text)

    return JUDGE_PROMPT_TMPL.format(
        transcript=text[:3000],
        fc_section=fc_section,
        rubric=_RUBRIC,
        score_keys=score_keys,
    )


# ── Response parser ────────────────────────────────────────────────────────────

def parse_judge_response(raw: str, judge_name: str) -> JudgeScore:
    raw = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return _neutral_score(judge_name, error="No JSON found in response")
    try:
        obj = json.loads(match.group())
        buy_scores = {c: _clamp(obj.get("buy_scores", {}).get(c, 5)) for c in CRITERIA}
        sell_scores = {c: _clamp(obj.get("sell_scores", {}).get(c, 5)) for c in CRITERIA}
        winner = str(obj.get("winner", "HOLD")).upper().strip()
        if winner not in VALID_WINNERS:
            winner = "HOLD"
        return JudgeScore(
            judge_name=judge_name,
            buy_scores=buy_scores,
            sell_scores=sell_scores,
            winner=winner,
            reasoning=str(obj.get("reasoning", ""))[:500],
        )
    except Exception as e:
        return _neutral_score(judge_name, error=f"Parse error: {e}")


def _clamp(v) -> int:
    try:
        return max(1, min(10, int(v)))
    except Exception:
        return 5


def _neutral_score(judge_name: str, error: str = "") -> JudgeScore:
    neutral = {c: 5 for c in CRITERIA}
    return JudgeScore(
        judge_name=judge_name,
        buy_scores=neutral.copy(),
        sell_scores=neutral.copy(),
        winner="HOLD",
        reasoning="Judge returned neutral score due to error.",
        error=error,
    )
