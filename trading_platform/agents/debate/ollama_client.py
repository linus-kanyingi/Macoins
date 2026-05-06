"""
agents/debate/ollama_client.py — Thin Ollama REST wrapper.
Adapted from findebate/agents/ollama_client.py to import from core.config.
"""
import re
import json
import requests
import time
import threading
from core.config import settings

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
DEBATE_TEMPERATURE = settings.DEBATE_TEMPERATURE

def _pick_model() -> str:
    """Return the configured model if available, otherwise auto-detect best local model."""
    configured = settings.OLLAMA_MODEL
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            local = {m["name"] for m in r.json().get("models", [])}
            if configured in local:
                return configured
            # Auto-pick from preference list
            preferred = [
                # Small models first (more likely to fit in RAM)
                "qwen3.5:0.8b", "qwen3:0.6b", "qwen3:1.7b",
                "qwen3.5:1.5b", "qwen2.5:3b", "llama3.2:1b",
                # Medium models
                "qwen3.5:4b", "qwen3:4b", "qwen2.5:7b",
                "llama3.2:3b", "llama3.1:8b", "qwen3.5:8b",
                "mistral:7b", "phi3:mini",
            ]
            for p in preferred:
                if p in local:
                    print(f"[Ollama] '{configured}' not found, using '{p}' instead")
                    return p
            if local:
                picked = sorted(local)[0]
                print(f"[Ollama] Auto-selected model: '{picked}'")
                return picked
    except Exception:
        pass
    return configured

OLLAMA_MODEL = _pick_model()

OLLAMA_TIMEOUT = 300
NUM_CTX = 768   # slightly larger context keeps reasoning + response in budget

_ollama_lock = threading.Semaphore(1)


def chat(prompt: str, system: str = "", model: str = OLLAMA_MODEL,
         temperature: float = DEBATE_TEMPERATURE, max_tokens: int = 150,
         stream_print: bool = True, token_callback=None) -> str:
    effective_prompt = prompt + "\n/no_think"
    last_err = None
    with _ollama_lock:
        for attempt, (endpoint, fn) in enumerate([
            ("chat",     _call_chat),
            ("generate", _call_generate),
            ("chat",     _call_chat),
        ]):
            if attempt == 2:
                time.sleep(2)
            try:
                return fn(effective_prompt, system, model, temperature,
                          max_tokens, stream_print, token_callback)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 404:
                    last_err = e
                    time.sleep(1)
                    continue
                raise RuntimeError(f"Ollama HTTP {status}: {e}")
            except requests.exceptions.ConnectionError:
                raise RuntimeError("Cannot connect to Ollama. Run: ollama serve")
            except requests.exceptions.Timeout:
                raise RuntimeError(
                    f"Ollama timed out after {OLLAMA_TIMEOUT}s. "
                    "Try a smaller model: ollama pull qwen3:4b"
                )
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Ollama error: {e}")
        raise RuntimeError(
            f"Ollama returned 404 on all endpoints for model '{model}'.\n"
            f"Run 'ollama list' to confirm the model name.\nLast error: {last_err}"
        )


def _call_chat(prompt, system, model, temperature, max_tokens, stream_print, token_callback):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": NUM_CTX},
        },
        timeout=OLLAMA_TIMEOUT,
        stream=True,
    )
    resp.raise_for_status()
    return _collect_chat(resp, stream_print, token_callback)


def _call_generate(prompt, system, model, temperature, max_tokens, stream_print, token_callback):
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": model,
            "prompt": full_prompt,
            "stream": True,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": NUM_CTX},
        },
        timeout=OLLAMA_TIMEOUT,
        stream=True,
    )
    resp.raise_for_status()
    return _collect_generate(resp, stream_print, token_callback)


def _collect_chat(resp, stream_print, token_callback):
    chunks, in_think = [], False
    if stream_print:
        print()
    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", {})
        if msg.get("thinking"):
            continue
        token = msg.get("content", "")
        if not token:
            continue
        token, in_think = _filter_think(token, in_think)
        if not token:
            continue
        chunks.append(token)
        if stream_print:
            print(token, end="", flush=True)
        if token_callback:
            token_callback(token)
    if stream_print:
        print()
    return _strip_think("".join(chunks).strip())


def _collect_generate(resp, stream_print, token_callback):
    chunks, in_think = [], False
    if stream_print:
        print()
    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        token = obj.get("response", "")
        if not token:
            continue
        token, in_think = _filter_think(token, in_think)
        if not token:
            continue
        chunks.append(token)
        if stream_print:
            print(token, end="", flush=True)
        if token_callback:
            token_callback(token)
    if stream_print:
        print()
    return _strip_think("".join(chunks).strip())


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


def is_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def list_local_models() -> list:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def warmup(model: str = OLLAMA_MODEL, progress_callback=None) -> bool:
    def log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(f"  Loading: {msg}")

    log(f"Loading model '{model}' into memory...")
    try:
        requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": "10m", "stream": False},
            timeout=120,
        )
        log(f"Model '{model}' loaded and ready")
        return True
    except Exception as e:
        log(f"Warmup note: {e} — continuing anyway")
        return True


def detect_model() -> str:
    models = list_local_models()
    if not models:
        return OLLAMA_MODEL
    print(f"  Available Ollama models: {', '.join(models)}")
    preferred = [
        "qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b", "qwen3.5:4b",
        "qwen3.5:4b", "qwen3.5:8b", "qwen3.5:1.5b",
        "qwen3:4b", "qwen3:8b", "qwen3:1.7b", "qwen3:0.6b",
        "qwen2:7b", "qwen2:3b", "qwen:7b", "qwen:4b",
        "llama3.2:3b", "llama3.2:1b", "llama3.1:8b", "llama3:8b",
        "mistral:7b", "phi3:mini", "phi3.5:mini",
    ]
    ml = {m.lower(): m for m in models}
    for p in preferred:
        if p in ml:
            return ml[p]
    return models[0]
