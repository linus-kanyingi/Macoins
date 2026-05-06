"""
agents/aggregator/aggregator.py — Financial decision aggregator.
Adapted from findebate — imports updated to use new package paths.
"""
from __future__ import annotations
import statistics
from typing import List, Optional
from agents.judges.base_judge import JudgeScore, CRITERIA
from agents.factcheck.factcheck import FactCheckResult, summarise_penalties


def map_winner_to_decision(winner: str) -> str:
    w = winner.upper().strip()
    if w == "BUY":  return "BUY"
    if w == "SELL": return "SELL"
    return "HOLD"


class AggregatedVerdict:

    def __init__(self, topic: str, judge_scores: List[JudgeScore],
                 factcheck_results: Optional[List[FactCheckResult]] = None,
                 asset_ticker: str = ""):
        self.topic        = topic
        self.judge_scores = judge_scores
        self.factcheck    = factcheck_results or []
        self.asset_ticker = asset_ticker
        self._compute()

    def _compute(self):
        valid = [s for s in self.judge_scores if not s.error or s.buy_total() > 0]
        if not valid: valid = self.judge_scores

        buy_totals  = [s.buy_total()  for s in valid]
        sell_totals = [s.sell_total() for s in valid]

        self.avg_buy_raw  = _mean(buy_totals)
        self.avg_sell_raw = _mean(sell_totals)
        self.avg_pro_raw  = self.avg_buy_raw
        self.avg_con_raw  = self.avg_sell_raw

        self.per_criterion = {}
        for c in CRITERIA:
            buy_vals  = [s.buy_scores.get(c, 5)  for s in valid]
            sell_vals = [s.sell_scores.get(c, 5) for s in valid]
            self.per_criterion[c] = {
                "BUY_avg":  round(_mean(buy_vals),  2),
                "SELL_avg": round(_mean(sell_vals), 2),
            }

        decisions = [map_winner_to_decision(s.winner) for s in valid]
        self.vote_buy  = decisions.count("BUY")
        self.vote_sell = decisions.count("SELL")
        self.vote_hold = decisions.count("HOLD")

        if self.vote_buy > self.vote_sell and self.vote_buy > self.vote_hold:
            self.majority_decision = "BUY"
        elif self.vote_sell > self.vote_buy and self.vote_sell > self.vote_hold:
            self.majority_decision = "SELL"
        else:
            self.majority_decision = "HOLD"
        self.majority_winner = self.majority_decision

        self.buy_variance  = round(_variance(buy_totals),  2)
        self.sell_variance = round(_variance(sell_totals), 2)
        self.pro_variance  = self.buy_variance
        self.con_variance  = self.sell_variance
        self.disagreement_level = _disagreement_label(self.buy_variance, self.sell_variance)

        self.factcheck_penalties = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        if self.factcheck:
            pen = summarise_penalties(self.factcheck)
            for spk in ("BUY", "SELL", "HOLD"):
                self.factcheck_penalties[spk] = round(
                    pen.get(spk, {}).get("penalty_total", 0.0), 3
                )

        PENALTY_SCALE  = 3.0
        self.adj_buy   = round(self.avg_buy_raw  - self.factcheck_penalties["BUY"]  * PENALTY_SCALE, 2)
        self.adj_sell  = round(self.avg_sell_raw - self.factcheck_penalties["SELL"] * PENALTY_SCALE, 2)
        self.adj_pro   = self.adj_buy
        self.adj_con   = self.adj_sell

        score_gap  = abs(self.adj_buy - self.adj_sell)
        high_var   = (self.buy_variance + self.sell_variance) / 2 > 8
        split_vote = (self.vote_buy > 0 and self.vote_sell > 0
                      and abs(self.vote_buy - self.vote_sell) <= 1)

        if score_gap < 2.0 or high_var or split_vote:
            self.final_decision = "HOLD"
            self.hold_reason    = _hold_reason(score_gap, high_var, split_vote)
        elif self.adj_buy > self.adj_sell:
            self.final_decision = "BUY"
            self.hold_reason    = ""
        else:
            self.final_decision = "SELL"
            self.hold_reason    = ""
        self.final_winner = self.final_decision

        self.confidence_score = _confidence_score(
            score_gap, self.buy_variance, self.sell_variance,
            self.vote_buy, self.vote_sell, self.vote_hold,
        )
        self.confidence_label = _confidence_label(self.confidence_score)
        self.uncertainty_flag = self.confidence_score < 0.45

    def to_dict(self) -> dict:
        return {
            "asset_ticker":        self.asset_ticker,
            "topic":               self.topic,
            "final_decision":      self.final_decision,
            "final_winner":        self.final_decision,
            "confidence_label":    self.confidence_label,
            "confidence_score":    round(self.confidence_score, 3),
            "uncertainty_flag":    self.uncertainty_flag,
            "hold_reason":         self.hold_reason,
            "majority_winner":     self.majority_decision,
            "votes":               {"BUY": self.vote_buy, "SELL": self.vote_sell, "HOLD": self.vote_hold},
            "avg_scores_raw":      {"BUY": round(self.avg_buy_raw, 2), "SELL": round(self.avg_sell_raw, 2)},
            "adj_scores":          {"BUY": self.adj_buy, "SELL": self.adj_sell},
            "factcheck_penalties": {"BUY": self.factcheck_penalties["BUY"], "SELL": self.factcheck_penalties["SELL"]},
            "per_criterion":       self.per_criterion,
            "judge_disagreement":  self.disagreement_level,
            "judge_variance":      {"BUY": self.buy_variance, "SELL": self.sell_variance},
            "individual_judges":   [s.to_dict() for s in self.judge_scores],
            "factcheck_results":   [r.to_dict() for r in self.factcheck],
        }


def aggregate_results(transcript, judge_scores, factcheck_results, scenario):
    """Convenience wrapper called by analysis_pipeline.
    When judge_scores is empty (skip_judges=True), synthesise pseudo-scores
    from the debate transcript so the verdict is still meaningful.
    """
    topic  = scenario.to_debate_topic() if hasattr(scenario, 'to_debate_topic') else str(scenario)
    ticker = getattr(scenario, 'asset_ticker', '')

    # If no real judge scores, build one synthetic score from debate closings
    if not judge_scores:
        judge_scores = _scores_from_transcript(transcript)

    return AggregatedVerdict(
        topic=topic,
        judge_scores=judge_scores,
        factcheck_results=factcheck_results,
        asset_ticker=ticker,
    )


def _scores_from_transcript(transcript) -> list:
    """Derive a single synthetic JudgeScore from the debate transcript
    when the judge panel was skipped. Counts closing-argument word counts
    and argument strength as a proxy for scoring."""
    from agents.judges.base_judge import JudgeScore, CRITERIA

    turns = []
    if hasattr(transcript, 'turns'):
        turns = transcript.turns
    elif isinstance(transcript, dict):
        turns = transcript.get('turns', [])

    # Collect content per side
    buy_text  = " ".join(getattr(t, 'content', '') for t in turns
                         if getattr(t, 'speaker', '') == 'BUY')
    sell_text = " ".join(getattr(t, 'content', '') for t in turns
                         if getattr(t, 'speaker', '') == 'SELL')

    # Word count as proxy: more words = stronger argument
    buy_words  = len(buy_text.split())
    sell_words = len(sell_text.split())
    total      = max(buy_words + sell_words, 1)

    # Scale to 1-10 (both sides get base 5; winner gets proportional bonus)
    buy_base  = 5 + round((buy_words  / total - 0.5) * 6)
    sell_base = 5 + round((sell_words / total - 0.5) * 6)
    buy_base  = max(1, min(10, buy_base))
    sell_base = max(1, min(10, sell_base))

    buy_scores  = {c: buy_base  for c in CRITERIA}
    sell_scores = {c: sell_base for c in CRITERIA}

    # Determine winner from closing statements
    buy_closing  = " ".join(getattr(t, 'content', '') for t in turns
                             if getattr(t, 'speaker', '') == 'BUY'
                             and getattr(t, 'turn_type', '') == 'closing')
    sell_closing = " ".join(getattr(t, 'content', '') for t in turns
                             if getattr(t, 'speaker', '') == 'SELL'
                             and getattr(t, 'turn_type', '') == 'closing')

    if len(buy_closing) > len(sell_closing) * 1.2:
        winner = "BUY"
    elif len(sell_closing) > len(buy_closing) * 1.2:
        winner = "SELL"
    else:
        winner = "HOLD"

    return [JudgeScore(
        judge_name="debate_synthesis",
        buy_scores=buy_scores,
        sell_scores=sell_scores,
        winner=winner,
        reasoning="Synthesised from debate transcript (judges skipped).",
    )]


def _mean(vals):     return statistics.mean(vals) if vals else 0.0
def _variance(vals): return statistics.variance(vals) if len(vals) >= 2 else 0.0

def _disagreement_label(v1, v2):
    avg = (v1 + v2) / 2
    if avg < 3:  return "Low (judges largely agree)"
    if avg < 10: return "Moderate"
    return "High (judges strongly disagree)"

def _hold_reason(gap, high_var, split):
    r = []
    if gap < 2.0:  r.append(f"BUY/SELL scores within {gap:.1f} pts")
    if high_var:   r.append("high judge variance")
    if split:      r.append("split judge vote")
    return "; ".join(r) or "mixed signals"

def _confidence_score(gap, vb, vs, buy_v, sell_v, hold_v):
    total = max(buy_v + sell_v + hold_v, 1)
    best  = max(buy_v, sell_v, hold_v)
    raw   = (best / total * 0.5) + (min(gap / 10, 1.0) * 0.5) - min((vb + vs) / 2 / 20, 0.5)
    return max(0.0, min(1.0, raw))

def _confidence_label(score):
    if score >= 0.75: return "HIGH"
    if score >= 0.55: return "MODERATE"
    if score >= 0.35: return "LOW"
    return "UNCERTAIN"
