import asyncio
import hmac
from xml.sax.saxutils import escape

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import brain, config, db, events
from .agents import coder, comms
from .ml import preferences
from .ml.memory import memory
from .ml.router import router

app = FastAPI(title="J.A.R.V.I.S.")


def _ok(token):
    return not config.TOKEN or hmac.compare_digest(token or "", config.TOKEN)


def auth(request: Request):
    token = request.headers.get("x-jarvis-token") or request.query_params.get("token")
    if not _ok(token):
        raise HTTPException(401, "Bad token")


class ChatIn(BaseModel):
    text: str


class FeedbackIn(BaseModel):
    message_id: int
    score: int


class ApproveIn(BaseModel):
    id: int
    text: str | None = None


class SayIn(BaseModel):
    text: str


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")


@app.post("/api/chat", dependencies=[Depends(auth)])
async def api_chat(body: ChatIn):
    try:
        return await brain.chat(body.text.strip())
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.post("/api/feedback", dependencies=[Depends(auth)])
def api_feedback(body: FeedbackIn):
    brain.feedback(body.message_id, 1 if body.score > 0 else -1)
    return {"ok": True}


@app.get("/api/state", dependencies=[Depends(auth)])
def api_state():
    return {
        "user_title": config.USER_TITLE,
        "model": config.MODEL,
        "voice": "elevenlabs" if config.ELEVENLABS_API_KEY else "browser",
        "twilio": config.twilio_enabled(),
        "comms_mode": config.COMMS_MODE,
        "exec": config.ALLOW_EXEC,
        "preferences": preferences.top(40),
        "style": {"weights": preferences.style.weights(), "n": preferences.style.n},
        "router": {"trained_on": router.trained_on},
        "memory_size": memory.size(),
        "messages": db.history("chat", 40),
        "comms": comms.pending(),
        "tasks": list(brain.tasks.values()),
        "files": coder.list_files("").splitlines() if coder.list_files("") != "(empty)" else [],
        "events": events.recent(80),
    }


@app.delete("/api/preferences/{key}", dependencies=[Depends(auth)])
def api_forget(key: str):
    brain.forget(key)
    return {"ok": True}


@app.post("/api/comms/approve", dependencies=[Depends(auth)])
async def api_approve(body: ApproveIn):
    try:
        return {"sent": await comms.approve(body.id, body.text)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/comms/reject", dependencies=[Depends(auth)])
def api_reject(body: ApproveIn):
    comms.reject(body.id)
    return {"ok": True}


@app.get("/api/file", dependencies=[Depends(auth)])
def api_file(path: str):
    try:
        return {"path": path, "content": coder.read_file(path)}
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/tts", dependencies=[Depends(auth)])
async def api_tts(body: SayIn):
    """Premium Jarvis voice via ElevenLabs. 204 tells the browser to use its own voice."""
    if not (config.ELEVENLABS_API_KEY and config.ELEVENLABS_VOICE_ID):
        return Response(status_code=204)
    async with httpx.AsyncClient(timeout=30) as h:
        r = await h.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
            headers={"xi-api-key": config.ELEVENLABS_API_KEY, "accept": "audio/mpeg"},
            json={"text": body.text[:2500], "model_id": "eleven_turbo_v2_5",
                  "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.15}})
    if r.status_code != 200:
        return Response(status_code=204)
    return Response(r.content, media_type="audio/mpeg")


@app.websocket("/ws")
async def ws(socket: WebSocket):
    if not _ok(socket.query_params.get("token")):
        await socket.close(code=4401)
        return
    await socket.accept()
    q = events.subscribe()
    try:
        while True:
            await socket.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        events.unsubscribe(q)


# ---------------- Twilio webhooks ----------------

async def _twilio_form(request: Request):
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = (config.PUBLIC_BASE_URL + request.url.path) if config.PUBLIC_BASE_URL else str(request.url)
    if not comms.valid_twilio_signature(url, form, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(403, "Bad Twilio signature")
    return form


def twiml(body):
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    media_type="application/xml")


VOICE = 'voice="Polly.Brian-Neural" language="en-GB"'  # British male - closest stock voice to Jarvis


@app.post("/twilio/sms")
async def twilio_sms(request: Request):
    form = await _twilio_form(request)
    asyncio.create_task(comms.draft_sms_reply(form.get("From", ""), form.get("Body", "")))
    return twiml("")  # reply is sent via REST once drafted / approved


@app.post("/twilio/voice")
async def twilio_voice(request: Request):
    form = await _twilio_form(request)
    return await _speak(form, None)


@app.post("/twilio/voice/gather")
async def twilio_gather(request: Request):
    form = await _twilio_form(request)
    return await _speak(form, form.get("SpeechResult", "").strip())


async def _speak(form, said):
    reply, hang = await comms.call_turn(form.get("CallSid", ""), form.get("From", ""), said)
    say = f"<Say {VOICE}>{escape(reply)}</Say>"
    if hang:
        return twiml(say + "<Hangup/>")
    return twiml(f'<Gather input="speech" speechTimeout="auto" action="/twilio/voice/gather" method="POST">'
                 f"{say}</Gather><Say {VOICE}>I didn't catch that. Goodbye.</Say><Hangup/>")


def main():
    import uvicorn
    print(f"\n  J.A.R.V.I.S. online →  http://{config.HOST}:{config.PORT}\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
