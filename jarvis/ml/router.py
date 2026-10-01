"""Online intent classifier. Learns which agent should handle a request.

Every time Jarvis (Claude) decides to use an agent, that choice becomes a training
label, so the router gets sharper the more you talk to it.
"""
import pickle
import threading

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier

from ..config import DATA_DIR

LABELS = ["chat", "research", "code", "comms"]
PATH = DATA_DIR / "router.pkl"

SEED = [
    ("hello jarvis how are you", "chat"),
    ("what's on your mind", "chat"),
    ("tell me a joke", "chat"),
    ("thanks that's all", "chat"),
    ("good morning", "chat"),
    ("remember that I like my coffee black", "chat"),
    ("research the best laptops for programming", "research"),
    ("look up the latest news on spacex", "research"),
    ("find out who won the game last night", "research"),
    ("what is the current price of bitcoin", "research"),
    ("compare electric cars under 40k", "research"),
    ("dig into this company and give me a report", "research"),
    ("build me a python script that renames files", "code"),
    ("write a react component for a todo list", "code"),
    ("fix the bug in my function", "code"),
    ("create a website for my portfolio", "code"),
    ("make a java class for a bank account", "code"),
    ("code a snake game", "code"),
    ("text mom that I'll be late", "comms"),
    ("reply to that message from alex", "comms"),
    ("send a text to john saying meeting moved", "comms"),
    ("who called me today", "comms"),
    ("any new messages", "comms"),
    ("approve the draft reply", "comms"),
]


class Router:
    def __init__(self):
        self.lock = threading.Lock()
        self.vec = HashingVectorizer(n_features=2 ** 18, ngram_range=(1, 2), alternate_sign=False)
        self.trained_on = 0
        if PATH.exists():
            with open(PATH, "rb") as f:
                state = pickle.load(f)
            self.clf, self.trained_on = state["clf"], state["n"]
        else:
            self.clf = SGDClassifier(loss="log_loss", alpha=1e-4, random_state=0)
            texts, labels = zip(*SEED)
            for _ in range(15):  # a few passes so the seed sticks
                self.clf.partial_fit(self.vec.transform(texts), labels, classes=LABELS)
            self.trained_on = len(SEED)
            self._save()

    def predict(self, text):
        with self.lock:
            probs = self.clf.predict_proba(self.vec.transform([text]))[0]
        ranked = sorted(zip(self.clf.classes_, probs), key=lambda x: -x[1])
        return {"label": str(ranked[0][0]), "confidence": float(ranked[0][1]),
                "probs": {str(k): round(float(v), 3) for k, v in ranked}}

    def learn(self, text, label):
        if label not in LABELS:
            return
        with self.lock:
            self.clf.partial_fit(self.vec.transform([text]), [label])
            self.trained_on += 1
            self._save()

    def _save(self):
        with open(PATH, "wb") as f:
            pickle.dump({"clf": self.clf, "n": self.trained_on}, f)


router = Router()
