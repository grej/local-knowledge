"""Database connection management and migration system."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import logging
from pathlib import Path
import sqlite3

log = logging.getLogger(__name__)


class Database:
    """SQLite database with WAL mode, migration tracking, and connection management."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "store.db"
        self._initialize()

    def _initialize(self) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            self._run_migrations(conn)

    def connect(self) -> sqlite3.Connection:
        """Open a new connection with standard PRAGMAs applied."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        from localknowledge.migrations import ALL_MIGRATIONS

        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM _migrations").fetchall()
        }

        for migration in ALL_MIGRATIONS:
            if migration.VERSION in applied:
                continue
            log.info("Applying migration %s", migration.VERSION)
            migration.up(conn)
            conn.execute(
                "INSERT INTO _migrations (version, applied_at) VALUES (?, ?)",
                (migration.VERSION, datetime.now(UTC).isoformat()),
            )
            conn.commit()
