"""
dedup.py — Persistent Deduplication Store

Stores seen item IDs (Reddit post IDs, YouTube comment IDs, published content hashes)
in SQLite so deduplication survives server restarts.

Client requirement: "Every write action is preceded by a deduplication check. Non-negotiable."
"""

import sqlite3
import os
from datetime import datetime, timezone
from typing import List, Optional

DB_PATH = os.getenv("DEDUP_DB", "./data/dedup.db")


def _get_connection() -> sqlite3.Connection:
    """Get SQLite connection, creating the DB and table if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_items (
            item_id TEXT NOT NULL,
            source TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            metadata TEXT DEFAULT '',
            PRIMARY KEY (item_id, source)
        )
    """)
    conn.commit()
    return conn


def is_seen(item_id: str, source: str) -> bool:
    """
    Check if an item has already been processed.
    
    Args:
        item_id: The unique ID (e.g., Reddit post ID, YouTube comment ID)
        source: The source type (e.g., "reddit", "youtube_comment", "youtube_description")
    """
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT 1 FROM seen_items WHERE item_id = ? AND source = ?",
        (item_id, source)
    )
    result = cursor.fetchone() is not None
    conn.close()
    return result


def mark_seen(item_id: str, source: str, metadata: str = "") -> None:
    """
    Mark an item as processed.
    
    Args:
        item_id: The unique ID
        source: The source type
        metadata: Optional extra info (e.g., the subreddit name, video title)
    """
    conn = _get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO seen_items (item_id, source, processed_at, metadata) VALUES (?, ?, ?, ?)",
        (item_id, source, datetime.now(timezone.utc).isoformat(), metadata)
    )
    conn.commit()
    conn.close()


def filter_unseen(item_ids: List[str], source: str) -> List[str]:
    """
    Given a list of item IDs, return only the ones we haven't seen before.
    Efficient batch check.
    """
    if not item_ids:
        return []
    conn = _get_connection()
    placeholders = ",".join(["?"] * len(item_ids))
    cursor = conn.execute(
        f"SELECT item_id FROM seen_items WHERE source = ? AND item_id IN ({placeholders})",
        [source] + item_ids
    )
    seen = {row[0] for row in cursor.fetchall()}
    conn.close()
    return [iid for iid in item_ids if iid not in seen]


def mark_seen_batch(item_ids: List[str], source: str, metadata: str = "") -> None:
    """Mark multiple items as seen in one transaction."""
    if not item_ids:
        return
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_items (item_id, source, processed_at, metadata) VALUES (?, ?, ?, ?)",
        [(iid, source, now, metadata) for iid in item_ids]
    )
    conn.commit()
    conn.close()


def get_seen_count(source: Optional[str] = None) -> int:
    """Get total count of seen items, optionally filtered by source."""
    conn = _get_connection()
    if source:
        cursor = conn.execute("SELECT COUNT(*) FROM seen_items WHERE source = ?", (source,))
    else:
        cursor = conn.execute("SELECT COUNT(*) FROM seen_items")
    count = cursor.fetchone()[0]
    conn.close()
    return count
