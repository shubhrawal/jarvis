# J.A.R.V.I.S.

Your own Jarvis: a British-butler AI that talks, listens, learns about you, and runs a team of agents.

```
            ┌──────────── HUD (browser) ─────────────┐
 you ──🎤──▶│ arc reactor · transcript · live activity│◀── WebSocket events
            └──────────────────┬──────────────────────┘
                               ▼
                       JARVIS CORE (Claude)
        ┌──────────┬──────────┴─────────┬──────────────┐
   Neural Router  Memory Core      Research agent   Engineering agent   Comms agent
   (learns intent) (learns you)     (web search)     (writes code)       (texts + calls)
```

## What it does

| Part | What it does |
|---|---|
| **Voice (both ways)** | Click **ACTIVATE** once, then just talk. Jarvis is always listening. When you pause, he answers out loud. While he talks, the mic pauses so he doesn't hear himself, then it turns back on. Tap the reactor or press Esc (or say "stop") to cut him off. Switch to *"Only when I say Jarvis"* mode if you want. Typing still works too. Add an ElevenLabs key for a better voice. |
| **HUD** | Animated arc reactor, live Activity Stream (every search, file, tool call), agent status lights, running operations, memory, comms queue, and built files. |
| **Research agent** | Searches the web, reads sources, sends back a short cited brief. Runs in the background. |
| **Engineering agent** | Builds real projects in `./workspace`. Click a file in the Engineering Bay to view it. |
| **Comms agent** | Answers your texts and phone calls through Twilio, as your assistant. Texts are drafted for your approval (or set `COMMS_MODE=auto`). Calls are answered live, then summarized for you. |

## How it learns (the ML part)

1. **Neural Router**: a small classifier that guesses which agent you need. Every time Jarvis picks an agent, that becomes a new training example, so it gets better the more you use it.
2. **Memory Core**: after each chat, Jarvis pulls out facts about you ("codes in Java", "mom's name is Priya"). If something comes up again, Jarvis gets more sure of it. If you change your mind, the new answer replaces the old one. Old facts fade slowly.
3. **Style model**: rate replies 👍 / 👎. A model learns what you like (short or long, lists, code, jokes) and tells Jarvis.
4. **Recall**: when you ask something, Jarvis searches your past conversations for anything related and uses it.

Everything is stored locally in `data/`.

## Run it

```bash
./run.sh            # first run creates .env; put your ANTHROPIC_API_KEY in it
./run.sh            # then open http://127.0.0.1:8000 in Chrome or Edge
```

Use Chrome or Edge, because voice input needs them. Wear headphones if you can, so the mic doesn't pick up Jarvis's voice.

## Optional: texts and calls

1. Get a Twilio phone number.
2. Fill in `TWILIO_*` in `.env`.
3. Make Jarvis reachable from the internet, for example `ngrok http 8000`, and put that URL in `PUBLIC_BASE_URL`.
4. Also set `JARVIS_TOKEN` so strangers can't open your HUD.
5. In Twilio, set your number's webhooks:
   - Messaging → `https://YOUR-URL/twilio/sms`
   - Voice → `https://YOUR-URL/twilio/voice`

To have your own texts and calls answered, forward them to that Twilio number.

Without Twilio, Comms runs in **SIM** mode. It drafts and logs messages but doesn't send them.

## Safety switches

- `COMMS_MODE=approve` (default): nothing gets texted until you click **SEND** on the HUD.
- `JARVIS_ALLOW_EXEC=0` (default): the engineering agent only writes files. Set it to `1` if you want it to run and test code inside `./workspace`.
- Jarvis tells callers he's an AI assistant and never agrees to anything on your behalf.
- Twilio webhooks are signature-checked.

## Files

```
jarvis/
  server.py        web server, HUD API, Twilio webhooks
  brain.py         Jarvis personality + gives work to the agents
  llm.py           Claude tool loop that reports each step to the HUD
  agents/          research.py · coder.py · comms.py
  ml/              router.py · memory.py · preferences.py
web/               the HUD (index.html, style.css, app.js)
workspace/         where built code goes
```
