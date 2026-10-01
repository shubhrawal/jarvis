import json
import sqlite3
import threading
import time

from .config import DATA_DIR

_lock = threading.Lock()
_conn = sqlite3.connect(DATA_DIR / "jarvis.db", check_same_thread=False)
_conn.row_factory = sqlite3.Row

_conn.executescript("""
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY, ts REAL, channel TEXT, role TEXT, content TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS preferences(
    key TEXT PRIMARY KEY, value TEXT, category TEXT, confidence REAL, hits INTEGER, updated REAL);
CREATE TABLE IF NOT EXISTS feedback(
    id INTEGER PRIMARY KEY, ts REAL, message_id INTEGER, score INTEGER);
CREATE TABLE IF NOT EXISTS comms(
    id INTEGER PRIMARY KEY, ts REAL, kind TEXT, contact TEXT, incoming TEXT,
    draft TEXT, status TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS contacts(
    number TEXT PRIMARY KEY, name TEXT, relationship TEXT, notes TEXT);
""")


def q(sql, args=(), one=False):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        rows = [dict(r) for r in cur.fetchall()]
        if sql.lstrip().upper().startswith("INSERT"):
            return cur.lastrowid
    return (rows[0] if rows else None) if one else rows


def add_message(channel, role, content, **meta):
    return q("INSERT INTO messages(ts,channel,role,content,meta) VALUES(?,?,?,?,?)",
             (time.time(), channel, role, content, json.dumps(meta)))


def history(channel="chat", limit=20):
    rows = q("SELECT * FROM messages WHERE channel=? ORDER BY id DESC LIMIT ?", (channel, limit))
    return list(reversed(rows))
