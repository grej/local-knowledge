"""Tests for hybrid search (mocked)."""

import numpy as np

from localknowledge.documents import DocumentStore
from localknowledge.embeddings.dense import DenseBackend
from localknowledge.embeddings.hybrid import HybridSearch


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


def test_rrf_fusion(db):
    docs_store = DocumentStore(db)
    doc1 = docs_store.create(
        title="Neural Networks", source_type="article", source_product="readcast",
        content="Deep learning neural networks and backpropagation",
    )
    doc2 = docs_store.create(
        title="Brain Science", source_type="article", source_product="readcast",
        content="Neuroscience and the human brain neural connections",
    )

    dense = DenseBackend(db, embed_fn=_mock_embed)
    dense.embed_document(doc1.id, doc1.content)
    dense.embed_document(doc2.id, doc2.content)

    hybrid = HybridSearch(docs_store, dense)
    results = hybrid.search("neural")
    assert len(results) >= 1
    result_ids = {doc.id for doc in results}
    assert doc1.id in result_ids or doc2.id in result_ids


def test_fts_only_fallback(db):
    docs_store = DocumentStore(db)
    docs_store.create(
        title="Python Programming", source_type="article", source_product="readcast",
        content="Python is a great programming language",
    )

    hybrid = HybridSearch(docs_store, dense_backend=None)
    results = hybrid.search("Python")
    assert len(results) == 1
    assert results[0].title == "Python Programming"
