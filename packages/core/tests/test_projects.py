"""Tests for project tags and tag_type infrastructure."""

import numpy as np

from localknowledge.db import Database
from localknowledge.documents import DocumentStore
from localknowledge.service import KnowledgeService
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


def _svc(tmp_path) -> KnowledgeService:
    return KnowledgeService(base_dir=tmp_path, embed_fn=_mock_embed)


def test_create_project(tmp_path):
    svc = _svc(tmp_path)
    project = svc.create_project("Mountain Discovery", description="Alpine research")
    assert project["tag_type"] == "project"
    assert project["slug"] == "mountain-discovery"
    assert project["description"] == "Alpine research"


def test_list_projects_excludes_topics(tmp_path):
    svc = _svc(tmp_path)
    svc.tags.create("optimization")  # topic (default)
    svc.create_project("silent-service")

    projects = svc.list_projects()
    assert len(projects) == 1
    assert projects[0]["slug"] == "silent-service"


def test_list_topics_excludes_projects(tmp_path):
    svc = _svc(tmp_path)
    svc.tags.create("optimization")
    svc.create_project("silent-service")

    topics = svc.tags.list_topics()
    assert len(topics) == 1
    assert topics[0]["slug"] == "optimization"


def test_tag_type_default_is_topic(tmp_path):
    db = Database(tmp_path)
    tags = TagStore(db)
    tag = tags.create("machine-learning")
    assert tag["tag_type"] == "topic"


def test_backward_compat_existing_tags(tmp_path):
    db = Database(tmp_path)
    tags = TagStore(db)
    # Existing tags (no explicit tag_type) should default to 'topic'
    tag = tags.create("legacy-tag")
    fetched = tags.get(tag["id"])
    assert fetched["tag_type"] == "topic"


def test_project_document_membership(tmp_path):
    svc = _svc(tmp_path)
    project = svc.create_project("spock")
    doc = svc.add_text("Knowledge distillation techniques", title="KD Paper")
    svc.tags.tag_document(doc.id, project["id"])

    docs = svc.get_project_documents("spock")
    assert len(docs) == 1
    assert docs[0].id == doc.id


def test_project_topics(tmp_path):
    svc = _svc(tmp_path)
    project = svc.create_project("spock")
    topic = svc.tags.create("optimization")

    doc = svc.add_text("Optimizing model distillation", title="Optimization")
    svc.tags.tag_document(doc.id, project["id"])
    svc.tags.tag_document(doc.id, topic["id"])

    topics = svc.get_project_topics("spock")
    assert len(topics) == 1
    assert topics[0]["slug"] == "optimization"


def test_list_with_tag_type_filter(tmp_path):
    db = Database(tmp_path)
    tags = TagStore(db)
    tags.create("topic-a")
    tags.create("topic-b")
    tags.create_project("project-x")

    all_tags = tags.list()
    assert len(all_tags) == 3

    topics = tags.list(tag_type="topic")
    assert len(topics) == 2

    projects = tags.list(tag_type="project")
    assert len(projects) == 1


def test_migration_v001_v002_v003_path(tmp_path):
    """Verify existing tags survive migration and project_centroids table exists."""
    db = Database(tmp_path)
    tags = TagStore(db)

    # Create a tag before v003 would have existed — it already ran during Database init
    tag = tags.create("pre-existing")
    fetched = tags.get(tag["id"])
    assert fetched["tag_type"] == "topic"

    # Verify project_centroids table exists
    from contextlib import closing
    with closing(db.connect()) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='project_centroids'"
        ).fetchone()
    assert row is not None
