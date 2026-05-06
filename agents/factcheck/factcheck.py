"""
agents/factcheck/factcheck.py — Financial claim extractor + verifier.
Adapted from findebate — imports updated to use new package paths.
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass
from typing import List, Optional
from core.config import settings

FACTCHECK_MODEL = settings.FACTCHECK_MODEL
MAX_CLAIMS_TO_CHECK = settings.MAX_CLAIMS_TO_CHECK


@dataclass
class FactCheckResult:
    claim: str
    speaker: str
    verdict: str
    explanation: str
    confidence: float
    penalty: float = 0.0

    def __post_init__(self):
        self.penalty = _penalty_for(self.verdict, self.confidence)

    def to_dict(self) -> dict:
        return {
            "claim":       self.claim,
            "speaker":     self.speaker,
            "verdict":     self.verdict,
            "explanation": self.explanation,
            "confidence":  self.confidence,
            "penalty":     self.penalty,
        }


def _penalty_for(verdict: str, confidence: float) -> float:
    base = {
        "supported":           0.0,
        "partially_supported": 0.3,
        "uncertain":           0.1,
        "unsupported":         0.7,
        "contradicted":        1.0,
    }.get(verdict, 0.2)
    return round(base * confidence, 3)


_EXTRACT_SYSTEM = (
    "You are a financial fact-checking assistant. "
    "Extract specific, verifiable factual claims from financial analyst arguments. "
    "Focus on: price levels, percentage changes, financial ratios, earnings figures, "
    "macro indicators, analyst ratings, and quantitative statements. "
    "Ignore opinions, predictions, and qualitative judgements."
)

_EXTRACT_TMPL = """Extract up to {max_c} specific, verifiable financial claims from this analyst argument.

ARGUMENT:
{text}

Return ONLY a JSON array of claim strings. Example:
["The RSI is at 36.2", "Apple missed earnings by 3%", "VIX is above 20"]

Return [] if there are no verifiable factual claims.
JSON array:"""


def extract_claims(text: str, max_claims: int = MAX_CLAIMS_TO_CHECK,
                   speaker: str = "unknown") -> List[str]:
    from agents.debate.ollama_client import chat
    prompt = _EXTRACT_TMPL.format(text=text[:800], max_c=max_claims)
    try:
        raw = chat(prompt, system=_EXTRACT_SYSTEM, model=FACTCHECK_MODEL,
                   max_tokens=200, stream_print=False)
        raw = re.sub(r"```json|```", "", raw).strip()
        claims = json.loads(raw)
        if isinstance(claims, list):
            return [str(c).strip() for c in claims if str(c).strip()][:max_claims]
    except Exception:
        pass
    return []


_VERIFY_SYSTEM = (
    "You are a financial fact-checker. Evaluate whether a financial claim is "
    "consistent with the provided evidence packet. "
    "You can ONLY verify against the evidence packet — do not use outside knowledge. "
    "Be strict: if the claim cannot be verified from the evidence, say 'uncertain'."
)

_VERIFY_TMPL = """Evaluate this financial claim against the evidence packet.

CLAIM: {claim}

EVIDENCE PACKET:
{evidence}

Respond ONLY with valid JSON in this exact format:
{{
  "verdict": "supported" | "partially_supported" | "unsupported" | "contradicted" | "uncertain",
  "explanation": "one sentence explaining your verdict",
  "confidence": 0.0-1.0
}}

JSON:"""


def verify_claim(claim: str, speaker: str = "unknown", evidence: str = "") -> FactCheckResult:
    from agents.debate.ollama_client import chat
    prompt = _VERIFY_TMPL.format(
        claim=claim,
        evidence=evidence[:1200] if evidence else "No evidence packet provided."
    )
    try:
        raw = chat(prompt, system=_VERIFY_SYSTEM, model=FACTCHECK_MODEL,
                   max_tokens=150, stream_print=False)
        raw = re.sub(r"```json|```", "", raw).strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            obj = json.loads(match.group())
            verdict     = obj.get("verdict", "uncertain")
            explanation = obj.get("explanation", "Could not evaluate.")
            confidence  = float(obj.get("confidence", 0.5))
            confidence  = max(0.0, min(1.0, confidence))
            return FactCheckResult(claim=claim, speaker=speaker, verdict=verdict,
                                   explanation=explanation, confidence=confidence)
    except Exception:
        pass
    return FactCheckResult(claim=claim, speaker=speaker, verdict="uncertain",
                           explanation="Fact-check failed — could not parse model response.",
                           confidence=0.3)


def run_factcheck(transcript_text: str, evidence: str = "",
                  max_claims: int = MAX_CLAIMS_TO_CHECK) -> List[FactCheckResult]:
    claims  = extract_claims(transcript_text, max_claims=max_claims)
    results = [verify_claim(c, evidence=evidence) for c in claims]
    return results


def summarise_penalties(results: List[FactCheckResult]) -> dict:
    out: dict = {}
    for r in results:
        spk = r.speaker
        if spk not in out:
            out[spk] = {"count": 0, "penalty_total": 0.0, "verdicts": []}
        out[spk]["count"]         += 1
        out[spk]["penalty_total"] += r.penalty
        out[spk]["verdicts"].append(r.verdict)
    return out


class FactChecker:
    """Convenience class wrapper for pipeline use."""
    def check(self, transcript, scenario) -> List[FactCheckResult]:
        evidence = ""
        if hasattr(scenario, 'evidence_packet'):
            evidence = scenario.evidence_packet()
        transcript_text = ""
        if hasattr(transcript, 'turns'):
            transcript_text = "\n".join(
                f"[{t.speaker}] {t.content}" if hasattr(t, 'speaker') else str(t)
                for t in transcript.turns
            )
        elif isinstance(transcript, str):
            transcript_text = transcript
        return run_factcheck(transcript_text, evidence=evidence)
