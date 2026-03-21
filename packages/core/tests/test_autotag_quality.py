"""Quality tests for auto-tagging with real embeddings.

These tests use the actual embedding model, so they are slow.
Run with: pytest -m slow
"""

import numpy as np
import pytest

from localknowledge.embeddings.dense import cosine_similarity, embedding_from_bytes
from localknowledge.service import KnowledgeService

pytestmark = pytest.mark.slow


CORPUS = [
    ("Machine Learning Basics", "Machine learning is a subset of artificial intelligence that enables computers to learn from data without being explicitly programmed."),
    ("Neural Network Architecture", "Deep neural networks consist of multiple layers of neurons that transform input data through learned weights and activation functions."),
    ("Cooking Italian Pasta", "To cook perfect pasta, bring a large pot of salted water to a rolling boil, then add dried pasta and cook until al dente."),
    ("French Bread Baking", "Artisanal French bread requires a long fermentation process, high hydration dough, and baking in a steam-injected oven."),
    ("Quantum Computing Primer", "Quantum computers use qubits that can exist in superposition states, enabling parallel computation across exponentially many states."),
    ("Climate Change Effects", "Rising global temperatures are causing sea level rise, extreme weather events, and disruption to ecosystems worldwide."),
    ("Python Programming", "Python is a high-level programming language known for its readable syntax, extensive standard library, and strong community support."),
    ("Organic Chemistry", "Organic chemistry studies carbon-based compounds and their reactions, including synthesis, mechanisms, and spectroscopic analysis."),
    ("Stock Market Analysis", "Technical analysis of stock markets involves studying price charts, volume patterns, and statistical indicators to predict future price movements."),
    ("Mediterranean Diet", "The Mediterranean diet emphasizes fruits, vegetables, whole grains, olive oil, and lean proteins like fish, and has been linked to improved cardiovascular health."),
]


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    """Create a service with real embeddings and ingest the corpus."""
    base = tmp_path_factory.mktemp("quality")
    service = KnowledgeService(base_dir=base)
    for title, text in CORPUS:
        service.add_text(text, title=title)
    return service


def _score_topic_against_doc(svc, topic_text: str, doc_id: str) -> float:
    """Compute raw cosine similarity between topic label and doc chunks."""
    from contextlib import closing
    from localknowledge.embeddings.dense import TABLE

    topic_vec = np.array(svc.dense._embed_fn([topic_text])[0])
    with closing(svc.db.connect()) as conn:
        rows = conn.execute(
            f"SELECT embedding FROM {TABLE} WHERE document_id = ?", (doc_id,)
        ).fetchall()
    return max(
        cosine_similarity(topic_vec, np.array(embedding_from_bytes(r[0])))
        for r in rows
    )


def test_ml_topic_scores_higher_for_ml_docs(svc):
    """ML topic label should score higher against ML docs than cooking docs."""
    docs = svc.docs.list(limit=100)
    ml_doc = next(d for d in docs if d.title == "Machine Learning Basics")
    pasta_doc = next(d for d in docs if d.title == "Cooking Italian Pasta")

    label = "machine learning: AI, neural networks, deep learning"
    ml_score = _score_topic_against_doc(svc, label, ml_doc.id)
    pasta_score = _score_topic_against_doc(svc, label, pasta_doc.id)

    assert ml_score > pasta_score


def test_cooking_topic_scores_higher_for_food_docs(svc):
    """Cooking topic should score higher against food docs than tech docs."""
    docs = svc.docs.list(limit=100)
    pasta_doc = next(d for d in docs if d.title == "Cooking Italian Pasta")
    quantum_doc = next(d for d in docs if d.title == "Quantum Computing Primer")

    label = "cooking: food preparation, recipes, culinary arts"
    cooking_score = _score_topic_against_doc(svc, label, pasta_doc.id)
    quantum_score = _score_topic_against_doc(svc, label, quantum_doc.id)

    assert cooking_score > quantum_score


def test_unrelated_topic_low_score(svc):
    """An unrelated topic should score low against all documents."""
    docs = svc.docs.list(limit=100)
    quantum_doc = next(d for d in docs if d.title == "Quantum Computing Primer")

    label = "underwater basket weaving"
    score = _score_topic_against_doc(svc, label, quantum_doc.id)
    assert score < 0.7


def test_project_centroid_similarity(svc):
    """Documents in a project should be similar to the project centroid."""
    project = svc.tags.create_project("ai-research")
    docs = svc.docs.list(limit=100)
    ml_doc = next(d for d in docs if d.title == "Machine Learning Basics")
    nn_doc = next(d for d in docs if d.title == "Neural Network Architecture")

    svc.tags.tag_document(ml_doc.id, project["id"])
    svc.tags.tag_document(nn_doc.id, project["id"])
    svc.centroids.update_centroid(project["id"])

    # A tech doc should score higher than a cooking doc against the AI centroid
    py_doc = next(d for d in docs if d.title == "Python Programming")
    score = svc.centroids.score_document(py_doc.id, project["id"])
    assert score is not None

    pasta_doc = next(d for d in docs if d.title == "Cooking Italian Pasta")
    pasta_score = svc.centroids.score_document(pasta_doc.id, project["id"])
    assert pasta_score is not None
    assert score > pasta_score
