"""Tests for MCP tools at function level (no MCP transport)."""

import numpy as np

from localknowledge.service import KnowledgeService


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


def _setup(tmp_path):
    """Create a service and patch it into the tools module."""
    import lk_mcp.tools as tools_mod

    svc = KnowledgeService(base_dir=tmp_path, embed_fn=_mock_embed)
    tools_mod._svc = svc
    return svc


def test_list_projects_empty(tmp_path):
    from lk_mcp.tools import list_projects

    _setup(tmp_path)
    result = list_projects()
    assert result == []


def test_ingest_and_search(tmp_path):
    from lk_mcp.tools import ingest, search

    _setup(tmp_path)
    result = ingest(text="Machine learning fundamentals", title="ML Intro")
    assert "document_id" in result
    assert result["title"] == "ML Intro"

    results = search(query="machine learning")
    assert len(results) >= 1
    assert results[0]["title"] == "ML Intro"


def test_search_with_project_filter(tmp_path):
    from lk_mcp.tools import ingest, search

    svc = _setup(tmp_path)
    project = svc.create_project("ml-project")

    result = ingest(text="Neural networks explained", title="NN", projects=["ml-project"])
    ingest(text="Cooking pasta with tomato sauce", title="Pasta")

    results = search(query="neural", project="ml-project")
    assert len(results) == 1
    assert results[0]["title"] == "NN"


def test_find_connections_excludes_same_project(tmp_path):
    from lk_mcp.tools import find_connections

    svc = _setup(tmp_path)
    project = svc.create_project("alpha")

    doc1 = svc.add_text("Neural network training", title="NN Train")
    svc.tags.tag_document(doc1.id, project["id"])

    doc2 = svc.add_text("Deep learning optimization", title="DL Opt")
    svc.tags.tag_document(doc2.id, project["id"])

    doc3 = svc.add_text("Neural network architectures", title="NN Arch")
    # doc3 is NOT in the project

    results = find_connections(doc_id=doc1.id, exclude_project="alpha")
    result_ids = [r["document_id"] for r in results]
    assert doc2.id not in result_ids
    # doc3 should be present if similar enough
    if results:
        assert all(r["document_id"] != doc2.id for r in results)


def test_tag_add_and_remove(tmp_path):
    from lk_mcp.tools import tag

    svc = _setup(tmp_path)
    doc = svc.add_text("Some content", title="Test Doc")

    result = tag(doc_id=doc.id, add=["science", "math"])
    assert len(result["tags"]) == 2

    result = tag(doc_id=doc.id, remove=["math"])
    assert len(result["tags"]) == 1
    assert result["tags"][0]["name"] == "science"


def test_suggest_projects_returns_scores(tmp_path):
    from lk_mcp.tools import suggest_projects

    svc = _setup(tmp_path)
    project = svc.create_project("beta")

    doc1 = svc.add_text("project beta content here", title="Beta Doc")
    svc.tags.tag_document(doc1.id, project["id"])
    svc.centroids.update_centroid(project["id"])

    doc2 = svc.add_text("project beta similar content", title="Similar")
    results = suggest_projects(doc_id=doc2.id)

    for r in results:
        assert "name" in r
        assert "score" in r
        assert isinstance(r["score"], float)
