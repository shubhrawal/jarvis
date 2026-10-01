"""Claude tool-use loop that narrates every step to the HUD."""
import asyncio
import json
import inspect

import anthropic

from . import config
from .events import emit

client = anthropic.AsyncAnthropic()

SERVER_TOOL_TYPES = ("web_search", "web_fetch")


async def create(**params):
    """messages.create with refusal fallbacks switched on (server-side, routed by category)."""
    params.setdefault("model", config.MODEL)
    params.setdefault("max_tokens", 16000)
    if config.USE_FALLBACKS:
        return await client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
    return await client.messages.create(**params)


def text_of(response):
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def run_agent(agent, system, messages, tools=(), handlers=None, effort="medium",
                    max_steps=25, task_id=None):
    """Loop until Claude stops calling tools. Returns (final_text, tools_used)."""
    handlers = handlers or {}
    messages = list(messages)
    used = []
    emit("agent_start", agent, task_id=task_id)
    try:
        for _ in range(max_steps):
            response = await create(system=system, messages=messages, tools=list(tools),
                                    output_config={"effort": effort})
            messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text" and block.text.strip() and response.stop_reason == "tool_use":
                    emit("narration", agent, text=block.text.strip(), task_id=task_id)
                elif block.type == "server_tool_use":
                    used.append(block.name)
                    emit("tool_call", agent, tool=block.name, input=block.input, task_id=task_id)
                elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                    emit("tool_result", agent, tool="web_search", task_id=task_id,
                         summary=f"{len(block.content)} results",
                         items=[{"title": r.title, "url": r.url} for r in block.content[:6]])

            if response.stop_reason == "refusal":
                emit("agent_error", agent, error="Request declined by safety systems.", task_id=task_id)
                return "I'm afraid I can't help with that one, " + config.USER_TITLE + ".", used
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                final = text_of(response)
                emit("agent_done", agent, text=final[:400], task_id=task_id)
                return final, used

            calls = [b for b in response.content if b.type == "tool_use"]
            results = await asyncio.gather(*(_call(agent, b, handlers, task_id) for b in calls))
            used += [b.name for b in calls]
            messages.append({"role": "user", "content": list(results)})

        emit("agent_error", agent, error="Step limit reached", task_id=task_id)
        return "I ran out of steps on that one. Shall I keep going?", used
    except anthropic.APIConnectionError as e:
        emit("agent_error", agent, error=f"Connection failed: {e}", task_id=task_id)
        raise
    except anthropic.APIStatusError as e:
        emit("agent_error", agent, error=f"API {e.status_code}: {e.message}", task_id=task_id)
        raise


async def _call(agent, block, handlers, task_id):
    emit("tool_call", agent, tool=block.name, input=_short(block.input), task_id=task_id)
    fn = handlers.get(block.name)
    try:
        if fn is None:
            raise ValueError(f"Unknown tool {block.name}")
        out = fn(**block.input)
        if inspect.isawaitable(out):
            out = await out
        out = out if isinstance(out, str) else json.dumps(out, default=str)
        emit("tool_result", agent, tool=block.name, summary=out[:300], task_id=task_id)
        return {"type": "tool_result", "tool_use_id": block.id, "content": out}
    except Exception as e:  # tool errors go back to Claude, not up the stack
        emit("tool_result", agent, tool=block.name, summary=f"ERROR: {e}", error=True, task_id=task_id)
        return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True}


def _short(d):
    return {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v) for k, v in d.items()}


def tool(name, description, props, required=None):
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": required if required is not None else list(props),
            "additionalProperties": False,
        },
    }
