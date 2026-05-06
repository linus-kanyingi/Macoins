"""
agents/debate/orchestrator.py — Financial debate orchestrator.
Flow: opening → rebuttals → risk analysis (HOLD only) → closing
Adapted from findebate/agents/orchestrator.py.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import List, Callable, Optional
from agents.debate.debater import Debater, DebateTurn
from core.config import settings

NUM_ROUNDS = settings.NUM_ROUNDS

SEP = "-" * 60


@dataclass
class Transcript:
    topic: str
    turns: List[DebateTurn] = field(default_factory=list)

    def full_text(self) -> str:
        lines = [f"FINANCIAL DEBATE: {self.topic}\n{'=' * 60}"]
        for t in self.turns:
            lines.append(
                f"\n[{t.speaker} - {t.turn_type.upper()}"
                + (f" Round {t.round_num}" if t.round_num else "") + "]"
            )
            lines.append(t.content)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "turns": [
                {
                    "speaker": t.speaker,
                    "turn_type": t.turn_type,
                    "round_num": t.round_num,
                    "content": t.content,
                }
                for t in self.turns
            ],
        }


def _hdr(speaker: str, turn_type: str, round_num: int = 0):
    icons = {"BUY": "[BUY]", "SELL": "[SELL]", "HOLD": "[HOLD]"}
    icon = icons.get(speaker, "[?]")
    rnd = f" · Round {round_num}" if round_num else ""
    print(f"\n{SEP}\n{icon}  {speaker}  —  {turn_type.upper()}{rnd}\n{SEP}")


class DebateOrchestrator:

    def __init__(self, scenario,
                 num_rounds: int = NUM_ROUNDS,
                 include_hold: bool = False,
                 include_hold_agent: bool = False,
                 progress_callback: Optional[Callable] = None,
                 turn_callback: Optional[Callable] = None,
                 token_callback: Optional[Callable] = None,
                 fc_turn_callback: Optional[Callable] = None):
        self.scenario = scenario
        self.topic = scenario.to_debate_topic()
        self.rounds = num_rounds
        self.include_hold = include_hold or include_hold_agent
        self.callback = progress_callback
        self.turn_cb = turn_callback
        self.token_cb = token_callback
        self.fc_cb = fc_turn_callback
        self.buy_agent = Debater("BUY", scenario)
        self.sell_agent = Debater("SELL", scenario)
        self.hold_agent = Debater("HOLD", scenario) if self.include_hold else None
        self._fc_threads: List[threading.Thread] = []

    def _log(self, msg: str):
        if self.callback:
            self.callback(msg)
        print(f"  {msg}")

    def _make_tc(self, speaker, turn_type, round_num):
        if not self.token_cb:
            return None
        ti = {"speaker": speaker, "turn_type": turn_type, "round_num": round_num}

        def tc(token, _ti=ti):
            self.token_cb(token, _ti)

        return tc

    def _speak(self, debater: Debater, turn_type: str,
               round_num: int = 0, opponent_last: Optional[str] = None) -> DebateTurn:
        _hdr(debater.side, turn_type, round_num)
        tc = self._make_tc(debater.side, turn_type, round_num)
        turn = debater.speak(
            turn_type, round_num=round_num,
            opponent_last=opponent_last, token_callback=tc,
        )
        if self.turn_cb:
            self.turn_cb({
                "speaker": turn.speaker,
                "turn_type": turn.turn_type,
                "round_num": turn.round_num,
                "content": turn.content,
            })
        if self.fc_cb:
            t = threading.Thread(
                target=self._run_fc,
                args=(turn.content, turn.speaker),
                daemon=True,
            )
            self._fc_threads.append(t)
            t.start()
        return turn

    def _run_fc(self, text: str, speaker: str):
        try:
            from agents.factcheck.factcheck import extract_claims, verify_claim
            claims = extract_claims(text, max_claims=2)
            for c in claims:
                result = verify_claim(c)
                self.fc_cb(result.to_dict())
        except Exception as e:
            print(f"  FC thread error: {e}")

    def run(self, turn_callback=None) -> Transcript:
        # Allow passing turn_callback at run time too
        if turn_callback is not None:
            self.turn_cb = turn_callback

        transcript = Transcript(topic=self.topic)

        # Openings
        self._log("BUY agent: Opening argument...")
        buy_open = self._speak(self.buy_agent, "opening")
        transcript.turns.append(buy_open)
        self.sell_agent.history.append(buy_open)

        self._log("SELL agent: Opening argument...")
        sell_open = self._speak(self.sell_agent, "opening")
        transcript.turns.append(sell_open)
        self.buy_agent.history.append(sell_open)

        if self.hold_agent:
            self._log("HOLD agent: Opening argument...")
            hold_open = self._speak(self.hold_agent, "opening")
            transcript.turns.append(hold_open)

        # Rebuttals
        last_sell = sell_open.content
        last_buy = buy_open.content

        for r in range(1, self.rounds + 1):
            self._log(f"BUY agent: Rebuttal round {r}...")
            buy_reb = self._speak(self.buy_agent, "rebuttal", r, last_sell)
            transcript.turns.append(buy_reb)
            self.sell_agent.history.append(buy_reb)
            last_buy = buy_reb.content

            self._log(f"SELL agent: Rebuttal round {r}...")
            sell_reb = self._speak(self.sell_agent, "rebuttal", r, last_buy)
            transcript.turns.append(sell_reb)
            self.buy_agent.history.append(sell_reb)
            last_sell = sell_reb.content

        # HOLD risk analysis
        if self.hold_agent:
            self._log("HOLD agent: Risk analysis...")
            combined = f"BUY argued: {last_buy[:300]}\n\nSELL argued: {last_sell[:300]}"
            hold_risk = self._speak(self.hold_agent, "risk", opponent_last=combined)
            transcript.turns.append(hold_risk)

        # Closings
        self._log("BUY agent: Closing recommendation...")
        transcript.turns.append(self._speak(self.buy_agent, "closing"))

        self._log("SELL agent: Closing recommendation...")
        transcript.turns.append(self._speak(self.sell_agent, "closing"))

        if self.hold_agent:
            self._log("HOLD agent: Closing recommendation...")
            transcript.turns.append(self._speak(self.hold_agent, "closing"))

        if self._fc_threads:
            print(f"  Waiting for {len(self._fc_threads)} fact-check threads...")
            for t in self._fc_threads:
                t.join(timeout=30)

        return transcript
