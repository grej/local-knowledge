"""Tests for CentroidStore."""

import numpy as np

from localknowledge.centroids import CentroidStore
from localknowledge.db import Database
from localknowledge.documents import DocumentStore
from localknowledge.embeddings.dense import DenseBackend
from localknowledge.tags import TagStore


def _deterministic_embed(texts):
    """Deterministic mock embedding based on text hash."""
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


def _setup(tmp_path):
    db = Database(tmp_path)
    docs = DocumentStore(db)
    tags = TagStore(db)
    dense = DenseBackend(db, embed_fn=_deterministic_embed)
    centroids = CentroidStore(db, dense)
    return db, docs, tags, dense, centroids


def test_compute_centroid_single_doc(tmp_path):
    db, docs, tags, dense, centroids = _setup(tmp_path)

    project = tags.create_project("alpha")
    doc = docs.create(title="Doc A", source_type="note", source_product="lk", content="Hello world")
    dense.embed_document_chunked(doc.id, "Hello world")
    tags.tag_document(doc.id, project["id"])

    centroid = centroids.compute_centroid(project["id"])
    assert centroid is not None
    assert len(centroid) == 384


def test_compute_centroid_multiple_docs(tmp_path):
    db, docs, tags, dense, centroids = _setup(tmp_path)

    project = tags.create_project("beta")
    for i, text in enumerate(["Machine learning basics", "Deep neural networks"]):
        doc = docs.create(title=f"Doc {i}", source_type="note", source_product="lk", content=text)
        dense.embed_document_chunked(doc.id, text)
        tags.tag_document(doc.id, project["id"])

    centroid = centroids.compute_centroid(project["id"])
    assert centroid is not None
    # Centroid should be normalized
    norm = np.linalg.norm(centroid)
    assert abs(norm - 1.0) < 0.01


def test_compute_centroid_empty(tmp_path):
    db, docs, tags, dense, centroids = _setup(tmp_path)

    project = tags.create_project("empty")
    centroid = centroids.compute_centroid(project["id"])
    assert centroid is None


def test_update_and_retrieve_centroid(tmp_path):
    db, docs, tags, dense, centroids = _setup(tmp_path)

    project = tags.create_project("gamma")
    doc = docs.create(title="Test", source_type="note", source_product="lk", content="Test content")
    dense.embed_document_chunked(doc.id, "Test content")
    tags.tag_document(doc.id, project["id"])

    assert centroids.update_centroid(project["id"]) is True
    retrieved = centroids.get_centroid(project["id"])
    assert retrieved is not None
    assert len(retrieved) == 384


def test_score_document_against_centroid(tmp_path):
    db, docs, tags, dense, centroids = _setup(tmp_path)

    project = tags.create_project("delta")
    doc1 = docs.create(title="Project Doc", source_type="note", source_product="lk", content="Neural network training")
    dense.embed_document_chunked(doc1.id, "Neural network training")
    tags.tag_document(doc1.id, project["id"])
    centroids.update_centroid(project["id"])

    doc2 = docs.create(title="Candidate", source_type="note", source_product="lk", content="Deep learning optimization")
    dense.embed_document_chunked(doc2.id, "Deep learning optimization")

    score = centroids.score_document(doc2.id, project["id"])
    assert score is not None
    assert 0.0 <= score <= 1.0


def test_update_all_centroids(tmp_path):
    db, docs, tags, dense, centroids = _setup(tmp_path)

    for name in ["proj-a", "proj-b"]:
        project = tags.create_project(name)
        doc = docs.create(title=f"Doc for {name}", source_type="note", source_product="lk", content=f"Content for {name}")
        dense.embed_document_chunked(doc.id, f"Content for {name}")
        tags.tag_document(doc.id, project["id"])

    count = centroids.update_all_centroids()
    assert count == 2


def test_centroid_survives_migration(tmp_path):
    """Verify project_centroids table is usable after migration."""
    db, docs, tags, dense, centroids = _setup(tmp_path)

    project = tags.create_project("persist")
    doc = docs.create(title="Persist", source_type="note", source_product="lk", content="Persistent data")
    dense.embed_document_chunked(doc.id, "Persistent data")
    tags.tag_document(doc.id, project["id"])
    centroids.update_centroid(project["id"])

    # Re-open database (simulates restart)
    db2 = Database(tmp_path)
    dense2 = DenseBackend(db2, embed_fn=_deterministic_embed)
    centroids2 = CentroidStore(db2, dense2)

    retrieved = centroids2.get_centroid(project["id"])
    assert retrieved is not None
    assert len(retrieved) == 384
