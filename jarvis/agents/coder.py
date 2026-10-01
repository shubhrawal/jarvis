"""Engineering agent: writes, reads and (optionally) runs code inside ./workspace."""
import asyncio
import os
from pathlib import Path

from .. import config
from ..events import emit
from ..llm import run_agent, tool

WS = config.WORKSPACE.resolve()


def _safe(path):
    p = (WS / path).resolve()
    if p != WS and WS not in p.parents:
        raise ValueError("Path escapes the workspace")
    return p


def write_file(path, content):
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    emit("file_written", "code", path=str(p.relative_to(WS)), bytes=len(content))
    return f"Wrote {len(content)} chars to {path}"


def read_file(path):
    return _safe(path).read_text()[:60000]


def list_files(path):
    base = _safe(path or ".")
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and not any(part.startswith(".") or part in ("node_modules", "__pycache__")
                                   for part in p.relative_to(WS).parts):
            out.append(str(p.relative_to(WS)))
    return "\n".join(out[:500]) or "(empty)"


async def run_command(command, cwd):
    if not config.ALLOW_EXEC:
        return "Command execution is disabled (set JARVIS_ALLOW_EXEC=1 to enable). Tell the user how to run it instead."
    proc = await asyncio.create_subprocess_shell(
        command, cwd=_safe(cwd or "."), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "ANTHROPIC_API_KEY": ""})
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return "Timed out after 120s"
    return f"exit={proc.returncode}\n{out.decode(errors='replace')[-8000:]}"


TOOLS = [
    tool("write_file", "Create or overwrite a file in the workspace.",
         {"path": {"type": "string", "description": "relative path, e.g. snake/main.py"},
          "content": {"type": "string"}}),
    tool("read_file", "Read a workspace file.", {"path": {"type": "string"}}),
    tool("list_files", "List files under a workspace folder ('' for root).", {"path": {"type": "string"}}),
    tool("run_command", "Run a shell command in a workspace folder (tests, builds, scripts). 2 min timeout.",
         {"command": {"type": "string"}, "cwd": {"type": "string", "description": "relative folder, '' for root"}}),
]

HANDLERS = {"write_file": write_file, "read_file": read_file, "list_files": list_files, "run_command": run_command}


def system(style_notes):
    return f"""You are the engineering division of J.A.R.V.I.S. You build real, working software in the workspace.
Put each project in its own folder. Write complete files (no placeholders), include a short README.md
with how to run it. {"Run tests or the program to verify it works." if config.ALLOW_EXEC else "You cannot run code, so be careful and double-check logic."}
Coding style the user prefers: {style_notes or "clean, idiomatic, well-named"}.
Finish with a short summary: what you built, the files, and how to run it."""


async def build(spec, style_notes="", task_id=None):
    text, _ = await run_agent("code", system(style_notes), [{"role": "user", "content": spec}],
                              tools=TOOLS, handlers=HANDLERS, effort="high", max_steps=40, task_id=task_id)
    return text
