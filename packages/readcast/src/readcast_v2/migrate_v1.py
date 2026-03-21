"""Migrate readcast v1 (~/.readcast/index.db) to localknowledge core."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from localknowledge.artifacts import ArtifactStore
from localknowledge.db import Database
from localknowledge.documents import DocumentStore
from localknowledge.tags import TagStore

_STATUS_MAP = {
    "queued": "raw",
    "synthesizing": "processed",
    "done": "indexed",
    "error": "error",
}


def migrate(old_base_dir: Path, new_base_dir: Path) -> dict:
    """Migrate readcast v1 data to localknowledge core.

    Reads old DB at old_base_dir/index.db (read-only).
    Writes to new DB at new_base_dir/store.db via core stores.

    Returns dict with migration stats.
    """
    old_db_path = old_base_dir / "index.db"
    if not old_db_path.exists():
        return {"articles": 0, "artifacts": 0, "tags": 0, "skipped": 0}

    old_conn = sqlite3.connect(f"file:{old_db_path}?mode=ro", uri=True)
    old_conn.row_factory = sqlite3.Row

    db = Database(new_base_dir)
    docs = DocumentStore(db)
    artifacts = ArtifactStore(db)
    tags = TagStore(db)

    stats = {"articles": 0, "artifacts": 0, "tags": 0, "skipped": 0}

    try:
        rows = old_conn.execute(
            "SELECT * FROM articles ORDER BY ingested_at ASC"
        ).fetchall()

        for row in rows:
            article = dict(row)
            article_id = article["id"]

            full_text = _get_full_text(old_conn, article_id)

            content_for_hash = full_text or article.get("title", "")
            content_hash = hashlib.sha256(
                content_for_hash.encode("utf-8")
            ).hexdigest()

            existing = docs.get_by_content_hash(content_hash)
            if existing:
                stats["skipped"] += 1
                continue

            metadata: dict = {}
            for field in (
                "author", "publication", "published_date", "word_count",
                "estimated_read_min", "description", "image_url", "site_name",
                "voice", "tts_model", "speed", "audio_duration_sec",
                "listened_at", "listen_count", "listened_complete",
                "last_digested_at", "digest_status", "error_message", "source_file",
            ):
                value = article.get(field)
                if value is not None:
                    metadata[field] = value

            raw_tags = json.loads(article.get("tags") or "[]")
            if raw_tags:
                metadata["tags"] = raw_tags

            status = _STATUS_MAP.get(article.get("status", "queued"), "raw")
            doc = docs.create(
                title=article["title"],
                source_type="article",
                source_product="readcast",
                id=article_id,
                content=full_text,
                content_type="text/plain",
                language=article.get("language", "en"),
                source_uri=article.get("source_url"),
                canonical_uri=article.get("canonical_url"),
                content_hash=content_hash,
                ingest_status=status,
                metadata=metadata,
            )
            stats["articles"] += 1

            if article.get("status") == "done" and article.get("audio_duration_sec"):
                audio_meta = {
                    "voice": article.get("voice"),
                    "tts_model": article.get("tts_model"),
                    "speed": article.get("speed"),
                    "duration_sec": article.get("audio_duration_sec"),
                }
                audio_path = _find_audio_file(old_base_dir, article_id)
                artifacts.create(
                    document_id=doc.id,
                    artifact_type="audio",
                    path=audio_path,
                    status="done",
                    metadata=audio_meta,
                )
                stats["artifacts"] += 1

            for tag_name in raw_tags:
                tag = tags.get_or_create(tag_name)
                tags.tag_document(doc.id, tag["id"])
                stats["tags"] += 1

            _copy_article_files(old_base_dir, new_base_dir, article_id)

    finally:
        old_conn.close()

    return stats


def _get_full_text(conn: sqlite3.Connection, article_id: str) -> str | None:
    """Read full text from FTS content table."""
    try:
        row = conn.execute(
            "SELECT full_text FROM articles_fts_content WHERE article_id = ?",
            (article_id,),
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _find_audio_file(old_base_dir: Path, article_id: str) -> str | None:
    """Find the audio file for an article."""
    article_dir = old_base_dir / "articles" / article_id
    if not article_dir.exists():
        return None
    for ext in (".mp3", ".m4a", ".wav"):
        candidate = article_dir / f"audio{ext}"
        if candidate.exists():
            return str(candidate)
    return None


def _copy_article_files(
    old_base_dir: Path, new_base_dir: Path, article_id: str
) -> None:
    """Copy article directory from old to new location."""
    old_dir = old_base_dir / "articles" / article_id
    if not old_dir.exists():
        return
    new_dir = new_base_dir / "documents" / article_id
    if new_dir.exists():
        return
    new_dir.mkdir(parents=True, exist_ok=True)
    for item in old_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, new_dir / item.name)
