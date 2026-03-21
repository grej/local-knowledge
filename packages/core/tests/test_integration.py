"""Integration tests — verify all core modules compose correctly."""

import numpy as np

from localknowledge.artifacts import ArtifactStore
from localknowledge.documents import DocumentStore
from localknowledge.embeddings.dense import DenseBackend
from localknowledge.tags import TagStore


def _mock_embed(texts):
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


def test_full_pipeline(db):
    """Create -> tag -> embed -> search -> delete pipeline."""
    docs = DocumentStore(db)
    tags = TagStore(db)
    embeddings = DenseBackend(db, embed_fn=_mock_embed)

    # Create
    doc = docs.create(
        title="Quantum Computing Basics",
        source_type="article",
        source_product="readcast",
        content="Quantum computing uses qubits and superposition for parallel computation",
    )

    # Tag
    tag = tags.get_or_create("Physics")
    tags.tag_document(doc.id, tag["id"])
    doc_tags = tags.get_document_tags(doc.id)
    assert len(doc_tags) == 1

    # Embed
    embeddings.embed_document(doc.id, doc.content)
    results = embeddings.find_similar_by_text("quantum superposition", top_k=5)
    assert len(results) == 1
    assert results[0][0] == doc.id

    # Search (FTS)
    fts_results = docs.search("quantum")
    assert len(fts_results) == 1

    # Soft delete
    docs.delete(doc.id)
    assert docs.get(doc.id) is None
    assert docs.get(doc.id, include_deleted=True) is not None

    # Search excludes deleted
    fts_results = docs.search("quantum")
    assert len(fts_results) == 0


def test_artifact_cascade(db):
    """Delete document cascades to artifacts."""
    docs = DocumentStore(db)
    artifacts = ArtifactStore(db)

    doc = docs.create(
        title="Audio Test", source_type="article", source_product="readcast"
    )
    a1 = artifacts.create(doc.id, "audio", path="/tmp/audio.mp3")
    a2 = artifacts.create(doc.id, "transcript", path="/tmp/transcript.txt")

    docs.delete(doc.id, hard=True)
    assert artifacts.get(a1["id"]) is None
    assert artifacts.get(a2["id"]) is None


def test_soft_delete_preserves_references(db):
    """Soft delete keeps document accessible for cross-product safety."""
    docs = DocumentStore(db)
    artifacts = ArtifactStore(db)
    tags_store = TagStore(db)

    doc = docs.create(
        title="Shared Doc", source_type="article", source_product="readcast"
    )
    artifacts.create(doc.id, "audio")
    tag = tags_store.get_or_create("Important")
    tags_store.tag_document(doc.id, tag["id"])

    # Soft delete
    docs.delete(doc.id)

    # Still accessible with include_deleted
    deleted_doc = docs.get(doc.id, include_deleted=True)
    assert deleted_doc is not None
    assert deleted_doc.deleted_at is not None

    # Artifacts still exist
    doc_artifacts = artifacts.get_for_document(doc.id)
    assert len(doc_artifacts) == 1

    # Tags still exist
    doc_tags = tags_store.get_document_tags(doc.id)
    assert len(doc_tags) == 1
