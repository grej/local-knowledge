"""Tests for dense embedding backend (mocked ML)."""

from contextlib import closing

import numpy as np

from localknowledge.chunker import Chunk
from localknowledge.documents import DocumentStore
from localknowledge.embeddings.dense import DenseBackend, TABLE, embedding_from_bytes


def _mock_embed(texts):
    """Return deterministic embeddings based on text content."""
    results = []
    for text in texts:
        vec = np.zeros(384)
        for i, char in enumerate(text[:384]):
            vec[i % 384] += ord(char)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        results.append(vec.tolist())
    return results


def test_embed_and_retrieve(db):
    docs = DocumentStore(db)
    doc1 = docs.create(
        title="ML Paper", source_type="article", source_product="readcast",
        content="Machine learning and neural networks",
    )
    doc2 = docs.create(
        title="Cooking", source_type="article", source_product="readcast",
        content="Pasta recipes and Italian food",
    )

    backend = DenseBackend(db, embed_fn=_mock_embed)
    backend.embed_document(doc1.id, doc1.content)
    backend.embed_document(doc2.id, doc2.content)

    results = backend.find_similar_by_text("neural network deep learning", top_k=5)
    assert len(results) == 2
    assert all(isinstance(score, float) for _, score in results)


def test_remove(db):
    docs = DocumentStore(db)
    doc = docs.create(
        title="To Remove", source_type="article", source_product="readcast",
        content="Temporary content",
    )

    backend = DenseBackend(db, embed_fn=_mock_embed)
    backend.embed_document(doc.id, doc.content)

    with closing(db.connect()) as conn:
        row = conn.execute(
            f"SELECT * FROM {TABLE} WHERE document_id = ?", (doc.id,)
        ).fetchone()
    assert row is not None

    backend.remove(doc.id)

    with closing(db.connect()) as conn:
        row = conn.execute(
            f"SELECT * FROM {TABLE} WHERE document_id = ?", (doc.id,)
        ).fetchone()
    assert row is None


def test_model_tracking(db):
    docs = DocumentStore(db)
    doc = docs.create(
        title="Test", source_type="article", source_product="readcast",
        content="Test content",
    )

    backend = DenseBackend(db, model_name="test-model-v1", embed_fn=_mock_embed)
    backend.embed_document(doc.id, doc.content)

    with closing(db.connect()) as conn:
        row = conn.execute(
            f"SELECT model FROM {TABLE} WHERE document_id = ?", (doc.id,)
        ).fetchone()
    assert row[0] == "test-model-v1"


def test_embed_document_chunked(db):
    docs = DocumentStore(db)
    doc = docs.create(
        title="Multi-chunk", source_type="article", source_product="readcast",
        content="Chunk one about ML.\n\nChunk two about cooking.",
    )

    chunks = [
        Chunk(text="Chunk one about ML.", start=0, end=19, index=0),
        Chunk(text="Chunk two about cooking.", start=21, end=45, index=1),
    ]

    backend = DenseBackend(db, embed_fn=_mock_embed)
    backend.embed_document_chunked(doc.id, doc.content, chunks=chunks)

    with closing(db.connect()) as conn:
        rows = conn.execute(
            f"SELECT * FROM {TABLE} WHERE document_id = ? ORDER BY chunk_index",
            (doc.id,),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["chunk_index"] == 0
    assert rows[1]["chunk_index"] == 1
    assert rows[0]["chunk_text"] == "Chunk one about ML."
    assert rows[1]["chunk_text"] == "Chunk two about cooking."


def test_embed_document_chunked_auto(db):
    """Auto-chunking when no explicit chunks given."""
    docs = DocumentStore(db)
    content = "First paragraph about science.\n\nSecond paragraph about food."
    doc = docs.create(
        title="Auto-chunk", source_type="article", source_product="readcast",
        content=content,
    )

    backend = DenseBackend(db, embed_fn=_mock_embed)
    backend.embed_document_chunked(doc.id, content)

    with closing(db.connect()) as conn:
        rows = conn.execute(
            f"SELECT * FROM {TABLE} WHERE document_id = ?", (doc.id,),
        ).fetchall()
    assert len(rows) >= 1


def test_find_similar_chunks(db):
    docs = DocumentStore(db)
    doc = docs.create(
        title="Multi-topic", source_type="article", source_product="readcast",
        content="ML content.\n\nFood content.",
    )

    chunks = [
        Chunk(text="ML content about neural networks.", start=0, end=33, index=0),
        Chunk(text="Food content about pasta recipes.", start=35, end=68, index=1),
    ]

    backend = DenseBackend(db, embed_fn=_mock_embed)
    backend.embed_document_chunked(doc.id, doc.content, chunks=chunks)

    results = backend.find_similar_chunks("neural networks", top_k=5)
    assert len(results) == 2
    assert results[0].document_id == doc.id
    assert results[0].chunk_index in (0, 1)


def test_find_similar_aggregates_chunks(db):
    """find_similar_by_text returns max similarity per document across chunks."""
    docs = DocumentStore(db)
    doc = docs.create(
        title="Multi-chunk", source_type="article", source_product="readcast",
        content="About ML.\n\nAbout food.",
    )

    chunks = [
        Chunk(text="About ML and neural networks.", start=0, end=28, index=0),
        Chunk(text="About food and pasta.", start=30, end=51, index=1),
    ]

    backend = DenseBackend(db, embed_fn=_mock_embed)
    backend.embed_document_chunked(doc.id, doc.content, chunks=chunks)

    results = backend.find_similar_by_text("neural networks", top_k=5)
    # Should aggregate to one result per document
    assert len(results) == 1
    assert results[0][0] == doc.id


def test_replaces_old_embeddings_on_re_embed(db):
    """Re-embedding a document replaces old chunks."""
    docs = DocumentStore(db)
    doc = docs.create(
        title="Re-embed", source_type="article", source_product="readcast",
        content="Original content",
    )

    backend = DenseBackend(db, embed_fn=_mock_embed)
    backend.embed_document(doc.id, doc.content)

    with closing(db.connect()) as conn:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE document_id = ?", (doc.id,)
        ).fetchone()[0]
    assert count == 1

    chunks = [
        Chunk(text="New chunk one.", start=0, end=14, index=0),
        Chunk(text="New chunk two.", start=16, end=30, index=1),
    ]
    backend.embed_document_chunked(doc.id, "New chunk one.\n\nNew chunk two.", chunks=chunks)

    with closing(db.connect()) as conn:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE document_id = ?", (doc.id,)
        ).fetchone()[0]
    assert count == 2
