"""SQLite-backed storage for group messages.

Categories are defined per-profile (see profiles/*.json) and stored as free-text
so the same DB schema works for any deployment domain.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "talbot.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_name TEXT    NOT NULL,
                sender_phone TEXT,
                content     TEXT    NOT NULL,
                category    TEXT    NOT NULL DEFAULT 'general',
                timestamp   TEXT    NOT NULL,
                group_id    TEXT    NOT NULL DEFAULT 'default'
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
            USING fts5(sender_name, content, content='messages', content_rowid='id')
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_ai
            AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, sender_name, content)
                VALUES (new.id, new.sender_name, new.content);
            END
        """)


def add_message(sender_name, content, category="general", sender_phone=None, timestamp=None, group_id="default") -> int:
    ts = timestamp or datetime.utcnow().isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO messages (sender_name, sender_phone, content, category, timestamp, group_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sender_name, sender_phone, content, category, ts, group_id),
        )
        return cur.lastrowid


def search_messages(query: str, limit: int = 10) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT m.id, m.sender_name, m.sender_phone, m.content, m.category, m.timestamp
               FROM messages_fts JOIN messages m ON messages_fts.rowid = m.id
               WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_messages_by_category(category: str, limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, sender_name, sender_phone, content, category, timestamp
               FROM messages WHERE category = ? ORDER BY timestamp DESC LIMIT ?""",
            (category, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_messages(days: int = 7, limit: int = 200) -> list[dict]:
    from datetime import timedelta
    cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0) - timedelta(days=days)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, sender_name, sender_phone, content, category, timestamp
               FROM messages WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?""",
            (cutoff.isoformat(), limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_statistics() -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        by_category = {row["category"]: row["cnt"] for row in conn.execute(
            "SELECT category, COUNT(*) as cnt FROM messages GROUP BY category").fetchall()}
        unique_senders = conn.execute("SELECT COUNT(DISTINCT sender_name) FROM messages").fetchone()[0]
        most_active = conn.execute(
            "SELECT sender_name, COUNT(*) as cnt FROM messages GROUP BY sender_name ORDER BY cnt DESC LIMIT 5").fetchall()
        return {"total_messages": total, "unique_members": unique_senders,
                "by_category": by_category, "most_active_members": [dict(r) for r in most_active]}


def find_senders_by_topic(topic: str, limit: int = 10) -> list[dict]:
    rows = search_messages(topic, limit=limit)
    seen: dict[str, dict] = {}
    for r in rows:
        name = r["sender_name"]
        if name not in seen:
            seen[name] = {"sender_name": name, "sender_phone": r["sender_phone"], "snippets": []}
        seen[name]["snippets"].append(r["content"][:120])
    return list(seen.values())
