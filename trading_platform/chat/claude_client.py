"""chat/claude_client.py — Anthropic Claude agentic loop for trading commands."""
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field
from typing import List

import anthropic
from anthropic import APIStatusError, AuthenticationError

from chat.tools_schema import TOOLS
from chat.context_builder import build_system_prompt
from chat import command_parser
from core.config import settings


@dataclass
class ChatResult:
    response: str
    actions_taken: List[dict] = field(default_factory=list)


def _anthropic_error_message(e: Exception) -> str:
    """Convert Anthropic API errors into friendly user-facing messages."""
    msg = str(e)
    if "credit" in msg.lower() or "billing" in msg.lower() or "balance" in msg.lower():
        return (
            "Your Anthropic account has insufficient credits. "
            "Add credits at console.anthropic.com/billing, then try again."
        )
    if isinstance(e, AuthenticationError):
        return "Authentication failed — check your ANTHROPIC_API_KEY in .env."
    if isinstance(e, APIStatusError):
        return f"Anthropic API error ({e.status_code}): {e.message}"
    return f"Anthropic error: {msg}"


async def process_command(user_message: str, loop=None) -> ChatResult:
    loop = loop or asyncio.get_event_loop()

    if not settings.ANTHROPIC_API_KEY:
        return ChatResult(
            response="Anthropic API key not configured. Set ANTHROPIC_API_KEY in your .env file.",
            actions_taken=[],
        )

    client        = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system_prompt = build_system_prompt()
    messages      = [{"role": "user", "content": user_message}]
    actions_taken = []
    max_iters     = 6

    for _ in range(max_iters):
        try:
            response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2048,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as e:
            return ChatResult(response=_anthropic_error_message(e), actions_taken=actions_taken)

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
            return ChatResult(response=text, actions_taken=actions_taken)

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await command_parser.execute_tool(block.name, block.input, loop=loop)
                    actions_taken.append({
                        "tool":   block.name,
                        "input":  block.input,
                        "result": result,
                    })
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(result),
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        break  # unexpected stop reason

    # Fallback: extract text from last response
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text = block.text
    return ChatResult(response=text or "I've processed your request.", actions_taken=actions_taken)
