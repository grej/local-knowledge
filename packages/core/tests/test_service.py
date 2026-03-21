"""Tests for KnowledgeService (mock embeddings)."""

from pathlib import Path

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


def _svc(tmp_path) -> KnowledgeService:
    return KnowledgeService(base_dir=tmp_path, embed_fn=_mock_embed)


def test_add_text_and_retrieve(tmp_path):
    svc = _svc(tmp_path)
    doc = svc.add_text("Hello world", title="Greeting")
    assert doc.title == "Greeting"
    assert doc.content == "Hello world"

    fetched = svc.get_document(doc.id)
    assert fetched is not None
    assert fetched.title == "Greeting"


def test_add_text_derives_title(tmp_path):
    svc = _svc(tmp_path)
    doc = svc.add_text("# My Great Note\nSome content here.")
    assert doc.title == "My Great Note"


def test_add_file(tmp_path):
    svc = _svc(tmp_path)
    f = tmp_path / "test-notes.md"
    f.write_text("Some file content", encoding="utf-8")
    doc = svc.add_file(f)
    assert doc.title == "Test Notes"
    assert doc.content == "Some file content"


def test_search_hybrid(tmp_path):
    svc = _svc(tmp_path)
    svc.add_text("Machine learning and neural networks", title="ML Paper")
    svc.add_text("Cooking pasta with tomato sauce", title="Pasta Recipe")

    results = svc.search("neural networks")
    assert len(results) >= 1
    assert results[0].document.title == "ML Paper"
    assert results[0].source == "hybrid"


def test_search_fts_only(tmp_path):
    svc = _svc(tmp_path)
    svc.add_text("Quantum computing and qubits", title="Quantum")

    results = svc.search("quantum", mode="fts")
    assert len(results) == 1
    assert results[0].source == "fts"


def test_search_semantic_only(tmp_path):
    svc = _svc(tmp_path)
    svc.add_text("Quantum computing and qubits", title="Quantum")

    results = svc.search("quantum physics", mode="semantic")
    assert len(results) == 1
    assert results[0].source == "semantic"


def test_embed_document(tmp_path):
    svc = KnowledgeService(base_dir=tmp_path, embed_fn=_mock_embed)
    # Disable auto_embed to test manual embedding
    svc.config.embeddings.auto_embed = False
    doc = svc.add_text("Content to embed", title="Test")

    stats = svc.embedding_stats()
    assert stats["unembedded"] == 1

    svc.embed_document(doc.id)
    stats = svc.embedding_stats()
    assert stats["embedded"] == 1
    assert stats["unembedded"] == 0


def test_embed_all(tmp_path):
    svc = KnowledgeService(base_dir=tmp_path, embed_fn=_mock_embed)
    svc.config.embeddings.auto_embed = False
    svc.add_text("Doc one", title="One")
    svc.add_text("Doc two", title="Two")
    svc.add_text("Doc three", title="Three")

    count = svc.embed_all()
    assert count == 3
    assert svc.embedding_stats()["unembedded"] == 0


def test_tag_document(tmp_path):
    svc = _svc(tmp_path)
    doc = svc.add_text("Tagged content", title="Tagged")
    tag = svc.tag_document(doc.id, "science")
    assert tag["slug"] == "science"

    tags = svc.get_document_tags(doc.id)
    assert len(tags) == 1
    assert tags[0]["name"] == "science"


def test_delete_soft(tmp_path):
    svc = _svc(tmp_path)
    doc = svc.add_text("To delete", title="Deleteme")
    assert svc.delete_document(doc.id)
    assert svc.get_document(doc.id) is None
    assert len(svc.list_documents()) == 0


def test_config_show_and_set(tmp_path):
    svc = _svc(tmp_path)
    cfg = svc.get_config()
    assert cfg["embeddings"]["model"] == "BAAI/bge-small-en-v1.5"

    svc.set_config("embeddings.auto_embed", "false")
    reloaded = KnowledgeService(base_dir=tmp_path, embed_fn=_mock_embed)
    assert reloaded.config.embeddings.auto_embed is False
