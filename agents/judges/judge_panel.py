"""
agents/judges/judge_panel.py — 5-judge ensemble.
Adapted from findebate — imports updated to use new package paths.
"""
from __future__ import annotations
import concurrent.futures
from typing import List, Optional, Callable
from agents.judges.base_judge import JudgeScore, build_judge_prompt, parse_judge_response, _neutral_score
from core.config import settings

OPENAI_API_KEY    = settings.OPENAI_API_KEY
GROK_API_KEY      = settings.GROK_API_KEY
GEMINI_API_KEY    = settings.GEMINI_API_KEY
DEEPSEEK_API_KEY  = settings.DEEPSEEK_API_KEY
ANTHROPIC_API_KEY = settings.ANTHROPIC_API_KEY
JUDGE_MODELS      = settings.JUDGE_MODELS
MAX_TOKENS_JUDGE  = settings.MAX_TOKENS_JUDGE
JUDGE_TEMPERATURE = settings.JUDGE_TEMPERATURE

PLACEHOLDERS = {"YOUR_OPENAI_KEY_HERE", "YOUR_GROK_KEY_HERE", "YOUR_DEEPSEEK_KEY_HERE",
                "YOUR_GEMINI_KEY_HERE", "YOUR_ANTHROPIC_KEY_HERE", "", None}

def _has_key(key) -> bool:
    return key not in PLACEHOLDERS


def _run_chatgpt(prompt: str) -> JudgeScore:
    name = "ChatGPT"
    if not _has_key(OPENAI_API_KEY):
        return _neutral_score(name, error="No API key")
    try:
        from openai import OpenAI
        client   = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=JUDGE_MODELS["chatgpt"], messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS_JUDGE, temperature=JUDGE_TEMPERATURE,
        )
        return parse_judge_response(response.choices[0].message.content or "", name)
    except Exception as e:
        return _neutral_score(name, error=str(e))


def _run_grok(prompt: str) -> JudgeScore:
    name = "Grok"
    if not _has_key(GROK_API_KEY):
        return _neutral_score(name, error="No API key")
    try:
        from openai import OpenAI
        client   = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
        response = client.chat.completions.create(
            model=JUDGE_MODELS["grok"], messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS_JUDGE, temperature=JUDGE_TEMPERATURE,
        )
        return parse_judge_response(response.choices[0].message.content or "", name)
    except Exception as e:
        return _neutral_score(name, error=str(e))


def _run_deepseek(prompt: str) -> JudgeScore:
    name = "DeepSeek"
    if not _has_key(DEEPSEEK_API_KEY):
        return _neutral_score(name, error="No API key")
    try:
        from openai import OpenAI
        client   = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
        response = client.chat.completions.create(
            model=JUDGE_MODELS["deepseek"], messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS_JUDGE, temperature=JUDGE_TEMPERATURE,
        )
        return parse_judge_response(response.choices[0].message.content or "", name)
    except Exception as e:
        return _neutral_score(name, error=str(e))


def _run_gemini(prompt: str) -> JudgeScore:
    name = "Gemini"
    if not _has_key(GEMINI_API_KEY):
        return _neutral_score(name, error="No API key")
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model    = genai.GenerativeModel(JUDGE_MODELS["gemini"])
        response = model.generate_content(prompt)
        return parse_judge_response(response.text or "", name)
    except Exception as e:
        return _neutral_score(name, error=str(e))


def _run_claude(prompt: str) -> JudgeScore:
    name = "Claude"
    if not _has_key(ANTHROPIC_API_KEY):
        return _neutral_score(name, error="No API key")
    try:
        import anthropic
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=JUDGE_MODELS["claude"], max_tokens=MAX_TOKENS_JUDGE,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text if response.content else ""
        return parse_judge_response(raw, name)
    except Exception as e:
        return _neutral_score(name, error=str(e))


_JUDGES = [
    ("ChatGPT",  _run_chatgpt),
    ("Grok",     _run_grok),
    ("DeepSeek", _run_deepseek),
    ("Gemini",   _run_gemini),
    ("Claude",   _run_claude),
]


def run_judge_ensemble(transcript_text: str,
                       factcheck_summary: Optional[str] = None,
                       progress_callback: Optional[Callable] = None) -> List[JudgeScore]:
    prompt = build_judge_prompt(transcript_text, factcheck_summary)
    scores: List[JudgeScore] = []

    def run_one(name_fn):
        name, fn = name_fn
        score  = fn(prompt)
        return score

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(run_one, nf): nf[0] for nf in _JUDGES}
        for future in concurrent.futures.as_completed(futures):
            try:
                scores.append(future.result())
            except Exception as e:
                name = futures[future]
                scores.append(_neutral_score(name, error=str(e)))

    order = {n: i for i, (n, _) in enumerate(_JUDGES)}
    scores.sort(key=lambda s: order.get(s.judge_name, 99))
    return scores
