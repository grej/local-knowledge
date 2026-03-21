import time

from localknowledge.documents import DocumentStore


def test_crud(db):
    store = DocumentStore(db)
    doc = store.create(
        title="Test Article",
        source_type="article",
        source_product="readcast",
        content="Hello world",
    )
    assert doc.id
    assert doc.title == "Test Article"

    fetched = store.get(doc.id)
    assert fetched is not None
    assert fetched.title == "Test Article"

    fetched.title = "Updated"
    store.update(fetched)
    updated = store.get(doc.id)
    assert updated.title == "Updated"


def test_content_hash_dedup(db):
    store = DocumentStore(db)
    doc1 = store.create(
        title="First",
        source_type="article",
        source_product="readcast",
        content="Same content",
    )
    found = store.get_by_content_hash(doc1.content_hash)
    assert found is not None
    assert found.id == doc1.id


def test_list_filters(db):
    store = DocumentStore(db)
    store.create(title="Article 1", source_type="article", source_product="readcast")
    store.create(
        title="Briefing 1", source_type="briefing", source_product="briefing-agent"
    )
    articles = store.list(source_type="article")
    assert len(articles) == 1
    assert articles[0].source_type == "article"


def test_soft_delete(db):
    store = DocumentStore(db)
    doc = store.create(
        title="To Delete", source_type="article", source_product="readcast"
    )
    assert store.delete(doc.id)
    assert store.get(doc.id) is None
    assert store.get(doc.id, include_deleted=True) is not None


def test_fts5_search(db):
    store = DocumentStore(db)
    store.create(
        title="Machine Learning Basics",
        source_type="article",
        source_product="readcast",
        content="Neural networks and deep learning fundamentals",
    )
    store.create(
        title="Cooking Recipes",
        source_type="article",
        source_product="readcast",
        content="How to make pasta and pizza",
    )
    results = store.search("neural networks")
    assert len(results) == 1
    assert results[0].title == "Machine Learning Basics"


def test_search_excludes_deleted(db):
    store = DocumentStore(db)
    doc = store.create(
        title="Secret Doc",
        source_type="article",
        source_product="readcast",
        content="Top secret information",
    )
    store.delete(doc.id)
    results = store.search("secret")
    assert len(results) == 0


def test_update_timestamps(db):
    store = DocumentStore(db)
    doc = store.create(
        title="Timestamped", source_type="article", source_product="readcast"
    )
    original_updated = doc.updated_at
    time.sleep(0.01)
    doc.title = "Timestamped Updated"
    store.update(doc)
    refreshed = store.get(doc.id)
    assert refreshed.updated_at > original_updated
