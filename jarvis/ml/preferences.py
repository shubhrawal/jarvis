"""Learns who you are and how you like things done.

Two learners:
  1. Profile learner - after each exchange Claude pulls out durable facts/preferences.
     Each repeat sighting raises confidence; contradictions replace the value.
  2. Style learner - a logistic regression trained on your thumbs up/down that figures
     out whether you like replies short or long, with lists, with code, etc.
"""
import json
import pickle
import time
import threading

import numpy as np
from sklearn.linear_model import SGDClassifier

from .. import db
from ..config import DATA_DIR
from ..events import emit

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "preferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "short snake_case id, e.g. favorite_language"},
                    "value": {"type": "string"},
                    "category": {"type": "string", "enum": [
                        "personal", "work", "communication_style", "tech", "schedule", "people", "likes", "dislikes"]},
                },
                "required": ["key", "value", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["preferences"],
    "additionalProperties": False,
}


async def extract(user_text, reply_text):
    from ..llm import create, text_of  # late import avoids a cycle
    known = ", ".join(f"{p['key']}={p['value']}" for p in top(40)) or "nothing yet"
    resp = await create(
        max_tokens=2000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": EXTRACT_SCHEMA}},
        system=("You maintain a user profile for a personal assistant. From the exchange, extract ONLY "
                "durable facts or preferences about the user worth remembering for weeks (names of people, "
                "tools they use, tastes, schedule habits, how they like answers). Skip one-off requests. "
                "Reuse an existing key when updating something already known. Return an empty list if nothing new.\n"
                f"Known profile: {known}"),
        messages=[{"role": "user", "content": f"USER: {user_text}\n\nASSISTANT: {reply_text}"}],
    )
    if resp.stop_reason != "end_turn":
        return []
    found = json.loads(text_of(resp)).get("preferences", [])
    for p in found:
        reinforce(p["key"], p["value"], p["category"])
    if found:
        emit("learned", "memory", items=found)
    return found


def reinforce(key, value, category, weight=0.25):
    row = db.q("SELECT * FROM preferences WHERE key=?", (key,), one=True)
    now = time.time()
    if row is None:
        db.q("INSERT INTO preferences VALUES(?,?,?,?,?,?)", (key, value, category, 0.5, 1, now))
    elif row["value"].lower() == value.lower():
        conf = min(1.0, row["confidence"] + weight * (1 - row["confidence"]))
        db.q("UPDATE preferences SET confidence=?, hits=hits+1, updated=? WHERE key=?", (conf, now, key))
    else:  # you changed your mind - newest wins, confidence resets a bit
        db.q("UPDATE preferences SET value=?, category=?, confidence=0.55, hits=hits+1, updated=? WHERE key=?",
             (value, category, now, key))


def forget(key):
    db.q("DELETE FROM preferences WHERE key=?", (key,))


def top(n=25):
    """Confidence decays slowly if a preference isn't seen again (half-life ~60 days)."""
    rows = db.q("SELECT * FROM preferences")
    now = time.time()
    for r in rows:
        age_days = (now - r["updated"]) / 86400
        r["score"] = r["confidence"] * 0.5 ** (age_days / 60)
    return sorted(rows, key=lambda r: -r["score"])[:n]


# ---------------- style learner ----------------

STYLE_PATH = DATA_DIR / "style.pkl"
FEATURES = ["length", "has_list", "has_code", "has_question", "has_joke"]


def featurize(text):
    return np.array([[
        min(len(text) / 800.0, 3.0),
        float("\n- " in text or "\n1." in text),
        float("```" in text),
        float(text.strip().endswith("?")),
        float(any(w in text.lower() for w in ("indeed", "naturally", "of course", "shall i"))),
    ]])


class StyleLearner:
    def __init__(self):
        self.lock = threading.Lock()
        self.n = 0
        self.clf = SGDClassifier(loss="log_loss", alpha=0.01, random_state=0)
        if STYLE_PATH.exists():
            with open(STYLE_PATH, "rb") as f:
                self.clf, self.n = pickle.load(f)

    def learn(self, text, liked):
        with self.lock:
            self.clf.partial_fit(featurize(text), [int(liked)], classes=[0, 1])
            self.n += 1
            with open(STYLE_PATH, "wb") as f:
                pickle.dump((self.clf, self.n), f)

    def weights(self):
        if self.n < 4 or not hasattr(self.clf, "coef_"):
            return {}
        return {f: round(float(w), 3) for f, w in zip(FEATURES, self.clf.coef_[0])}

    def guidance(self):
        w = self.weights()
        if not w:
            return ""
        tips = []
        if w["length"] < -0.3:
            tips.append("keep replies short")
        elif w["length"] > 0.3:
            tips.append("detailed replies are welcome")
        if w["has_list"] > 0.3:
            tips.append("bullet points land well")
        elif w["has_list"] < -0.3:
            tips.append("avoid bullet lists")
        if w["has_code"] > 0.3:
            tips.append("show code examples")
        if w["has_joke"] > 0.3:
            tips.append("lean into the dry wit")
        elif w["has_joke"] < -0.3:
            tips.append("tone down the banter")
        return "; ".join(tips)


style = StyleLearner()
