"""Add tag_type column and project_centroids table."""

VERSION = "v003_tag_type_and_centroids"


def up(conn):
    conn.executescript(
        """
        ALTER TABLE tags ADD COLUMN tag_type TEXT NOT NULL DEFAULT 'topic';
        CREATE INDEX IF NOT EXISTS idx_tags_tag_type ON tags(tag_type);

        CREATE TABLE IF NOT EXISTS project_centroids (
            tag_id      TEXT PRIMARY KEY,
            embedding   BLOB NOT NULL,
            model       TEXT NOT NULL,
            doc_count   INTEGER NOT NULL DEFAULT 0,
            updated_at  TEXT NOT NULL,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );
        """
    )
