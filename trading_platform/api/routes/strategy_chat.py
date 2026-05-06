"""api/routes/strategy_chat.py — AI Strategy Assistant for Expert Mode.

Conversational endpoint that helps users design trading strategies via AI.
Uses the unified LLM router so any provider (Ollama, OpenAI, Anthropic, etc.)
can power the chat.  Stateless — conversation history is sent from the client.

Streams tokens to the frontend via WebSocket for real-time display.
"""
from __future__ import annotations
import asyncio
import json
import re
import uuid
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from agents.llm_router import llm_call, LLMConfig, default_config
from core.events import manager

router = APIRouter()

STRATEGY_SYSTEM_PROMPT = """You are a Trading Strategy Architect — an expert AI assistant embedded in an agentic trading platform.

Your job is to help users design autonomous trading agent configurations through conversation. You are friendly, knowledgeable, and concise.

## Your Workflow
1. **Understand** — Ask what stock/sector they're interested in, their trading style (momentum, mean-reversion, breakout, etc.), risk tolerance, and time horizon.
2. **Educate** — Briefly explain relevant indicators (RSI, SMA, EMA, MACD, VWAP, Bollinger Bands, etc.) if the user seems unsure.
3. **Craft** — Build precise, actionable strategy instructions the agent can follow.
4. **Configure** — When the strategy is ready, present the complete agent configuration.

## Rules
- Keep responses concise (2-4 paragraphs max)
- Use bullet points for clarity
- Always suggest specific values (e.g. "RSI below 30" not just "low RSI")
- When you have enough info to define the strategy, output a configuration block
- Be proactive — make suggestions, don't just ask questions

## Configuration Output
When you've gathered enough information and the strategy is ready, include EXACTLY this JSON block in your response (the frontend will detect and parse it):

```agent_config
{
  "name": "Descriptive Agent Name",
  "ticker": "AAPL",
  "strategy": "Full strategy instructions the agent will follow...",
  "schedule": "0 9 * * 1-5",
  "auto_execute": false
}
```

The schedule should be a cron expression. Common ones:
- "0 9 * * 1-5" = 9 AM weekdays (market open)
- "30 15 * * 1-5" = 3:30 PM weekdays (near close)
- "0 9,12,15 * * 1-5" = Three times daily
- "" = Manual only (no schedule)

Set auto_execute to false by default unless the user explicitly asks for auto-execution.

Do NOT output the config block until you've confirmed the strategy with the user. Ask at least 2-3 questions first to understand their goals."""


class ChatMessage(BaseModel):
    role: str       # "user" or "assistant"
    content: str


class StrategyChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    llm_provider: str = "ollama"
    llm_model: str = ""


@router.post("/api/expert/strategy-chat")
async def strategy_chat(req: StrategyChatRequest):
    """Process a strategy chat message and stream tokens via WebSocket."""

    # Build the full prompt from history + new message
    conversation_lines = []
    for msg in req.history:
        role_label = "User" if msg.role == "user" else "Assistant"
        conversation_lines.append(f"{role_label}: {msg.content}")
    conversation_lines.append(f"User: {req.message}")

    full_prompt = "\n\n".join(conversation_lines)
    if len(req.history) == 0:
        full_prompt = (
            "The user just opened the strategy chat. Greet them and ask what "
            "kind of trading strategy they'd like to build.\n\n"
            f"User: {req.message}"
        )

    # Build LLM config
    config = LLMConfig(
        provider=req.llm_provider,
        model=req.llm_model,
        temperature=0.7,
        max_tokens=800,
        label="Strategy Assistant",
    )

    # Generate a stream ID so the frontend can correlate token events
    stream_id = str(uuid.uuid4())[:8]
    loop = asyncio.get_event_loop()

    # Token callback — fires on each streamed token from Ollama
    def on_token(token: str):
        manager.broadcast_sync({
            "type": "strategy_chat_token",
            "stream_id": stream_id,
            "token": token,
        }, loop)

    # Notify frontend that streaming is starting
    await manager.broadcast({
        "type": "strategy_chat_start",
        "stream_id": stream_id,
    })

    try:
        response = await loop.run_in_executor(
            None,
            lambda: llm_call(
                full_prompt,
                system=STRATEGY_SYSTEM_PROMPT,
                config=config,
                token_callback=on_token,
            ),
        )
    except Exception as e:
        await manager.broadcast({
            "type": "strategy_chat_done",
            "stream_id": stream_id,
            "error": str(e),
        })
        return {
            "response": f"⚠️ LLM Error: {str(e)}",
            "agent_config": None,
            "stream_id": stream_id,
        }

    # Try to extract agent_config from the response
    agent_config = _extract_agent_config(response)

    # Notify frontend that streaming is done
    await manager.broadcast({
        "type": "strategy_chat_done",
        "stream_id": stream_id,
        "agent_config": agent_config,
    })

    return {
        "response": response,
        "agent_config": agent_config,
        "stream_id": stream_id,
    }


def _extract_agent_config(text: str) -> Optional[dict]:
    """Extract agent_config JSON from the AI response."""
    # Try ```agent_config ... ``` blocks first
    match = re.search(r'```agent_config\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        try:
            config = json.loads(match.group(1).strip())
            return _validate_config(config)
        except (json.JSONDecodeError, ValueError):
            pass

    # Try {"agent_config": {...}} pattern
    match = re.search(r'"agent_config"\s*:\s*(\{.*?\})', text, re.DOTALL)
    if match:
        try:
            config = json.loads(match.group(1).strip())
            return _validate_config(config)
        except (json.JSONDecodeError, ValueError):
            pass

    # Try any JSON block that has the right keys
    for match in re.finditer(r'\{[^{}]*"name"[^{}]*"ticker"[^{}]*"strategy"[^{}]*\}', text, re.DOTALL):
        try:
            config = json.loads(match.group())
            if "name" in config and "ticker" in config and "strategy" in config:
                return _validate_config(config)
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _validate_config(config: dict) -> dict:
    """Ensure config has required fields and sane defaults."""
    required = {"name", "ticker", "strategy"}
    if not required.issubset(config.keys()):
        return None

    return {
        "name": str(config["name"])[:100],
        "ticker": str(config["ticker"]).upper().strip()[:10],
        "strategy": str(config["strategy"])[:2000],
        "schedule": str(config.get("schedule", "")),
        "auto_execute": bool(config.get("auto_execute", False)),
    }
