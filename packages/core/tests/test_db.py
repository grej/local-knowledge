import sqlite3
from contextlib import closing

import pytest

from localknowledge.db import Database


def test_creates_file(base_dir):
    db = Database(base_dir)
    assert db.db_path.exists()


def test_wal_mode(base_dir):
    db = Database(base_dir)
    with closing(db.connect()) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_migration_idempotent(base_dir):
    Database(base_dir)
    db2 = Database(base_dir)
    with closing(db2.connect()) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "documents" in tables


def test_migration_tracked(base_dir):
    db = Database(base_dir)
    with closing(db.connect()) as conn:
        versions = [
            row[0]
            for row in conn.execute("SELECT version FROM _migrations").fetchall()
        ]
    assert "v001_initial" in versions


def test_foreign_keys_enforced(base_dir):
    db = Database(base_dir)
    with closing(db.connect()) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO artifacts (id, document_id, artifact_type, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("a1", "nonexistent", "audio", "2024-01-01", "2024-01-01"),
            )
