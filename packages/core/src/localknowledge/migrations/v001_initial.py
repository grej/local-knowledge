"""Initial schema: documents, artifacts, tags, embeddings, FTS5."""

VERSION = "v001_initial"


def up(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id                  TEXT PRIMARY KEY,
            title               TEXT NOT NULL,
            content             TEXT,
            summary             TEXT,
            content_type        TEXT DEFAULT 'text/plain',
            language            TEXT,
            source_type         TEXT NOT NULL,
            source_uri          TEXT,
            canonical_uri       TEXT,
            source_product      TEXT NOT NULL,
            parent_document_id  TEXT,
            content_hash        TEXT,
            ingest_status       TEXT DEFAULT 'raw',
            metadata            TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            deleted_at          TEXT,
            FOREIGN KEY (parent_document_id) REFERENCES documents(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type);
        CREATE INDEX IF NOT EXISTS idx_documents_source_product ON documents(source_product);
        CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
        CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
        CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_document_id);
        CREATE INDEX IF NOT EXISTS idx_documents_not_deleted ON documents(deleted_at) WHERE deleted_at IS NULL;

        CREATE TABLE IF NOT EXISTS artifacts (
            id              TEXT PRIMARY KEY,
            document_id     TEXT NOT NULL,
            artifact_type   TEXT NOT NULL,
            path            TEXT,
            status          TEXT DEFAULT 'queued',
            metadata        TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_artifacts_document ON artifacts(document_id);
        CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
        CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);

        CREATE TABLE IF NOT EXISTS tags (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            slug        TEXT NOT NULL UNIQUE,
            parent_id   TEXT,
            description TEXT,
            color       TEXT,
            created_at  TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES tags(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS document_tags (
            document_id TEXT NOT NULL,
            tag_id      TEXT NOT NULL,
            confidence  REAL DEFAULT 1.0,
            source      TEXT DEFAULT 'user',
            created_at  TEXT NOT NULL,
            PRIMARY KEY (document_id, tag_id),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS embeddings_dense (
            document_id TEXT PRIMARY KEY,
            embedding   BLOB NOT NULL,
            model       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            title, content, summary,
            content='documents',
            content_rowid='rowid'
        );

        CREATE TRIGGER IF NOT EXISTS documents_fts_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, title, content, summary)
            VALUES (new.rowid, new.title, new.content, new.summary);
        END;

        CREATE TRIGGER IF NOT EXISTS documents_fts_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, title, content, summary)
            VALUES ('delete', old.rowid, old.title, old.content, old.summary);
        END;

        CREATE TRIGGER IF NOT EXISTS documents_fts_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, title, content, summary)
            VALUES ('delete', old.rowid, old.title, old.content, old.summary);
            INSERT INTO documents_fts(rowid, title, content, summary)
            VALUES (new.rowid, new.title, new.content, new.summary);
        END;
        """
    )
