"""
memory_manager.py — 3-Layer Agent Memory System

Provides persistent memory across council sessions so agents can:
- Remember brand preferences and style rules (Layer 1: Preferences)
- Learn from approved/rejected outputs (Layer 2: Episodic)
- Cache reusable facts and knowledge snippets (Layer 3: Semantic)

Architecture:
    Layer 1 — Preferences DB (SQLite): Explicit brand rules, tone guides
    Layer 2 — Episodic DB (SQLite): Past approved/rejected task history
    Layer 3 — Semantic Cache (LanceDB): Vectorized knowledge for similarity lookup

Usage in council prompts:
    memory_context = await get_memory_context(task_description, council_name)
    # Returns formatted string ready to inject into system prompt
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR = Path("./data")
MEMORY_DB_PATH = DATA_DIR / "memory.db"
EPISODIC_LIMIT = 5  # Max past examples to inject per prompt
PREFERENCE_LIMIT = 10  # Max preferences to inject


# ── DB Init ───────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(MEMORY_DB_PATH), check_same_thread=False)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS preferences (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            council     TEXT DEFAULT 'all',
            key         TEXT NOT NULL,
            value       TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodic (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            council         TEXT NOT NULL,
            task_summary    TEXT NOT NULL,
            output_summary  TEXT NOT NULL,
            outcome         TEXT NOT NULL CHECK(outcome IN ('approved', 'rejected')),
            feedback_notes  TEXT DEFAULT '',
            confidence      REAL DEFAULT 0.0,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS guidelines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guideline   TEXT NOT NULL,
            council     TEXT DEFAULT 'all',
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    return conn


# ── Layer 1: Preferences ──────────────────────────────────────────────────

async def save_preference(key: str, value: str, council: str = "all") -> dict:
    """Save or update a brand preference/style rule."""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM preferences WHERE key = ? AND council = ?", (key, council)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE preferences SET value = ?, updated_at = datetime('now') WHERE id = ?",
            (value, existing[0])
        )
    else:
        conn.execute(
            "INSERT INTO preferences (key, value, council) VALUES (?, ?, ?)",
            (key, value, council)
        )
    conn.commit()
    return {"status": "saved", "key": key, "council": council}


async def get_preferences(council: str = "all") -> list[dict]:
    """Get all preferences for a council (includes global 'all' prefs)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT key, value, council, updated_at FROM preferences WHERE council IN (?, 'all') ORDER BY updated_at DESC LIMIT ?",
        (council, PREFERENCE_LIMIT)
    ).fetchall()
    return [{"key": r[0], "value": r[1], "council": r[2], "updated_at": r[3]} for r in rows]


# ── Layer 2: Episodic Memory ───────────────────────────────────────────────

async def store_episode(
    council: str,
    task_summary: str,
    output_summary: str,
    outcome: str,
    feedback_notes: str = "",
    confidence: float = 0.0,
) -> dict:
    """
    Store the result of a task as an episodic memory.
    Called automatically when a task is approved or rejected.
    """
    conn = _get_conn()
    conn.execute(
        """INSERT INTO episodic
           (council, task_summary, output_summary, outcome, feedback_notes, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (council, task_summary[:500], output_summary[:500],
         outcome, feedback_notes[:300], confidence)
    )
    conn.commit()
    return {"status": "stored", "outcome": outcome}


async def get_recent_episodes(council: str, outcome: str = "approved", limit: int = EPISODIC_LIMIT) -> list[dict]:
    """Get recent approved/rejected examples for a council."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT task_summary, output_summary, outcome, feedback_notes, confidence, created_at
           FROM episodic WHERE council = ? AND outcome = ?
           ORDER BY created_at DESC LIMIT ?""",
        (council, outcome, limit)
    ).fetchall()
    return [
        {
            "task": r[0], "output": r[1], "outcome": r[2],
            "feedback": r[3], "confidence": r[4], "date": r[5]
        }
        for r in rows
    ]


# ── Layer 3: Guidelines (semantic) ────────────────────────────────────────

async def get_guidelines(council: str = "all") -> list[dict]:
    """Get all brand guidelines."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, guideline, council, created_at FROM guidelines WHERE council IN (?, 'all') ORDER BY created_at DESC",
        (council,)
    ).fetchall()
    return [{"id": r[0], "guideline": r[1], "council": r[2], "created_at": r[3]} for r in rows]


async def add_guideline(guideline: str, council: str = "all") -> dict:
    """Add a new brand guideline."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO guidelines (guideline, council) VALUES (?, ?)", (guideline, council)
    )
    conn.commit()
    return {"status": "saved", "guideline": guideline}


async def delete_guideline(guideline_id: int) -> bool:
    """Remove a guideline."""
    conn = _get_conn()
    conn.execute("DELETE FROM guidelines WHERE id = ?", (guideline_id,))
    conn.commit()
    return True


# ── Context Builder ───────────────────────────────────────────────────────

async def get_memory_context(task_description: str, council: str = "all") -> str:
    """
    Build a memory context string to inject into council prompts.

    Combines:
    - Brand guidelines
    - Council-specific preferences
    - Recent approved examples (few-shot)
    - Recent rejected examples (negative examples)

    Returns empty string if no memory exists (graceful no-op).
    """
    try:
        parts = []

        # Guidelines
        guidelines = await get_guidelines(council)
        if guidelines:
            g_text = "\n".join(f"  • {g['guideline']}" for g in guidelines[:5])
            parts.append(f"[Brand Guidelines]\n{g_text}")

        # Preferences
        prefs = await get_preferences(council)
        if prefs:
            p_text = "\n".join(f"  {p['key']}: {p['value']}" for p in prefs[:5])
            parts.append(f"[Brand Preferences]\n{p_text}")

        # Approved examples (few-shot)
        approved = await get_recent_episodes(council, "approved", limit=2)
        if approved:
            ex_text = "\n\n".join(
                f"  Task: {e['task'][:150]}\n  Output: {e['output'][:200]}"
                for e in approved
            )
            parts.append(f"[Examples of Approved Outputs]\n{ex_text}")

        # Rejected examples (negative few-shot)
        rejected = await get_recent_episodes(council, "rejected", limit=1)
        if rejected:
            rej_text = "\n\n".join(
                f"  Task: {e['task'][:150]}\n  Rejected Output: {e['output'][:150]}\n  Reason: {e['feedback']}"
                for e in rejected
            )
            parts.append(f"[Examples of REJECTED Outputs — avoid these patterns]\n{rej_text}")

        if not parts:
            return ""

        header = "=== MEMORY CONTEXT (use this to improve your response) ==="
        return f"{header}\n\n" + "\n\n---\n\n".join(parts)

    except Exception as e:
        print(f"[Memory] Context retrieval failed (non-fatal): {e}")
        return ""


# ── Analytics ─────────────────────────────────────────────────────────────

async def get_memory_stats() -> dict:
    """Return memory statistics for the dashboard."""
    conn = _get_conn()
    prefs = conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
    episodes = conn.execute("SELECT COUNT(*) FROM episodic").fetchone()[0]
    approved = conn.execute("SELECT COUNT(*) FROM episodic WHERE outcome = 'approved'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM episodic WHERE outcome = 'rejected'").fetchone()[0]
    guidelines = conn.execute("SELECT COUNT(*) FROM guidelines").fetchone()[0]
    return {
        "preferences": prefs,
        "episodes_total": episodes,
        "episodes_approved": approved,
        "episodes_rejected": rejected,
        "guidelines": guidelines,
    }
