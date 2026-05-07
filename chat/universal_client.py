"""chat/universal_client.py — Universal agentic loop for trading commands.

Runs a tool-calling loop using `llm_router.py` across any supported LLM provider.
"""
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field
from typing import List, Callable, Optional

from agents.llm_router import llm_call, LLMConfig
from chat import command_parser
from chat.tools_schema import get_anthropic_tools, get_openai_tools, get_gemini_tools


@dataclass
class ChatResult:
    response: str
    actions_taken: List[dict] = field(default_factory=list)


async def process_universal_chat(
    messages: List[dict],
    system_prompt: str,
    llm_config: LLMConfig,
    token_callback: Optional[Callable] = None,
    loop=None,
) -> ChatResult:
    """Run an agentic loop using any LLM provider."""
    loop = loop or asyncio.get_event_loop()

    # Determine which tool format to use based on the provider
    provider = llm_config.provider.lower()
    if provider == "anthropic":
        tools = get_anthropic_tools()
    elif provider == "gemini":
        tools = get_gemini_tools()
    else:
        # OpenAI, Ollama, DeepSeek, Grok all use OpenAI format
        tools = get_openai_tools()

    actions_taken = []
    max_iters = 6
    empty_count = 0  # Track consecutive empty responses

    for iteration in range(max_iters):
        # We only pass token_callback on the final iteration (when no tools are expected)
        # or we just pass it and let the router ignore it if it doesn't stream.
        # However, for tool execution, streaming intermediate thoughts can be messy.
        # We will pass token_callback always; llm_router handles disabling it if needed.
        
        try:
            result = await loop.run_in_executor(
                None,
                lambda: llm_call(
                    system=system_prompt,
                    messages=messages,
                    config=llm_config,
                    tools=tools,
                    token_callback=token_callback,
                )
            )
        except Exception as e:
            return ChatResult(response=f"LLM Error: {str(e)}", actions_taken=actions_taken)

        content = result.get("content", "")
        tool_calls = result.get("tool_calls", [])

        # Track empty responses — small models often can't handle tool calling
        if not content.strip():
            empty_count += 1
            if empty_count >= 2 or (empty_count >= 1 and not tool_calls):
                fallback = "⚠️ The model returned an empty response. This can happen with smaller models that struggle with tool-calling. Try a larger model (e.g. gemma4:e2b) or enable the Think toggle."
                if token_callback:
                    token_callback(fallback)
                return ChatResult(response=fallback, actions_taken=actions_taken)
        else:
            empty_count = 0

        # Append assistant's message to history
        assistant_msg = {"role": "assistant", "content": content}
        
        # Some providers need tool_calls included in the assistant message to maintain conversation state
        if provider in ["openai", "deepseek", "grok", "ollama"] and tool_calls:
            # We add it in the OpenAI format for history
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{i}"), 
                    "type": "function", 
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}
                }
                for i, tc in enumerate(tool_calls)
            ]
        
        messages.append(assistant_msg)

        # For non-streaming providers, manually push the generated content.
        # Ollama streams tokens directly via callback, so skip to avoid duplicates.
        if content and token_callback and provider != "ollama":
            # If we're going to loop again, add a visual separator for the user
            separator = "\n\n" if tool_calls else ""
            token_callback(content + separator)

        if not tool_calls:
            # No more tools to call, we are done
            return ChatResult(response=content, actions_taken=actions_taken)

        # Execute tools
        tool_results_msg = {"role": "user", "content": []}
        
        for i, tc in enumerate(tool_calls):
            tool_name = tc["name"]
            tool_args = tc["arguments"]
            call_id = tc.get("id", f"call_{i}")
            
            tool_result = await command_parser.execute_tool(tool_name, tool_args, loop=loop)
            
            actions_taken.append({
                "tool": tool_name,
                "input": tool_args,
                "result": tool_result,
            })
            
            # Format the tool result for the specific provider
            if provider == "anthropic":
                # Anthropic tool result format
                tool_results_msg["content"].append({
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": json.dumps(tool_result),
                })
            elif provider in ["openai", "deepseek", "grok", "ollama"]:
                # OpenAI tool result format requires a separate message per tool call
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(tool_result)
                })
            elif provider == "gemini":
                # Gemini tool result format
                messages.append({
                    "role": "user",
                    "content": f"Tool '{tool_name}' returned: {json.dumps(tool_result)}"
                })

        if provider == "anthropic":
            messages.append(tool_results_msg)

    final_msg = "Max iterations reached."
    if token_callback:
        token_callback("\n\n" + final_msg)
    return ChatResult(response=final_msg, actions_taken=actions_taken)
