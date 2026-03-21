from localknowledge.documents import DocumentStore
from localknowledge.tags import TagStore


def _create_doc(db, title="Test"):
    return DocumentStore(db).create(
        title=title, source_type="article", source_product="readcast"
    )


def test_slug_generation(db):
    store = TagStore(db)
    tag = store.create("Organic Chemistry")
    assert tag["slug"] == "organic-chemistry"


def test_idempotent_get_or_create(db):
    store = TagStore(db)
    first = store.get_or_create("Machine Learning")
    second = store.get_or_create("Machine Learning")
    assert first["id"] == second["id"]


def test_hierarchy(db):
    store = TagStore(db)
    parent = store.create("Work")
    child = store.create("Anaconda", parent_id=parent["id"])
    fetched = store.get(child["id"])
    assert fetched["parent_id"] == parent["id"]
    children = store.list(parent_id=parent["id"])
    assert len(children) == 1
    assert children[0]["id"] == child["id"]


def test_confidence_scoring(db):
    store = TagStore(db)
    doc = _create_doc(db)
    tag = store.create("AI")
    store.tag_document(doc.id, tag["id"], confidence=0.85, source="auto_embed")
    tags = store.get_document_tags(doc.id)
    assert len(tags) == 1
    assert tags[0]["confidence"] == 0.85
    assert tags[0]["source"] == "auto_embed"


def test_document_tags(db):
    store = TagStore(db)
    doc = _create_doc(db)
    tag1 = store.create("Python")
    tag2 = store.create("Testing")
    store.tag_document(doc.id, tag1["id"])
    store.tag_document(doc.id, tag2["id"])
    tags = store.get_document_tags(doc.id)
    assert len(tags) == 2

    store.untag_document(doc.id, tag1["id"])
    tags = store.get_document_tags(doc.id)
    assert len(tags) == 1


def test_recursive_child_lookup(db):
    tags = TagStore(db)
    docs = DocumentStore(db)

    parent = tags.create("Science")
    child = tags.create("Physics", parent_id=parent["id"])
    grandchild = tags.create("Quantum", parent_id=child["id"])

    doc1 = docs.create(
        title="Physics 101", source_type="article", source_product="readcast"
    )
    doc2 = docs.create(
        title="Quantum Mechanics", source_type="article", source_product="readcast"
    )

    tags.tag_document(doc1.id, child["id"])
    tags.tag_document(doc2.id, grandchild["id"])

    direct = tags.get_tagged_documents(parent["id"])
    assert len(direct) == 0

    recursive = tags.get_tagged_documents(parent["id"], recursive=True)
    assert len(recursive) == 2
