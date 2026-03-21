import sqlite3

import pytest

from localknowledge.db import Database

READCAST_V1_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    source_url TEXT,
    source_file TEXT,
    title TEXT NOT NULL,
    author TEXT,
    publication TEXT,
    published_date TEXT,
    ingested_at TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    estimated_read_min INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    image_url TEXT,
    canonical_url TEXT,
    site_name TEXT,
    language TEXT NOT NULL DEFAULT 'en',
    status TEXT NOT NULL DEFAULT 'queued',
    error_message TEXT,
    audio_duration_sec REAL,
    voice TEXT,
    tts_model TEXT,
    speed REAL,
    tags TEXT NOT NULL DEFAULT '[]',
    listened_at TEXT,
    listen_count INTEGER DEFAULT 0,
    listened_complete INTEGER DEFAULT 0,
    last_digested_at TEXT,
    digest_status TEXT
);

CREATE TABLE IF NOT EXISTS articles_fts_content (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT NOT NULL,
    title TEXT,
    author TEXT,
    publication TEXT,
    full_text TEXT
);
"""


@pytest.fixture
def base_dir(tmp_path):
    return tmp_path


@pytest.fixture
def db(base_dir):
    return Database(base_dir)


@pytest.fixture
def old_readcast_dir(tmp_path):
    """Create a mock readcast v1 directory with schema."""
    old_dir = tmp_path / "old_readcast"
    old_dir.mkdir()
    conn = sqlite3.connect(old_dir / "index.db")
    conn.executescript(READCAST_V1_SCHEMA)
    conn.close()
    return old_dir
