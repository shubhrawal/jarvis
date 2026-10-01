"""Research agent: searches the live web, reads sources, writes a cited brief."""
from .. import config
from ..llm import run_agent

SYSTEM = f"""You are the research division of J.A.R.V.I.S., working for {config.USER_NAME or 'your principal'}.
Search the web, read the most useful sources, and cross-check key claims.
Return a tight brief: a 1-2 sentence bottom line first, then key findings, then sources as markdown links.
Note anything uncertain or contested. No filler."""

TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 6},
]


async def research(topic, task_id=None):
    text, _ = await run_agent("research", SYSTEM, [{"role": "user", "content": topic}],
                              tools=TOOLS, effort="high", task_id=task_id)
    return text
