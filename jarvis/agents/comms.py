"""Comms agent: answers your texts and phone calls as your assistant (via Twilio)."""
import base64
import hashlib
import hmac
import time

import httpx

from .. import config, db
from ..events import emit
from ..llm import create, text_of
from ..ml import preferences

ME = config.USER_NAME or "my principal"


def _profile():
    return "\n".join(f"- {p['key']}: {p['value']}" for p in preferences.top(30)) or "- (nothing learned yet)"


def contact(number):
    return db.q("SELECT * FROM contacts WHERE number=?", (number,), one=True) or {"number": number, "name": None}


def _thread(number, limit=12):
    rows = db.q("SELECT role, content FROM messages WHERE channel=? ORDER BY id DESC LIMIT ?",
                (f"sms:{number}", limit))
    return "\n".join(f"{r['role'].upper()}: {r['content']}" for r in reversed(rows))


def _system(kind, who):
    return f"""You are J.A.R.V.I.S., the AI assistant of {ME}. You are handling an incoming {kind} for them.
Speak like Jarvis: calm, polite, British, quietly witty, efficient. Always be honest that you are {ME}'s AI assistant.
Never agree to commitments, payments, meetings or share private info on {ME}'s behalf - offer to pass the message on instead.
If it sounds urgent (emergency, family, work crisis) say you'll alert {ME} immediately.
Contact: {who.get('name') or 'unknown'} ({who.get('relationship') or 'relationship unknown'}). Notes: {who.get('notes') or 'none'}.
What you know about {ME}:
{_profile()}"""


async def draft_sms_reply(number, body):
    who = contact(number)
    db.add_message(f"sms:{number}", "them", body)
    emit("comms_in", "comms", medium="sms", contact=who.get("name") or number, text=body)
    resp = await create(
        max_tokens=1000, output_config={"effort": "low"},
        system=_system("text message", who) + "\nReply with ONLY the SMS text, under 300 characters.",
        messages=[{"role": "user", "content": f"Conversation so far:\n{_thread(number)}\n\nWrite the reply."}])
    draft = text_of(resp)
    cid = db.q("INSERT INTO comms(ts,kind,contact,incoming,draft,status,meta) VALUES(?,?,?,?,?,?,?)",
               (time.time(), "sms", number, body, draft, "pending", "{}"))
    emit("comms_draft", "comms", id=cid, contact=who.get("name") or number, incoming=body, draft=draft)
    if config.COMMS_MODE == "auto":
        await approve(cid)
    return cid, draft


async def approve(cid, text=None):
    row = db.q("SELECT * FROM comms WHERE id=?", (cid,), one=True)
    if not row or row["status"] != "pending":
        raise ValueError("No pending draft with that id")
    msg = text or row["draft"]
    await send_sms(row["contact"], msg)
    db.q("UPDATE comms SET status='sent', draft=? WHERE id=?", (msg, cid))
    return msg


def reject(cid):
    db.q("UPDATE comms SET status='dismissed' WHERE id=?", (cid,))


async def send_sms(to, body):
    if not config.twilio_enabled():
        emit("comms_out", "comms", medium="sms", contact=to, text=body, simulated=True)
        db.add_message(f"sms:{to}", "jarvis", body, simulated=True)
        return "Twilio not configured - message logged but not sent."
    async with httpx.AsyncClient(timeout=20) as h:
        r = await h.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
            data={"From": config.TWILIO_PHONE_NUMBER, "To": to, "Body": body})
        r.raise_for_status()
    db.add_message(f"sms:{to}", "jarvis", body)
    emit("comms_out", "comms", medium="sms", contact=to, text=body)
    return "Sent."


# ---------------- phone calls ----------------
_calls: dict[str, list] = {}


async def call_turn(call_sid, number, said):
    """One back-and-forth on a live call. Returns (what Jarvis says, hang_up?)."""
    who = contact(number)
    convo = _calls.setdefault(call_sid, [])
    if said:
        convo.append({"role": "user", "content": said})
        emit("comms_in", "comms", medium="call", contact=who.get("name") or number, text=said)
    else:
        convo.append({"role": "user", "content": "(call connected - greet the caller)"})
    resp = await create(
        max_tokens=600, output_config={"effort": "low"},
        system=_system("phone call", who) + "\nThis is spoken aloud: 1-3 short sentences, no markdown. "
               "Take a message if they want " + ME + ". When the caller is done, say goodbye and end with [END].",
        messages=convo)
    reply = text_of(resp)
    convo.append({"role": "assistant", "content": reply})
    hang = "[END]" in reply or len(convo) > 24
    reply = reply.replace("[END]", "").strip()
    emit("comms_out", "comms", medium="call", contact=who.get("name") or number, text=reply)
    if hang:
        await _summarize_call(call_sid, number)
    return reply, hang


async def _summarize_call(call_sid, number):
    convo = _calls.pop(call_sid, [])
    transcript = "\n".join(f"{'CALLER' if m['role'] == 'user' else 'JARVIS'}: {m['content']}" for m in convo[1:])
    resp = await create(max_tokens=500, output_config={"effort": "low"},
                        system="Summarize this call for the user in 1-3 lines: who, what they wanted, any action needed.",
                        messages=[{"role": "user", "content": transcript or "(silent call)"}])
    summary = text_of(resp)
    db.q("INSERT INTO comms(ts,kind,contact,incoming,draft,status,meta) VALUES(?,?,?,?,?,?,?)",
         (time.time(), "call", number, transcript, summary, "logged", "{}"))
    db.add_message("calls", "jarvis", f"Call from {number}: {summary}")
    emit("call_summary", "comms", contact=contact(number).get("name") or number, summary=summary)


def valid_twilio_signature(url, params, signature):
    """Reject webhooks that didn't come from Twilio."""
    if not config.TWILIO_AUTH_TOKEN:
        return True
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(config.TWILIO_AUTH_TOKEN.encode(), payload.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature or "")


def pending():
    return db.q("SELECT * FROM comms ORDER BY id DESC LIMIT 30")
