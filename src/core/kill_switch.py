"""
kill_switch.py — Global Kill Switch

A single stored flag checked at the top of every workflow.
If ON, all workflows exit immediately without processing.

Controllable via:
- Telegram bot commands (/kill, /resume)
- Dashboard API endpoint
- Direct function call

Storage: SQLite file (survives restarts). Upgradeable to Postgres.
"""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.getenv("KILL_SWITCH_DB", "./data/kill_switch.db")


def _get_connection() -> sqlite3.Connection:
    """Get SQLite connection, creating the DB and table if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kill_switch (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            is_active INTEGER NOT NULL DEFAULT 0,
            toggled_by TEXT NOT NULL DEFAULT 'system',
            toggled_at TEXT NOT NULL,
            reason TEXT DEFAULT ''
        )
    """)
    # Ensure exactly one row exists
    cursor = conn.execute("SELECT COUNT(*) FROM kill_switch")
    if cursor.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO kill_switch (id, is_active, toggled_by, toggled_at) VALUES (1, 0, 'system', ?)",
            (datetime.now(timezone.utc).isoformat(),)
        )
        conn.commit()
    return conn


def is_killed() -> bool:
    """Check if the kill switch is active. Call this at the top of every workflow."""
    conn = _get_connection()
    cursor = conn.execute("SELECT is_active FROM kill_switch WHERE id = 1")
    result = cursor.fetchone()
    conn.close()
    return bool(result[0]) if result else False


def activate(toggled_by: str = "telegram", reason: str = "") -> None:
    """Activate the kill switch — all workflows will stop."""
    conn = _get_connection()
    conn.execute(
        "UPDATE kill_switch SET is_active = 1, toggled_by = ?, toggled_at = ?, reason = ? WHERE id = 1",
        (toggled_by, datetime.now(timezone.utc).isoformat(), reason)
    )
    conn.commit()
    conn.close()
    print(f"🛑 [Kill Switch] ACTIVATED by {toggled_by}. Reason: {reason}")


def deactivate(toggled_by: str = "telegram") -> None:
    """Deactivate the kill switch — workflows will resume."""
    conn = _get_connection()
    conn.execute(
        "UPDATE kill_switch SET is_active = 0, toggled_by = ?, toggled_at = ? WHERE id = 1",
        (toggled_by, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    print(f"✅ [Kill Switch] DEACTIVATED by {toggled_by}. Workflows resumed.")


def get_status() -> dict:
    """Get full kill switch status."""
    conn = _get_connection()
    cursor = conn.execute("SELECT is_active, toggled_by, toggled_at, reason FROM kill_switch WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "is_active": bool(row[0]),
            "toggled_by": row[1],
            "toggled_at": row[2],
            "reason": row[3],
        }
    return {"is_active": False, "toggled_by": "system", "toggled_at": "", "reason": ""}
