"""Tests for tag intersection queries."""

from localknowledge.documents import DocumentStore
from localknowledge.tags import TagStore


def _create_doc(db, title="Test"):
    return DocumentStore(db).create(
        title=title, source_type="article", source_product="test"
    )


def test_and_query_both_tags(db):
    tags = TagStore(db)
    doc1 = _create_doc(db, "Energy Policy")
    doc2 = _create_doc(db, "Pure Energy")
    doc3 = _create_doc(db, "Pure Politics")

    t_energy = tags.get_or_create("energy")
    t_politics = tags.get_or_create("politics")

    tags.tag_document(doc1.id, t_energy["id"])
    tags.tag_document(doc1.id, t_politics["id"])
    tags.tag_document(doc2.id, t_energy["id"])
    tags.tag_document(doc3.id, t_politics["id"])

    result = tags.search_by_tags(["energy", "politics"], match_all=True)
    assert result == [doc1.id]


def test_or_query_either_tag(db):
    tags = TagStore(db)
    doc1 = _create_doc(db, "Energy Doc")
    doc2 = _create_doc(db, "Politics Doc")
    doc3 = _create_doc(db, "Unrelated")

    t_energy = tags.get_or_create("energy")
    t_politics = tags.get_or_create("politics")

    tags.tag_document(doc1.id, t_energy["id"])
    tags.tag_document(doc2.id, t_politics["id"])

    result = tags.search_by_tags(["energy", "politics"], match_all=False)
    assert set(result) == {doc1.id, doc2.id}


def test_mixed_tag_coverage(db):
    tags = TagStore(db)
    doc1 = _create_doc(db, "Has Both")
    doc2 = _create_doc(db, "Has One")
    doc3 = _create_doc(db, "Has Other")

    t_a = tags.get_or_create("alpha")
    t_b = tags.get_or_create("beta")

    tags.tag_document(doc1.id, t_a["id"])
    tags.tag_document(doc1.id, t_b["id"])
    tags.tag_document(doc2.id, t_a["id"])
    tags.tag_document(doc3.id, t_b["id"])

    # AND: only doc1
    and_result = tags.search_by_tags(["alpha", "beta"], match_all=True)
    assert and_result == [doc1.id]

    # OR: all three
    or_result = tags.search_by_tags(["alpha", "beta"], match_all=False)
    assert set(or_result) == {doc1.id, doc2.id, doc3.id}


def test_no_matches_returns_empty(db):
    tags = TagStore(db)
    _create_doc(db, "Some Doc")

    result = tags.search_by_tags(["nonexistent-tag"], match_all=True)
    assert result == []
