import json
import sqlite3
from pathlib import Path

from localknowledge.artifacts import ArtifactStore
from localknowledge.db import Database
from localknowledge.documents import DocumentStore
from localknowledge.tags import TagStore
from readcast_v2.migrate_v1 import migrate


def _insert_article(old_dir: Path, **overrides) -> str:
    """Insert a test article into the old readcast database."""
    defaults = {
        "id": "test-001",
        "title": "Test Article",
        "source_url": "https://example.com/test",
        "ingested_at": "2024-06-01T12:00:00+00:00",
        "word_count": 500,
        "estimated_read_min": 3,
        "language": "en",
        "status": "queued",
        "tags": "[]",
        "author": "Bob",
    }
    defaults.update(overrides)

    conn = sqlite3.connect(old_dir / "index.db")
    conn.execute(
        """
        INSERT INTO articles (id, title, source_url, ingested_at, word_count,
            estimated_read_min, language, status, tags, author)
        VALUES (:id, :title, :source_url, :ingested_at, :word_count,
            :estimated_read_min, :language, :status, :tags, :author)
        """,
        defaults,
    )
    # Add FTS content
    conn.execute(
        "INSERT INTO articles_fts_content (article_id, title, author, full_text) "
        "VALUES (?, ?, ?, ?)",
        (defaults["id"], defaults["title"], defaults.get("author"), f"Full text of {defaults['title']}"),
    )
    conn.commit()
    conn.close()
    return defaults["id"]


def test_empty_db(old_readcast_dir, tmp_path):
    new_dir = tmp_path / "new"
    stats = migrate(old_readcast_dir, new_dir)
    assert stats["articles"] == 0
    assert stats["artifacts"] == 0


def test_articles_migrate(old_readcast_dir, tmp_path):
    _insert_article(old_readcast_dir, id="a1", title="Article One", author="Alice")
    _insert_article(old_readcast_dir, id="a2", title="Article Two", author="Bob")

    new_dir = tmp_path / "new"
    stats = migrate(old_readcast_dir, new_dir)
    assert stats["articles"] == 2

    db = Database(new_dir)
    docs = DocumentStore(db)
    all_docs = docs.list()
    assert len(all_docs) == 2
    titles = {d.title for d in all_docs}
    assert titles == {"Article One", "Article Two"}

    doc = docs.get("a1")
    assert doc is not None
    assert doc.metadata["author"] == "Alice"
    assert doc.source_type == "article"


def test_audio_to_artifacts(old_readcast_dir, tmp_path):
    # Create article with audio
    article_dir = old_readcast_dir / "articles" / "audio-1"
    article_dir.mkdir(parents=True)
    (article_dir / "audio.mp3").write_bytes(b"fake mp3 data")

    _insert_article(
        old_readcast_dir,
        id="audio-1",
        title="Audio Article",
        status="done",
        audio_duration_sec="120.5",
    )
    # Update the audio_duration_sec directly since _insert_article uses defaults
    conn = sqlite3.connect(old_readcast_dir / "index.db")
    conn.execute(
        "UPDATE articles SET status='done', audio_duration_sec=120.5, voice='af_sky' WHERE id='audio-1'"
    )
    conn.commit()
    conn.close()

    new_dir = tmp_path / "new"
    stats = migrate(old_readcast_dir, new_dir)
    assert stats["articles"] == 1
    assert stats["artifacts"] == 1

    db = Database(new_dir)
    artifacts = ArtifactStore(db)
    doc_artifacts = artifacts.get_for_document("audio-1")
    assert len(doc_artifacts) == 1
    assert doc_artifacts[0]["artifact_type"] == "audio"
    assert doc_artifacts[0]["status"] == "done"


def test_tags_split(old_readcast_dir, tmp_path):
    _insert_article(
        old_readcast_dir,
        id="tagged-1",
        title="Tagged Article",
        tags=json.dumps(["python", "machine-learning"]),
    )

    new_dir = tmp_path / "new"
    stats = migrate(old_readcast_dir, new_dir)
    assert stats["tags"] == 2

    db = Database(new_dir)
    tags = TagStore(db)
    doc_tags = tags.get_document_tags("tagged-1")
    tag_names = {t["name"] for t in doc_tags}
    assert tag_names == {"python", "machine-learning"}


def test_idempotent_rerun(old_readcast_dir, tmp_path):
    _insert_article(old_readcast_dir, id="idem-1", title="Idempotent Test")

    new_dir = tmp_path / "new"
    stats1 = migrate(old_readcast_dir, new_dir)
    assert stats1["articles"] == 1

    stats2 = migrate(old_readcast_dir, new_dir)
    assert stats2["articles"] == 0
    assert stats2["skipped"] == 1

    db = Database(new_dir)
    docs = DocumentStore(db)
    assert len(docs.list()) == 1
