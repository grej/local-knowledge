"""Upgrade embeddings_dense to chunk-aware embeddings_dense_v2."""

VERSION = "v002_chunk_embeddings"


def up(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS embeddings_dense_v2 (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id     TEXT NOT NULL,
            chunk_index     INTEGER NOT NULL DEFAULT 0,
            chunk_text      TEXT,
            chunk_start     INTEGER,
            chunk_end       INTEGER,
            embedding       BLOB NOT NULL,
            model           TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            UNIQUE(document_id, chunk_index),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_embeddings_dense_v2_doc
            ON embeddings_dense_v2(document_id);

        -- Migrate existing data from embeddings_dense (one row per doc -> chunk_index=0)
        INSERT OR IGNORE INTO embeddings_dense_v2
            (document_id, chunk_index, embedding, model, created_at)
        SELECT document_id, 0, embedding, model, created_at
        FROM embeddings_dense;

        DROP TABLE IF EXISTS embeddings_dense;
        """
    )
