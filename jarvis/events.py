"""Tiny pub/sub so every part of Jarvis can tell the HUD what it's doing."""
import asyncio
import time
import itertools

_ids = itertools.count(1)
_subscribers: set[asyncio.Queue] = set()
_history: list[dict] = []
HISTORY_MAX = 300


def emit(kind, agent="core", **data):
    event = {"id": next(_ids), "ts": time.time(), "kind": kind, "agent": agent, **data}
    _history.append(event)
    del _history[:-HISTORY_MAX]
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
    return event


def subscribe():
    q = asyncio.Queue(maxsize=1000)
    _subscribers.add(q)
    return q


def unsubscribe(q):
    _subscribers.discard(q)


def recent(n=100):
    return _history[-n:]
