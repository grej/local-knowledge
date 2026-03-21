"""Real embedding tests using mlx_embeddings — requires Apple Silicon.

Run with: pixi run test:slow
"""

import pytest

from localknowledge.service import KnowledgeService

pytestmark = pytest.mark.slow

CORPUS = [
    ("Quantum Computing", "Quantum computing uses qubits and superposition to perform parallel computation on complex mathematical problems"),
    ("Pasta Recipes", "Italian pasta recipes with fresh basil, tomato sauce, and parmesan cheese for authentic Mediterranean cooking"),
    ("How Computers Work", "How transistors and silicon chips enable modern computers through binary logic gates and integrated circuits"),
    ("French Pastry", "The history of French pastry and baking techniques including croissants, eclairs, and mille-feuille"),
    ("Machine Learning", "Machine learning algorithms for natural language processing, including transformers, attention mechanisms, and neural networks"),
]


@pytest.fixture
def svc(tmp_path):
    """KnowledgeService with real mlx_embeddings."""
    service = KnowledgeService(base_dir=tmp_path)
    for title, content in CORPUS:
        service.add_text(content, title=title, source_type="article")
    return service


def test_semantic_search_computing(svc):
    """'how computers work' should rank computing docs above food docs."""
    results = svc.search("how computers work", mode="semantic")
    titles = [r.document.title for r in results]
    computing = {"Quantum Computing", "How Computers Work", "Machine Learning"}
    food = {"Pasta Recipes", "French Pastry"}
    # At least one computing doc in top 2
    assert titles[0] in computing or titles[1] in computing
    # No food doc in top 2
    assert titles[0] not in food
    assert titles[1] not in food


def test_semantic_search_cooking(svc):
    """'cooking food' should rank food docs above computing docs."""
    results = svc.search("cooking food", mode="semantic")
    titles = [r.document.title for r in results]
    food = {"Pasta Recipes", "French Pastry"}
    # Top result should be a food doc
    assert titles[0] in food


def test_hybrid_search_quantum(svc):
    """'quantum' should return quantum doc first (FTS exact + semantic boost)."""
    results = svc.search("quantum", mode="hybrid")
    assert results[0].document.title == "Quantum Computing"
    assert results[0].source == "hybrid"
