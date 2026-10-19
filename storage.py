"""SQLite-backed storage for group messages.

Every message belongs to a group (group_id = the profile key, e.g. "hiphop"),
so one server can serve many classes while each class only ever sees its own
memory. Categories are per-profile and stored as free text.
"""

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "talbot.db"
DEFAULT_GROUP = "default"


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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_group ON messages(group_id)")
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


def adopt_legacy_rows(group_id: str) -> int:
    """Rows stored before multi-class support carry group_id 'default'.

    They belonged to the server's single class, so hand them to that class
    once; afterwards no row stays under 'default'.
    """
    if group_id == DEFAULT_GROUP:
        return 0
    with _connect() as conn:
        return conn.execute("UPDATE messages SET group_id = ? WHERE group_id = ?",
                            (group_id, DEFAULT_GROUP)).rowcount


def _fts_query(raw: str) -> Optional[str]:
    """Turn free text into a safe FTS5 query: each word quoted, OR-joined.

    Raw user/model text can contain FTS5 syntax characters (quotes, hyphens,
    colons) that would otherwise raise a syntax error.
    """
    words = [w for w in re.split(r"\s+", raw.replace('"', " ")) if w]
    if not words:
        return None
    return " OR ".join(f'"{w}"' for w in words)


def add_message(sender_name, content, category="general", sender_phone=None,
                timestamp=None, group_id=DEFAULT_GROUP) -> int:
    ts = timestamp or datetime.utcnow().isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO messages (sender_name, sender_phone, content, category, timestamp, group_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sender_name, sender_phone, content, category, ts, group_id),
        )
        return cur.lastrowid


def search_messages(query: str, limit: int = 10, group_id: str = DEFAULT_GROUP) -> list[dict]:
    fts = _fts_query(query)
    if not fts:
        return []
    with _connect() as conn:
        rows = conn.execute(
            """SELECT m.id, m.sender_name, m.sender_phone, m.content, m.category, m.timestamp
               FROM messages_fts JOIN messages m ON messages_fts.rowid = m.id
               WHERE messages_fts MATCH ? AND m.group_id = ?
               ORDER BY rank LIMIT ?""",
            (fts, group_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_messages_by_category(category: str, limit: int = 50, group_id: str = DEFAULT_GROUP) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, sender_name, sender_phone, content, category, timestamp
               FROM messages WHERE category = ? AND group_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (category, group_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_messages(days: int = 7, limit: int = 200, group_id: str = DEFAULT_GROUP) -> list[dict]:
    cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0) - timedelta(days=days)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, sender_name, sender_phone, content, category, timestamp
               FROM messages WHERE timestamp >= ? AND group_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (cutoff.isoformat(), group_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_statistics(group_id: str = DEFAULT_GROUP) -> dict:
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE group_id = ?", (group_id,)).fetchone()[0]
        by_category = {row["category"]: row["cnt"] for row in conn.execute(
            "SELECT category, COUNT(*) AS cnt FROM messages WHERE group_id = ? GROUP BY category",
            (group_id,)).fetchall()}
        unique_senders = conn.execute(
            "SELECT COUNT(DISTINCT sender_name) FROM messages WHERE group_id = ?", (group_id,)).fetchone()[0]
        most_active = conn.execute(
            """SELECT sender_name, COUNT(*) AS cnt FROM messages WHERE group_id = ?
               GROUP BY sender_name ORDER BY cnt DESC LIMIT 5""", (group_id,)).fetchall()
        return {"total_messages": total, "unique_members": unique_senders,
                "by_category": by_category, "most_active_members": [dict(r) for r in most_active]}


def find_senders_by_topic(topic: str, limit: int = 10, group_id: str = DEFAULT_GROUP) -> list[dict]:
    rows = search_messages(topic, limit=limit, group_id=group_id)
    seen: dict[str, dict] = {}
    for r in rows:
        name = r["sender_name"]
        if name not in seen:
            seen[name] = {"sender_name": name, "sender_phone": r["sender_phone"], "snippets": []}
        seen[name]["snippets"].append(r["content"][:120])
    return list(seen.values())
