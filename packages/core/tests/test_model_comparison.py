"""Multi-model embedding comparison — same corpus, side-by-side metrics.

Run with: pixi run test:slow -s  (to see the comparison table)
"""

import pytest

from localknowledge.service import KnowledgeService

pytestmark = pytest.mark.slow

MODEL_A = "BAAI/bge-small-en-v1.5"   # 384d, ~33M params
MODEL_B = "BAAI/bge-large-en-v1.5"   # 1024d, ~335M params

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

QUERIES = [
    {
        "query": "how computers work",
        "expected_top": {"Quantum computing and qubits", "Silicon chip transistors"},
        "expected_relevant": {
            "Quantum computing and qubits",
            "Silicon chip transistors",
            "Machine learning and NLP",
        },
    },
    {
        "query": "government energy regulation",
        "expected_top": {"Solar energy policy in Europe", "Nuclear energy regulation debates"},
        "expected_relevant": {
            "Solar energy policy in Europe",
            "Nuclear energy regulation debates",
            "Congressional climate legislation",
        },
    },
    {
        "query": "cooking food recipes",
        "expected_top": {"Italian pasta recipes", "French pastry techniques"},
        "expected_relevant": {"Italian pasta recipes", "French pastry techniques"},
    },
    {
        "query": "gene editing biotechnology",
        "expected_top": {"CRISPR gene editing ethics"},
        "expected_relevant": {"CRISPR gene editing ethics"},
    },
    {
        "query": "electric vehicle batteries",
        "expected_top": {"Battery chemistry for EVs"},
        "expected_relevant": {"Battery chemistry for EVs"},
    },
]


def _build_service(tmp_path, model_name):
    """Build a KnowledgeService with a specific embedding model."""
    base = tmp_path / model_name.replace("/", "_")
    base.mkdir(parents=True, exist_ok=True)
    svc = KnowledgeService(base_dir=base)
    svc.config.embeddings.model = model_name
    # Rebuild dense backend with the correct model
    from localknowledge.embeddings.dense import DenseBackend
    svc.dense = DenseBackend(svc.db, model_name=model_name)
    from localknowledge.embeddings.hybrid import HybridSearch
    svc.hybrid = HybridSearch(svc.docs, svc.dense)
    for title, content in CORPUS:
        doc = svc.docs.create(
            title=title, source_type="article", source_product="lk", content=content
        )
        svc.dense.embed_document_chunked(doc.id, content)
    return svc


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    base = tmp_path_factory.mktemp("model_comparison")
    svc_a = _build_service(base, MODEL_A)
    svc_b = _build_service(base, MODEL_B)
    return {MODEL_A: svc_a, MODEL_B: svc_b}


def _title_map(svc):
    """Map title → doc_id."""
    docs = svc.list_documents(limit=100)
    return {doc.title: doc.id for doc in docs}


def _mrr(ranked_titles, expected_top):
    """Mean Reciprocal Rank: 1/(rank of first expected hit)."""
    for i, title in enumerate(ranked_titles, start=1):
        if title in expected_top:
            return 1.0 / i
    return 0.0


def _recall_at_k(ranked_titles, expected_relevant, k=3):
    """Fraction of expected_relevant found in top-k."""
    top_k = set(ranked_titles[:k])
    if not expected_relevant:
        return 1.0
    return len(top_k & expected_relevant) / len(expected_relevant)


def _run_query(svc, query, limit=5):
    """Run semantic search and return ranked titles."""
    results = svc.search(query, mode="semantic", limit=limit)
    return [r.document.title for r in results]


def test_both_models_produce_results(services):
    """Sanity: both models return non-empty results for every query."""
    for q in QUERIES:
        for model_name, svc in services.items():
            results = _run_query(svc, q["query"])
            assert len(results) > 0, f"{model_name} returned no results for '{q['query']}'"


def test_comparison_table(services, capsys):
    """Run all queries, compute metrics, print comparison table."""
    rows = []
    for q in QUERIES:
        row = {"query": q["query"]}
        for model_name, svc in services.items():
            titles = _run_query(svc, q["query"])
            mrr = _mrr(titles, q["expected_top"])
            recall = _recall_at_k(titles, q["expected_relevant"], k=3)
            short = model_name.split("/")[-1]
            row[f"{short}_mrr"] = mrr
            row[f"{short}_recall"] = recall
            row[f"{short}_top3"] = titles[:3]
        rows.append(row)

    # Print comparison table
    print("\n" + "=" * 100)
    print("MODEL COMPARISON: Semantic Search Quality")
    print("=" * 100)

    model_a_short = MODEL_A.split("/")[-1]
    model_b_short = MODEL_B.split("/")[-1]

    header = f"{'Query':<35} {'Metric':<10} {model_a_short:<20} {model_b_short:<20} {'Winner':<15}"
    print(header)
    print("-" * 100)

    a_wins = 0
    b_wins = 0

    for row in rows:
        query = row["query"][:33]
        a_mrr = row[f"{model_a_short}_mrr"]
        b_mrr = row[f"{model_b_short}_mrr"]
        a_recall = row[f"{model_a_short}_recall"]
        b_recall = row[f"{model_b_short}_recall"]

        mrr_winner = model_a_short if a_mrr > b_mrr else model_b_short if b_mrr > a_mrr else "tie"
        recall_winner = model_a_short if a_recall > b_recall else model_b_short if b_recall > a_recall else "tie"

        if a_mrr > b_mrr:
            a_wins += 1
        elif b_mrr > a_mrr:
            b_wins += 1

        print(f"{query:<35} {'MRR':<10} {a_mrr:<20.3f} {b_mrr:<20.3f} {mrr_winner:<15}")
        print(f"{'':<35} {'R@3':<10} {a_recall:<20.3f} {b_recall:<20.3f} {recall_winner:<15}")

        # Show top-3 results for each model
        a_top3 = ", ".join(t[:25] for t in row[f"{model_a_short}_top3"])
        b_top3 = ", ".join(t[:25] for t in row[f"{model_b_short}_top3"])
        print(f"{'  ' + model_a_short + ':':<37} {a_top3}")
        print(f"{'  ' + model_b_short + ':':<37} {b_top3}")
        print()

    print("-" * 100)
    print(f"Summary: {model_a_short} wins {a_wins}, {model_b_short} wins {b_wins}, ties {len(rows) - a_wins - b_wins}")
    print("=" * 100)

    # Assert both models produce non-degenerate results
    for row in rows:
        assert row[f"{model_a_short}_mrr"] > 0 or row[f"{model_a_short}_recall"] > 0
        assert row[f"{model_b_short}_mrr"] > 0 or row[f"{model_b_short}_recall"] > 0
