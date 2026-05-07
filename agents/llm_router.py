"""
agents/llm_router.py — Unified LLM dispatch for all agents.

Every agent in the system calls `llm_call()` with an optional LLMConfig.
The router dispatches to the correct provider (Ollama, OpenAI, Anthropic,
Gemini, DeepSeek, Grok) based on config.  Default: local Ollama model.
"""
from __future__ import annotations

import json
import re
import time
import threading
import requests
from dataclasses import dataclass, field
from typing import Optional, Callable

from core.config import settings

# ── Configuration ──────────────────────────────────────────────────────────────

PROVIDERS = ("ollama", "openai", "anthropic", "gemini", "deepseek", "grok")


@dataclass
class LLMConfig:
    """Per-agent LLM configuration."""
    provider: str = "ollama"            # ollama | openai | anthropic | gemini | deepseek | grok
    model: str = ""                     # empty → use default for provider
    temperature: float = 0.7
    max_tokens: int = 300
    label: str = ""                     # human-readable label, e.g. "Factor Identifier"
    think: bool = True                  # whether to use <|think|> internal reasoning

    def __post_init__(self):
        if not self.model:
            self.model = _default_model_for(self.provider)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "label": self.label,
            "think": self.think,
        }

    @staticmethod
    def from_dict(d: dict) -> "LLMConfig":
        return LLMConfig(
            provider=d.get("provider", "ollama"),
            model=d.get("model", ""),
            temperature=d.get("temperature", 0.7),
            max_tokens=d.get("max_tokens", 300),
            label=d.get("label", ""),
            think=d.get("think", True),
        )


def default_config(label: str = "", max_tokens: int = 300) -> LLMConfig:
    """Return the system-wide default config (local Ollama model)."""
    return LLMConfig(
        provider="ollama",
        model=settings.OLLAMA_MODEL,
        temperature=0.7,
        max_tokens=max_tokens,
        label=label,
    )


def _default_model_for(provider: str) -> str:
    return {
        "ollama":    settings.OLLAMA_MODEL,
        "openai":    "gpt-4o-mini",
        "anthropic": "claude-sonnet-4-20250514",
        "gemini":    "gemini-2.0-flash",
        "deepseek":  "deepseek-chat",
        "grok":      "grok-3-mini",
    }.get(provider, settings.OLLAMA_MODEL)


# ── Ollama helpers ─────────────────────────────────────────────────────────────

_ollama_lock = threading.Semaphore(1)
OLLAMA_TIMEOUT = 300
NUM_CTX = 4096

_ollama_model_cache: Optional[str] = None


def _resolve_ollama_model(requested: str) -> str:
    """Fall back to an available model if the requested one isn't pulled."""
    global _ollama_model_cache
    if _ollama_model_cache and _ollama_model_cache == requested:
        return requested
    try:
        r = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            local = {m["name"] for m in r.json().get("models", [])}
            if requested in local:
                _ollama_model_cache = requested
                return requested
            preferred = [
                "gemma4:e2b",
                "qwen3.5:0.8b", "qwen3:0.6b", "qwen3:1.7b",
                "qwen3.5:1.5b", "qwen2.5:3b", "llama3.2:1b",
                "qwen3.5:4b", "qwen3:4b", "qwen2.5:7b",
                "llama3.2:3b", "llama3.1:8b", "qwen3.5:8b",
                "mistral:7b", "phi3:mini",
            ]
            for p in preferred:
                if p in local:
                    print(f"[LLM] '{requested}' not found, using '{p}'")
                    return p
            if local:
                picked = sorted(local)[0]
                print(f"[LLM] Auto-selected: '{picked}'")
                return picked
    except Exception:
        pass
    return requested


def _ollama_chat(prompt: str, system: str, model: str,
                 temperature: float, max_tokens: int,
                 token_callback: Optional[Callable] = None,
                 tools: list = None, think: bool = True, messages: list = None) -> dict | str:
    """Call Ollama /api/chat. Always streams for real-time token display."""
    model = _resolve_ollama_model(model)
    
    if not messages:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if prompt:
            messages.append({"role": "user", "content": prompt})
    elif system:
        # Ensure system prompt is present even when messages are pre-built
        if not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system})

    # Thinking models (gemma4, qwen3, etc.) consume tokens on internal reasoning.
    # Give them extra budget so they don't exhaust num_predict before producing output.
    predict_budget = max_tokens + 1500

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": think,
        "options": {
            "temperature": temperature,
            "num_predict": predict_budget,
            "num_ctx": NUM_CTX,
        },
    }
    print(f"[Ollama] think={think}, tools={bool(tools)}, messages={len(messages)}")
    if tools:
        payload["tools"] = tools

    with _ollama_lock:
        resp = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
            stream=True,
        )
        if resp.status_code != 200:
            try:
                err_body = resp.text
            except Exception:
                err_body = f"HTTP {resp.status_code}"
            raise RuntimeError(f"Ollama error ({resp.status_code}): {err_body}")
            
        return _collect_ollama_stream(resp, token_callback, has_tools=bool(tools))


def _collect_ollama_stream(resp, token_callback, has_tools: bool = False) -> str | dict:
    """Collect streamed Ollama response. Keeps thinking content as fallback."""
    visible_chunks = []
    think_chunks = []
    in_think = False
    tool_calls = []
    raw_chunks = []   # Debug: track all raw content

    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", {})
        
        # Capture tool calls from stream
        if has_tools and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                tool_calls.append({
                    "id": tc.get("id"),
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"]
                })

        token = msg.get("content", "")
        thinking_text = msg.get("thinking", "")

        # Capture thinking tokens (Ollama puts them in a separate 'thinking' field)
        if thinking_text:
            think_chunks.append(thinking_text)

        if not token:
            continue

        raw_chunks.append(token)

        # If the Ollama API explicitly marks this chunk as thinking, capture and skip
        if thinking_text:
            # Content arrived alongside a thinking chunk — treat content as visible
            pass
        elif msg.get("thinking") is not None:
            # Edge case: thinking field exists but empty while content has text
            pass

        # Filter inline <think>...</think> tags from visible output
        token, in_think = _filter_think(token, in_think)
        if not token:
            continue

        visible_chunks.append(token)
        print(token, end="", flush=True)
        if token_callback:
            token_callback(token)

    print()

    visible = _strip_think("".join(visible_chunks).strip())

    if visible:
        return {"content": visible, "tool_calls": tool_calls} if has_tools else visible

    # Fallback: if visible output is empty but thinking produced content,
    # extract useful text from the thinking (the model "thought" but didn't
    # produce a visible reply — common with small thinking models).
    if think_chunks:
        think_text = "".join(think_chunks).strip()
        print(f"[LLM] No visible output — extracting from {len(think_text)} chars of thinking")
        fallback_text = think_text[:max(2000, len(think_text))]
        return {"content": fallback_text, "tool_calls": tool_calls} if has_tools else fallback_text

    # Last resort: if _filter_think stripped inline <think> tags, use raw content
    if raw_chunks:
        raw_text = _strip_think("".join(raw_chunks).strip())
        if raw_text:
            print(f"[LLM] Recovered {len(raw_text)} chars after stripping inline think tags")
            if token_callback:
                token_callback(raw_text)
            return {"content": raw_text, "tool_calls": tool_calls} if has_tools else raw_text
        else:
            print(f"[LLM] WARNING: Model produced {len(''.join(raw_chunks))} chars but all were <think> content")

    print("[LLM] WARNING: Model returned completely empty response")
    return {"content": "", "tool_calls": tool_calls} if has_tools else ""


def _filter_think(token: str, in_think: bool):
    result, i = [], 0
    while i < len(token):
        if not in_think:
            s = token.find("<think>", i)
            if s == -1:
                result.append(token[i:])
                break
            result.append(token[i:s])
            in_think = True
            i = s + 7
        else:
            e = token.find("</think>", i)
            if e == -1:
                break
            in_think = False
            i = e + 8
    return "".join(result), in_think


def _strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = re.sub(r"\s*/no_think\s*", "", text)
    return text.strip()


# ── Cloud provider calls ──────────────────────────────────────────────────────

def _openai_chat(messages: list, model: str,
                 temperature: float, max_tokens: int,
                 api_key: str, base_url: str = "https://api.openai.com/v1", tools: list = None) -> dict:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    kwargs = {
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        
    response = client.chat.completions.create(**kwargs)
    msg = response.choices[0].message
    
    tool_calls = []
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments)
            })
            
    return {"content": msg.content or "", "tool_calls": tool_calls}


def _anthropic_chat(messages: list, system: str, model: str,
                    temperature: float, max_tokens: int, tools: list = None) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    kwargs = {
        "model": model, "max_tokens": max_tokens, "temperature": temperature,
        "messages": messages, "system": system or "You are a helpful assistant."
    }
    if tools:
        kwargs["tools"] = tools
        
    response = client.messages.create(**kwargs)
    
    content = ""
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            content += block.text
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "name": block.name,
                "arguments": block.input
            })
            
    return {"content": content, "tool_calls": tool_calls}


def _gemini_chat(messages: list, system: str, model: str,
                 temperature: float, max_tokens: int, tools: list = None) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)
    kwargs = {"model_name": model, "system_instruction": system or None}
    if tools:
        kwargs["tools"] = tools
        
    gm = genai.GenerativeModel(**kwargs)
    
    # Gemini requires a specific message format (user/model roles, parts)
    # We map common {"role": "...", "content": "..."} to Gemini format
    gemini_history = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        if isinstance(m["content"], str):
            gemini_history.append({"role": role, "parts": [{"text": m["content"]}]})
            
    chat = gm.start_chat(history=gemini_history[:-1])
    response = chat.send_message(gemini_history[-1]["parts"])
    
    content = ""
    tool_calls = []
    if response.parts:
        for part in response.parts:
            if getattr(part, "text", None):
                content += part.text
            elif getattr(part, "function_call", None):
                fc = part.function_call
                args = {k: v for k, v in fc.args.items()}
                tool_calls.append({"name": fc.name, "arguments": args})
                
    return {"content": content, "tool_calls": tool_calls}


# ── Main dispatch ──────────────────────────────────────────────────────────────

def llm_call(prompt: str = "", system: str = "", messages: list = None,
             config: Optional[LLMConfig] = None, tools: list = None,
             token_callback: Optional[Callable] = None) -> dict:
    """
    Unified LLM call. Pass an LLMConfig to override provider/model.
    Returns: {"content": "...", "tool_calls": [...]}
    """
    if config is None:
        config = default_config()

    provider = config.provider.lower()
    label = f" [{config.label}]" if config.label else ""
    print(f"[LLM{label}] → {provider}/{config.model} (max_tokens={config.max_tokens})")
    
    if messages is None:
        messages = []
        if prompt:
            messages.append({"role": "user", "content": prompt})
    
    # Extract system prompt if embedded in messages
    sys_prompt = system
    filtered_messages = []
    for m in messages:
        if m["role"] == "system":
            sys_prompt = m["content"]
        else:
            filtered_messages.append(m)
    messages = filtered_messages

    try:
        if provider == "ollama":
            content = _ollama_chat(
                prompt=prompt, 
                system=sys_prompt, model=config.model,
                temperature=config.temperature, max_tokens=config.max_tokens,
                token_callback=token_callback,
                tools=tools, think=config.think, messages=messages
            )
            # _ollama_chat now returns dict if tools are enabled
            if isinstance(content, dict):
                return content
            return {"content": content, "tool_calls": []}

        elif provider == "openai":
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY not set in .env")
            if sys_prompt:
                messages.insert(0, {"role": "system", "content": sys_prompt})
            return _openai_chat(
                messages, config.model, config.temperature, config.max_tokens,
                api_key=settings.OPENAI_API_KEY, tools=tools
            )

        elif provider == "anthropic":
            if not settings.ANTHROPIC_API_KEY:
                raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
            return _anthropic_chat(
                messages, sys_prompt, config.model,
                config.temperature, config.max_tokens, tools=tools
            )

        elif provider == "gemini":
            if not settings.GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY not set in .env")
            return _gemini_chat(
                messages, sys_prompt, config.model,
                config.temperature, config.max_tokens, tools=tools
            )

        elif provider == "deepseek":
            if not settings.DEEPSEEK_API_KEY:
                raise RuntimeError("DEEPSEEK_API_KEY not set in .env")
            if sys_prompt:
                messages.insert(0, {"role": "system", "content": sys_prompt})
            return _openai_chat(
                messages, config.model, config.temperature, config.max_tokens,
                api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1", tools=tools
            )

        elif provider == "grok":
            if not settings.GROK_API_KEY:
                raise RuntimeError("GROK_API_KEY not set in .env")
            if sys_prompt:
                messages.insert(0, {"role": "system", "content": sys_prompt})
            return _openai_chat(
                messages, config.model, config.temperature, config.max_tokens,
                api_key=settings.GROK_API_KEY, base_url="https://api.x.ai/v1", tools=tools
            )

        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to {provider}. "
            + ("Run: ollama serve" if provider == "ollama" else "Check your network/API key.")
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(f"{provider} timed out. Try a smaller model.")


# ── Utility functions ──────────────────────────────────────────────────────────

def list_ollama_models() -> list[str]:
    """Return names of locally available Ollama models."""
    try:
        r = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def is_ollama_available() -> bool:
    try:
        r = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def get_available_providers() -> list[dict]:
    """Return list of providers with availability status."""
    providers = []
    providers.append({
        "id": "ollama", "name": "Ollama (Local)",
        "available": is_ollama_available(),
        "models": list_ollama_models(),
    })
    for pid, key, name in [
        ("openai",    settings.OPENAI_API_KEY,    "OpenAI"),
        ("anthropic", settings.ANTHROPIC_API_KEY,  "Anthropic"),
        ("gemini",    settings.GEMINI_API_KEY,     "Google Gemini"),
        ("deepseek",  settings.DEEPSEEK_API_KEY,   "DeepSeek"),
        ("grok",      settings.GROK_API_KEY,       "Grok (xAI)"),
    ]:
        has_key = bool(key and key.strip())
        providers.append({
            "id": pid, "name": name,
            "available": has_key,
            "models": [_default_model_for(pid)] if has_key else [],
        })
    return providers
