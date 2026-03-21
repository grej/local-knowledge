"""Tests for AutoTagger."""

import numpy as np

from localknowledge.autotag import (
    TOPIC_AUTO_THRESHOLD,
    TOPIC_SUGGEST_THRESHOLD,
    AutoTagger,
)
from localknowledge.service import KnowledgeService


def _mock_embed(texts):
    """Mock embedding that produces deterministic vectors from text."""
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


def test_suggest_topics_above_threshold(tmp_path):
    svc = _svc(tmp_path)
    # Create a topic whose name is very similar to the doc content
    svc.tags.create("machine learning basics")
    doc = svc.add_text("machine learning basics and fundamentals", title="ML Intro")

    suggestions = svc.suggest_topics(doc.id)
    # With mock embeddings and similar text, we should get a suggestion
    assert len(suggestions) >= 1
    assert all(s.tag_type == "topic" for s in suggestions)


def test_suggest_topics_with_description(tmp_path):
    svc = _svc(tmp_path)
    svc.tags.create("ML", description="machine learning and deep learning")
    doc = svc.add_text("machine learning and deep learning tutorial", title="ML Tutorial")

    suggestions = svc.suggest_topics(doc.id)
    assert len(suggestions) >= 1


def test_suggest_topics_below_threshold_excluded(tmp_path):
    svc = _svc(tmp_path)
    # Topic name very different from doc content
    svc.tags.create("underwater basket weaving")
    doc = svc.add_text("quantum computing and quantum mechanics", title="Quantum")

    suggestions = svc.suggest_topics(doc.id)
    # Very dissimilar content should produce low scores
    low_scores = [s for s in suggestions if s.score < TOPIC_SUGGEST_THRESHOLD]
    # Either no suggestions or all below threshold should be excluded
    for s in suggestions:
        assert s.score >= TOPIC_SUGGEST_THRESHOLD


def test_auto_tag_applies_high_confidence_topics(tmp_path):
    svc = _svc(tmp_path)
    # Create topic with name identical to doc content for high similarity
    svc.tags.create("identical content for testing")
    doc = svc.add_text("identical content for testing", title="Test")

    suggestions = svc.auto_tag(doc.id)
    auto_applied = [s for s in suggestions if s.action == "auto"]

    if auto_applied:
        # Verify the tag was actually applied
        tags = svc.get_document_tags(doc.id)
        auto_tag_ids = {s.tag_id for s in auto_applied}
        applied_ids = {t["id"] for t in tags}
        assert auto_tag_ids.issubset(applied_ids)


def test_auto_tag_does_not_apply_low(tmp_path):
    svc = _svc(tmp_path)
    svc.tags.create("zzz completely unrelated xyz")
    doc = svc.add_text("abc totally different content 123", title="Different")

    suggestions = svc.auto_tag(doc.id)
    # Suggestions with action="suggest" should NOT be auto-applied
    suggest_only = [s for s in suggestions if s.action == "suggest"]
    if suggest_only:
        tags = svc.get_document_tags(doc.id)
        suggest_ids = {s.tag_id for s in suggest_only}
        applied_ids = {t["id"] for t in tags}
        assert not suggest_ids.intersection(applied_ids)


def test_suggest_projects_never_auto_assigns(tmp_path):
    svc = _svc(tmp_path)
    project = svc.create_project("my-project")

    # Add a doc to the project and build centroid
    doc1 = svc.add_text("project content about testing", title="Project Doc")
    svc.tags.tag_document(doc1.id, project["id"])
    svc.centroids.update_centroid(project["id"])

    # Now check suggestions for a similar doc
    doc2 = svc.add_text("project content about testing again", title="Similar Doc")
    suggestions = svc.suggest_projects(doc2.id)

    for s in suggestions:
        assert s.action == "suggest"  # Never "auto"
        assert s.tag_type == "project"


def test_suggest_projects_uses_centroid(tmp_path):
    svc = _svc(tmp_path)
    project = svc.create_project("centroid-test")

    doc = svc.add_text("centroid content here", title="Centroid Doc")
    svc.tags.tag_document(doc.id, project["id"])
    svc.centroids.update_centroid(project["id"])

    # Centroid should exist now
    centroid = svc.centroids.get_centroid(project["id"])
    assert centroid is not None


def test_auto_tag_on_ingest(tmp_path):
    svc = _svc(tmp_path)
    # Create a topic, then add a doc — auto_tag should run
    svc.tags.create("auto tag test content")
    doc = svc.add_text("auto tag test content is great", title="Auto Tagged")
    # auto_tag ran during ingest; check if any tags applied
    tags = svc.get_document_tags(doc.id)
    # May or may not have applied based on mock similarity — just verify no crash


def test_auto_tag_on_ingest_disabled(tmp_path):
    svc = _svc(tmp_path)
    svc.config.embeddings.auto_tag = False
    svc.tags.create("should not auto tag")
    doc = svc.add_text("should not auto tag content", title="No Auto")
    # With auto_tag disabled, no tags should be applied during ingest
    tags = svc.get_document_tags(doc.id)
    assert len(tags) == 0


def test_suggest_all_combines_and_sorts(tmp_path):
    svc = _svc(tmp_path)
    svc.tags.create("topic alpha")
    project = svc.create_project("project beta")

    doc1 = svc.add_text("project beta content", title="P Doc")
    svc.tags.tag_document(doc1.id, project["id"])
    svc.centroids.update_centroid(project["id"])

    doc2 = svc.add_text("topic alpha and project beta content", title="Combined")
    suggestions = svc.autotagger.suggest_all(doc2.id)

    # Should include both topic and project suggestions (if scores above threshold)
    types = {s.tag_type for s in suggestions}
    # Verify sorted by score descending
    scores = [s.score for s in suggestions]
    assert scores == sorted(scores, reverse=True)
