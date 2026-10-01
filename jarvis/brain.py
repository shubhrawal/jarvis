"""J.A.R.V.I.S. core: personality, memory, routing and delegation to the agent divisions."""
import asyncio
import itertools
import time
from datetime import datetime

from . import config, db
from .agents import coder, comms, research
from .events import emit
from .llm import run_agent, tool
from .ml import preferences
from .ml.memory import memory
from .ml.router import router

T = config.USER_TITLE

PERSONA = f"""You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the personal AI of {config.USER_NAME or 'the user'}.
Voice: a composed British butler-engineer. Dry, understated wit; unfailingly polite; confident and efficient.
Address the user as "{T}". Natural Jarvis phrasing is welcome ("Right away, {T}.", "Indeed.", "Shall I...?",
"I've taken the liberty of..."), but never camp it up or repeat catchphrases. Never break character to talk about being a language model.

Your replies are usually SPOKEN ALOUD, so: lead with the answer, keep it to a few sentences, avoid markdown
tables and long lists unless asked. Code or long research goes in your divisions' output, not your speech.

You run three divisions you can dispatch in the background:
- Research division (start_research): anything needing current info, comparisons, or digging.
- Engineering division (start_build): writing or changing code/apps/scripts in the workspace.
- Comms division (send_text, check_comms, save_contact): texts and calls on {T}'s behalf.
Dispatch them instead of guessing; for quick facts you're sure of, just answer. After dispatching, say so briefly
- results arrive automatically when done. Use remember/forget when {T} tells you something about themself."""

_task_ids = itertools.count(1)
tasks: dict[int, dict] = {}


def _spawn(kind, label, coro):
    tid = next(_task_ids)
    tasks[tid] = {"id": tid, "kind": kind, "label": label, "status": "running", "started": time.time()}
    emit("task_start", kind, task_id=tid, label=label)

    async def runner():
        try:
            result = await coro(tid)
            tasks[tid].update(status="done", result=result)
            db.add_message("chat", "assistant", f"[{kind} task #{tid} complete: {label}]\n{result}", task=tid)
            emit("task_done", kind, task_id=tid, label=label, result=result)
        except Exception as e:
            tasks[tid].update(status="failed", result=str(e))
            emit("task_failed", kind, task_id=tid, label=label, error=str(e))

    asyncio.create_task(runner())
    return tid


def start_research(topic):
    tid = _spawn("research", topic[:80], lambda t: research.research(topic, task_id=t))
    return f"Research task #{tid} dispatched."


def start_build(spec):
    style = "; ".join(f"{p['value']}" for p in preferences.top(40) if p["category"] in ("tech",))
    tid = _spawn("code", spec[:80], lambda t: coder.build(spec, style, task_id=t))
    return f"Engineering task #{tid} dispatched. Files will land in ./workspace."


async def send_text(to, message):
    if not to.startswith("+"):
        row = db.q("SELECT number FROM contacts WHERE lower(name)=lower(?)", (to,), one=True)
        if not row:
            return f"No number on file for '{to}'. Ask {T} for it, then save_contact."
        to = row["number"]
    if config.COMMS_MODE == "auto":
        return await comms.send_sms(to, message)
    cid = db.q("INSERT INTO comms(ts,kind,contact,incoming,draft,status,meta) VALUES(?,?,?,?,?,?,?)",
               (time.time(), "sms-out", to, "", message, "pending", "{}"))
    emit("comms_draft", "comms", id=cid, contact=to, incoming="(outgoing)", draft=message)
    return "Draft queued on the HUD for one-click approval."


def check_comms():
    rows = comms.pending()[:10]
    if not rows:
        return "No texts or calls on record."
    return "\n".join(f"#{r['id']} {r['kind']} {r['contact']} [{r['status']}] in: {r['incoming'][:120]} | "
                     f"reply/summary: {(r['draft'] or '')[:160]}" for r in rows)


def save_contact(number, name, relationship, notes):
    db.q("INSERT OR REPLACE INTO contacts VALUES(?,?,?,?)", (number, name, relationship, notes))
    return f"Saved {name}."


def remember(key, value, category):
    preferences.reinforce(key, value, category, weight=0.5)
    emit("learned", "memory", items=[{"key": key, "value": value, "category": category}])
    return "Stored."


def forget(key):
    preferences.forget(key)
    emit("forgot", "memory", key=key)
    return "Forgotten."


def task_status():
    if not tasks:
        return "No tasks yet."
    return "\n".join(f"#{t['id']} {t['kind']} [{t['status']}] {t['label']}" for t in tasks.values())


CATS = ["personal", "work", "communication_style", "tech", "schedule", "people", "likes", "dislikes"]
TOOLS = [
    tool("start_research", "Dispatch the research division (web search + reading) in the background.",
         {"topic": {"type": "string", "description": "the full research brief"}}),
    tool("start_build", "Dispatch the engineering division to write code/projects in the workspace.",
         {"spec": {"type": "string", "description": "complete spec: what to build, language, features"}}),
    tool("send_text", "Text someone on the user's behalf.",
         {"to": {"type": "string", "description": "E.164 number like +15551234567 or a saved contact name"},
          "message": {"type": "string"}}),
    tool("check_comms", "List recent incoming texts/calls and drafted replies.", {}),
    tool("save_contact", "Save or update a contact.",
         {"number": {"type": "string"}, "name": {"type": "string"},
          "relationship": {"type": "string"}, "notes": {"type": "string"}}),
    tool("remember", "Store a durable fact or preference about the user.",
         {"key": {"type": "string"}, "value": {"type": "string"}, "category": {"type": "string", "enum": CATS}}),
    tool("forget", "Delete a stored preference by key.", {"key": {"type": "string"}}),
    tool("task_status", "List background tasks and their status.", {}),
]
HANDLERS = {"start_research": start_research, "start_build": start_build, "send_text": send_text,
            "check_comms": check_comms, "save_contact": save_contact, "remember": remember,
            "forget": forget, "task_status": task_status}
TOOL_TO_LABEL = {"start_research": "research", "start_build": "code", "send_text": "comms",
                 "check_comms": "comms", "save_contact": "comms"}


def _context(user_text, exclude):
    prof = "\n".join(f"- [{p['category']}] {p['key']}: {p['value']} (conf {p['score']:.2f})"
                     for p in preferences.top(25)) or "- nothing yet; learn as you go"
    recalls = memory.recall(user_text, k=5, exclude_ids=exclude)
    if recalls:
        emit("recall", "memory", items=[{"text": r["content"][:140], "score": r["score"]} for r in recalls])
    mem = "\n".join(f"- ({datetime.fromtimestamp(r['ts']):%b %d}) {r['role']}: {r['content'][:300]}"
                    for r in recalls) or "- none"
    style = preferences.style.guidance()
    return f"""{PERSONA}

Now: {datetime.now():%A %d %B %Y, %H:%M}.
What you've learned about {T}:
{prof}
Learned style preferences (from feedback): {style or 'not enough feedback yet'}
Possibly relevant past conversations:
{mem}"""


def _history(limit=16):
    msgs = []
    for r in db.history("chat", limit):
        role = "user" if r["role"] == "user" else "assistant"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n\n" + r["content"]
        else:
            msgs.append({"role": role, "content": r["content"]})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


async def chat(user_text):
    prediction = router.predict(user_text)
    emit("route", "router", **prediction)
    uid = db.add_message("chat", "user", user_text)
    system = _context(user_text, {r["id"] for r in db.history("chat", 16)})
    emit("user_said", "core", text=user_text)

    hint = (f"\n(Intent classifier suggests: {prediction['label']} @ {prediction['confidence']:.0%}. "
            "Use your judgment.)" if prediction["confidence"] > 0.5 else "")
    messages = _history() or [{"role": "user", "content": user_text}]
    messages[-1]["content"] += hint

    reply, used = await run_agent("core", system, messages, tools=TOOLS, handlers=HANDLERS, effort="medium")
    mid = db.add_message("chat", "assistant", reply, reply_to=uid)

    # learn: what the router *should* have said = what Jarvis actually did
    label = next((TOOL_TO_LABEL[t] for t in used if t in TOOL_TO_LABEL), "chat")
    router.learn(user_text, label)
    emit("router_learned", "router", label=label, n=router.trained_on)
    asyncio.create_task(_learn_prefs(user_text, reply))
    return {"reply": reply, "message_id": mid, "route": prediction}


async def _learn_prefs(user_text, reply):
    try:
        await preferences.extract(user_text, reply)
    except Exception as e:
        emit("agent_error", "memory", error=f"preference extraction failed: {e}")


def feedback(message_id, score):
    row = db.q("SELECT content FROM messages WHERE id=?", (message_id,), one=True)
    if not row:
        raise ValueError("unknown message")
    db.q("INSERT INTO feedback(ts,message_id,score) VALUES(?,?,?)", (time.time(), message_id, score))
    preferences.style.learn(row["content"], score > 0)
    emit("style_learned", "memory", weights=preferences.style.weights(), n=preferences.style.n)
