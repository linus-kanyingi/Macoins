"""
agents/debate/debater.py — Financial stance agents: BUY (Bullish) / SELL (Bearish) / HOLD (Risk-aware).
Evidence packet from FinancialScenario is injected into every prompt.
Adapted from findebate/agents/debater.py to import from agents.debate.ollama_client and core.config.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Callable
from agents.debate.ollama_client import chat
from core.config import settings

MAX_TOKENS_DEBATER = settings.MAX_TOKENS_DEBATER

VALID_SIDES = {"BUY", "SELL", "HOLD"}


@dataclass
class DebateTurn:
    speaker: str
    turn_type: str
    round_num: int
    content: str


class Debater:

    def __init__(self, side: str, scenario):
        assert side in VALID_SIDES, f"side must be one of {VALID_SIDES}"
        self.side = side
        self.scenario = scenario
        self.topic = scenario.to_debate_topic()
        self._evidence = scenario.evidence_packet()
        self.history: List[DebateTurn] = []

    def _system(self) -> str:
        if self.side == "BUY":
            return (
                "You are ANALYST BULL — a senior equity analyst who believes this asset "
                "should be BOUGHT. You argue ONLY for BUY using data from the evidence packet. "
                "Never recommend SELL or HOLD. Cite specific numbers. Sound confident and professional."
            )
        elif self.side == "SELL":
            return (
                "You are ANALYST BEAR — a senior equity analyst who believes this asset "
                "should be SOLD or avoided. You argue ONLY for SELL using data from the evidence packet. "
                "Never recommend BUY or HOLD. Cite specific numbers. Sound cautious and risk-aware."
            )
        else:  # HOLD
            return (
                "You are ANALYST RISK — a risk management specialist. You believe "
                "the correct stance is HOLD due to mixed or uncertain signals. "
                "Highlight risks and uncertainty. Cite specific numbers. Never push BUY or SELL."
            )

    def _build_prompt(self, turn_type: str, round_num: int, opponent_last: Optional[str]) -> str:
        evidence_block = (
            f"\n{self._evidence}\n"
            "IMPORTANT: Base ALL arguments on the evidence above. "
            "Do NOT invent prices, percentages, or news not in the evidence.\n"
        )

        role_map = {
            "BUY": (
                f'YOUR ROLE: Argue for BUY — "{self.topic}"',
                "Make the strongest case for buying this asset NOW using the evidence.",
            ),
            "SELL": (
                f'YOUR ROLE: Argue for SELL — "{self.topic}"',
                "Make the strongest case for selling / avoiding this asset using the evidence.",
            ),
            "HOLD": (
                f'YOUR ROLE: Argue for HOLD — "{self.topic}"',
                "Explain why risk/reward does NOT clearly favour buying or selling right now.",
            ),
        }
        role_line, stance_line = role_map[self.side]
        lines = [evidence_block, role_line, stance_line, ""]

        if turn_type == "opening":
            lines += [
                "TASK — OPENING ARGUMENT:",
                "Give 2 sharp, evidence-backed arguments for YOUR stance.",
                "Reference at least ONE specific number from the evidence packet.",
                "Max 120 words. Do NOT argue the other side.",
            ]
        elif turn_type == "rebuttal":
            opp = (opponent_last or "")[:400]
            lines += [
                "OPPONENT JUST SAID:", opp, "",
                f"TASK — REBUTTAL (Round {round_num}):",
                "Step 1: Counter ONE specific point the opponent made.",
                "Step 2: Reinforce your strongest evidence-backed argument.",
                "Max 120 words. Stay firmly on YOUR side.",
            ]
        elif turn_type == "risk":
            combined = (opponent_last or "")[:600]
            lines += [
                "BOTH SIDES HAVE ARGUED:", combined, "",
                "TASK — RISK ANALYSIS:",
                "Identify the top 2 risks making this decision uncertain.",
                "For each: name it, cite the evidence, state if it leans BUY or SELL.",
                "Conclude with your HOLD recommendation. Max 120 words.",
            ]
        elif turn_type == "closing":
            lines += [
                "TASK — CLOSING RECOMMENDATION:",
                f"State your final recommendation: {self.side}.",
                "Give ONE compelling evidence-backed reason. Max 40 words.",
                f"End with: 'My recommendation: {self.side}.'",
            ]
        return "\n".join(lines)

    def speak(self, turn_type: str, round_num: int = 0,
              opponent_last: Optional[str] = None,
              token_callback: Optional[Callable] = None) -> DebateTurn:
        prompt = self._build_prompt(turn_type, round_num, opponent_last)
        max_tok = {"opening": 150, "rebuttal": 150, "risk": 150, "closing": 55}.get(
            turn_type, MAX_TOKENS_DEBATER
        )
        response = chat(
            prompt, system=self._system(), max_tokens=max_tok,
            stream_print=True, token_callback=token_callback,
        )
        if not response.strip():
            response = f"[{self.side} — argument generation failed, please retry.]"
        turn = DebateTurn(
            speaker=self.side, turn_type=turn_type,
            round_num=round_num, content=response,
        )
        self.history.append(turn)
        return turn
