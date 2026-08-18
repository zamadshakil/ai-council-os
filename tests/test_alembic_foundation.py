from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text


def test_initial_migration_builds_complete_schema(tmp_path):
    database_path = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    schema_check = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert schema_check.returncode == 0, schema_check.stdout + schema_check.stderr

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    expected = {
        "alembic_version", "users", "sessions", "tasks", "council_runs",
        "workflow_definitions", "workflow_runs", "external_items", "approvals",
        "audit_events", "outbox_events", "knowledge_documents",
        "council_integrations",
    }
    assert expected <= set(inspector.get_table_names())
    assert "version" in {column["name"] for column in inspector.get_columns("tasks")}
    engine.dispose()


def test_initial_migration_upgrades_legacy_task_schema(tmp_path):
    database_path = tmp_path / "legacy.db"
    legacy = create_engine(f"sqlite:///{database_path.as_posix()}")
    with legacy.begin() as connection:
        connection.execute(text("""
            CREATE TABLE tasks (
                task_id VARCHAR(50) PRIMARY KEY, council VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL, task_description TEXT NOT NULL,
                final_output TEXT NOT NULL, confidence_score FLOAT NOT NULL,
                iterations INTEGER NOT NULL, total_cost_usd FLOAT NOT NULL,
                debate_history JSON NOT NULL, context JSON NOT NULL,
                feedback_notes TEXT NOT NULL, error TEXT NOT NULL,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE seen_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, item_id VARCHAR(255) NOT NULL,
                source VARCHAR(100) NOT NULL, processed_at DATETIME NOT NULL,
                metadata_text TEXT NOT NULL
            )
        """))
        connection.execute(text(
            "INSERT INTO seen_items (item_id, source, processed_at, metadata_text) "
            "VALUES ('same', 'reddit', CURRENT_TIMESTAMP, ''), "
            "('same', 'reddit', CURRENT_TIMESTAMP, '')"
        ))
    legacy.dispose()

    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    upgraded = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(upgraded)
    assert "version" in {column["name"] for column in inspector.get_columns("tasks")}
    with upgraded.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM seen_items")).scalar_one() == 1
    upgraded.dispose()
