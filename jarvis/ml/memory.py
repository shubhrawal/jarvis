"""Long-term memory: semantic-ish recall over every past conversation (TF-IDF + cosine)."""
import threading

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .. import db


class Memory:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows, self.matrix, self.vec = [], None, None

    def _refit(self):
        rows = db.q("SELECT id, ts, channel, role, content FROM messages WHERE length(content) > 12")
        if len(rows) == len(self.rows) and self.matrix is not None:
            return
        self.rows = rows
        if len(rows) < 3:
            self.matrix = None
            return
        self.vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vec.fit_transform([r["content"] for r in rows])

    def recall(self, text, k=5, min_score=0.18, exclude_ids=()):
        with self.lock:
            self._refit()
            if self.matrix is None:
                return []
            sims = cosine_similarity(self.vec.transform([text]), self.matrix)[0]
        hits = []
        for i in sims.argsort()[::-1]:
            if sims[i] < min_score or len(hits) >= k:
                break
            r = self.rows[i]
            if r["id"] in exclude_ids:
                continue
            hits.append({**r, "score": round(float(sims[i]), 3)})
        return hits

    def size(self):
        return len(self.rows)


memory = Memory()
