import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def env(name, default=""):
    return os.environ.get(name, default).strip()


MODEL = env("JARVIS_MODEL", "claude-opus-5-5")
USE_FALLBACKS = env("JARVIS_FALLBACKS", "1") == "1"
USER_NAME = env("JARVIS_USER_NAME", "")
USER_TITLE = env("JARVIS_USER_TITLE", "sir")
HOST = env("JARVIS_HOST", "127.0.0.1")
PORT = int(env("JARVIS_PORT", "8000"))
TOKEN = env("JARVIS_TOKEN")
ALLOW_EXEC = env("JARVIS_ALLOW_EXEC", "0") == "1"

ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = env("ELEVENLABS_VOICE_ID")

TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = env("TWILIO_PHONE_NUMBER")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL").rstrip("/")
COMMS_MODE = env("COMMS_MODE", "approve")

DATA_DIR = ROOT / "data"
WORKSPACE = ROOT / "workspace"
WEB_DIR = ROOT / "web"
DATA_DIR.mkdir(exist_ok=True)
WORKSPACE.mkdir(exist_ok=True)


def twilio_enabled():
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER)
