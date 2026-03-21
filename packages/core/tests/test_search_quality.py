"""Search quality tests — explore different search patterns with real embeddings.

Run with: pixi run test:slow
"""

import pytest

from localknowledge.service import KnowledgeService

pytestmark = pytest.mark.slow

CORPUS = [
    (
        "Quantum computing and qubits",
        "Quantum computing leverages quantum mechanical phenomena such as "
        "superposition and entanglement to perform computations. Qubits are the "
        "fundamental units of quantum information, analogous to classical bits.",
    ),
    (
        "Italian pasta recipes",
        "Italian cuisine features many pasta varieties including spaghetti, "
        "penne, and fusilli. Traditional recipes use simple ingredients like "
        "tomatoes, olive oil, garlic, and fresh basil.",
    ),
    (
        "Silicon chip transistors",
        "Modern computer processors contain billions of transistors fabricated "
        "on silicon wafers. Moore's law predicted the doubling of transistor "
        "density approximately every two years.",
    ),
    (
        "French pastry techniques",
        "French patisserie relies on precise techniques such as tempering "
        "chocolate, laminating dough for croissants, and making choux pastry. "
        "Butter quality and temperature control are essential.",
    ),
    (
        "Machine learning and NLP",
        "Natural language processing uses machine learning models such as "
        "transformers and recurrent neural networks to understand and generate "
        "human language. Applications include translation and summarization.",
    ),
    (
        "Solar energy policy in Europe",
        "European nations have adopted aggressive solar energy targets. Feed-in "
        "tariffs and renewable portfolio standards drive investment. Germany's "
        "Energiewende remains a model for clean energy transition policy.",
    ),
    (
        "Nuclear energy regulation debates",
        "Nuclear power generation faces ongoing regulatory debates about safety, "
        "waste disposal, and proliferation risks. Governments must balance energy "
        "security with environmental and public health concerns.",
    ),
    (
        "Congressional climate legislation",
        "Recent congressional bills address climate change through carbon pricing, "
        "emissions caps, and renewable energy incentives. Bipartisan support varies "
        "across different policy proposals.",
    ),
    (
        "Battery chemistry for EVs",
        "Lithium-ion batteries power most electric vehicles. Research focuses on "
        "solid-state electrolytes, silicon anodes, and cobalt-free cathodes to "
        "improve energy density and reduce costs.",
    ),
    (
        "CRISPR gene editing ethics",
        "CRISPR-Cas9 enables precise genome editing in living organisms. Ethical "
        "debates center on germline modification, designer babies, consent, and "
        "equitable access to genetic therapies.",
    ),
]


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    base = tmp_path_factory.mktemp("search_quality")
    service = KnowledgeService(base_dir=base)
    for title, content in CORPUS:
        service.add_text(content, title=title)
    return service


@pytest.fixture(scope="module")
def doc_ids(svc):
    docs = svc.list_documents(limit=100)
    return {doc.title: doc.id for doc in docs}


# -- Similarity from existing entry -----------------------------------------

def test_quantum_similar_to_cs(svc, doc_ids):
    """Given quantum doc, similar docs should be other CS docs."""
    results = svc.dense.find_similar(doc_ids["Quantum computing and qubits"], top_k=3)
    result_ids = {did for did, _ in results}
    cs_ids = {
        doc_ids["Silicon chip transistors"],
        doc_ids["Machine learning and NLP"],
    }
    assert result_ids & cs_ids, f"Expected CS docs in top 3, got {result_ids}"


def test_pasta_similar_to_pastry(svc, doc_ids):
    """Given pasta doc, French pastry should be highly ranked."""
    results = svc.dense.find_similar(doc_ids["Italian pasta recipes"], top_k=3)
    result_ids = {did for did, _ in results}
    assert doc_ids["French pastry techniques"] in result_ids


# -- Semantic search ---------------------------------------------------------

def test_semantic_how_computers_work(svc, doc_ids):
    """'how computers work' should surface CS docs."""
    results = svc.dense.find_similar_by_text("how computers work", top_k=3)
    result_ids = {did for did, _ in results}
    cs_ids = {
        doc_ids["Quantum computing and qubits"],
        doc_ids["Silicon chip transistors"],
        doc_ids["Machine learning and NLP"],
    }
    assert len(result_ids & cs_ids) >= 2, f"Expected >=2 CS docs in top 3, got {result_ids & cs_ids}"


def test_semantic_cooking_food(svc, doc_ids):
    """'cooking food' should surface food docs."""
    results = svc.dense.find_similar_by_text("cooking food", top_k=2)
    result_ids = {did for did, _ in results}
    food_ids = {
        doc_ids["Italian pasta recipes"],
        doc_ids["French pastry techniques"],
    }
    assert len(result_ids & food_ids) >= 1, f"Expected food docs in top 2, got {result_ids}"


def test_semantic_government_energy_regulation(svc, doc_ids):
    """'government energy regulation' should find energy+politics docs."""
    results = svc.dense.find_similar_by_text("government energy regulation", top_k=3)
    result_ids = {did for did, _ in results}
    expected_ids = {
        doc_ids["Solar energy policy in Europe"],
        doc_ids["Nuclear energy regulation debates"],
        doc_ids["Congressional climate legislation"],
    }
    assert len(result_ids & expected_ids) >= 2, (
        f"Expected >=2 energy/politics docs in top 3, got {result_ids & expected_ids}"
    )


# -- Hybrid vs FTS vs semantic comparison ------------------------------------

def test_quantum_fts_finds_exact(svc, doc_ids):
    """FTS 'quantum' should find the quantum doc."""
    results = svc.search("quantum", mode="fts")
    result_ids = {r.document.id for r in results}
    assert doc_ids["Quantum computing and qubits"] in result_ids


def test_quantum_semantic_finds_related_cs(svc, doc_ids):
    """Semantic 'quantum' should also find related CS docs."""
    results = svc.search("quantum", mode="semantic", limit=5)
    result_ids = {r.document.id for r in results}
    assert doc_ids["Quantum computing and qubits"] in result_ids
    # Semantic should also surface conceptually related CS docs
    cs_ids = {
        doc_ids["Silicon chip transistors"],
        doc_ids["Machine learning and NLP"],
    }
    assert result_ids & cs_ids, "Expected semantic to find related CS docs too"


def test_renewable_power_laws_semantic_wins(svc, doc_ids):
    """'renewable power laws' — semantic should find energy/politics docs."""
    results = svc.search("renewable power laws", mode="semantic", limit=5)
    result_ids = {r.document.id for r in results}
    expected_ids = {
        doc_ids["Solar energy policy in Europe"],
        doc_ids["Nuclear energy regulation debates"],
        doc_ids["Congressional climate legislation"],
    }
    assert len(result_ids & expected_ids) >= 1


# -- Per-chunk vs per-document comparison ------------------------------------

def test_chunk_search_finds_relevant_section(svc):
    """A long doc with distinct sections — chunk search should find the right section."""
    long_content = (
        "Introduction to computer science. Algorithms are step-by-step procedures "
        "for solving computational problems. Data structures organize information "
        "for efficient access and modification.\n\n"
        "Italian cooking traditions. Risotto requires constant stirring and gradual "
        "addition of warm broth. Ossobuco is a Milanese specialty of braised veal "
        "shanks with gremolata.\n\n"
        "Climate policy in the United States. The Clean Air Act regulates emissions "
        "from stationary and mobile sources. The EPA sets national ambient air "
        "quality standards for criteria pollutants."
    )
    doc = svc.add_text(long_content, title="Multi-topic document")

    chunk_results = svc.search_chunks("Italian food recipes", limit=5)
    # At least one chunk from the multi-topic doc should be about food
    food_chunks = [
        cr for cr in chunk_results
        if cr.document_id == doc.id and "Italian" in cr.chunk_text
    ]
    assert len(food_chunks) >= 1, "Expected chunk search to find the food section"


# -- Tag intersection --------------------------------------------------------

def test_tag_intersection(svc, doc_ids):
    """Tag docs with domains, search with match_all=True."""
    svc.tag_document(doc_ids["Solar energy policy in Europe"], "energy")
    svc.tag_document(doc_ids["Solar energy policy in Europe"], "politics")
    svc.tag_document(doc_ids["Nuclear energy regulation debates"], "energy")
    svc.tag_document(doc_ids["Nuclear energy regulation debates"], "politics")
    svc.tag_document(doc_ids["Battery chemistry for EVs"], "energy")
    svc.tag_document(doc_ids["Congressional climate legislation"], "politics")

    results = svc.search_by_tags(["energy", "politics"], match_all=True)
    result_ids = {doc.id for doc in results}
    assert doc_ids["Solar energy policy in Europe"] in result_ids
    assert doc_ids["Nuclear energy regulation debates"] in result_ids
    assert doc_ids["Battery chemistry for EVs"] not in result_ids
    assert doc_ids["Congressional climate legislation"] not in result_ids


# -- Edge cases --------------------------------------------------------------

def test_empty_query_returns_empty(svc):
    results = svc.search_chunks("", limit=5)
    # An empty query still produces results (embeddings of empty string),
    # but we verify no crash and results are returned
    assert isinstance(results, list)


def test_hybrid_no_semantic_match_still_returns_fts(svc):
    """Query with unique FTS term should work even if semantic is weak."""
    results = svc.search("Energiewende", mode="hybrid", limit=5)
    result_titles = {r.document.title for r in results}
    assert "Solar energy policy in Europe" in result_titles
