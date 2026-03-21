from readcast_v2.compat import Article, article_to_document, document_to_article


def _sample_article() -> Article:
    return Article(
        id="abc-123",
        source_url="https://example.com/article",
        source_file=None,
        title="Test Article",
        author="Alice",
        publication="Tech Blog",
        published_date="2024-06-01",
        ingested_at="2024-06-01T12:00:00+00:00",
        word_count=1500,
        estimated_read_min=7,
        description="A test article about testing",
        canonical_url="https://example.com/article",
        language="en",
        status="done",
        voice="af_sky",
        tts_model="kokoro-82m",
        speed=1.0,
        audio_duration_sec=420.5,
        tags=["python", "testing"],
        listen_count=3,
        listened_complete=1,
    )


def test_round_trip():
    """Article -> Document -> Article preserves identity and key fields."""
    original = _sample_article()
    doc = article_to_document(original)
    restored = document_to_article(doc)

    assert restored.id == original.id
    assert restored.title == original.title
    assert restored.source_url == original.source_url
    assert restored.author == original.author
    assert restored.publication == original.publication
    assert restored.language == original.language
    assert restored.status == original.status
    assert restored.tags == original.tags
    assert restored.voice == original.voice
    assert restored.listen_count == original.listen_count


def test_metadata_preservation():
    """Readcast-specific fields are preserved in Document.metadata."""
    article = _sample_article()
    doc = article_to_document(article)

    assert doc.metadata is not None
    assert doc.metadata["author"] == "Alice"
    assert doc.metadata["publication"] == "Tech Blog"
    assert doc.metadata["voice"] == "af_sky"
    assert doc.metadata["audio_duration_sec"] == 420.5
    assert doc.metadata["tags"] == ["python", "testing"]
    assert doc.metadata["listen_count"] == 3

    assert doc.source_type == "article"
    assert doc.source_product == "readcast"
    assert doc.source_uri == "https://example.com/article"
    assert doc.ingest_status == "indexed"


def test_status_mapping():
    """Article status maps correctly to Document ingest_status."""
    for article_status, expected_ingest in [
        ("queued", "raw"),
        ("synthesizing", "processed"),
        ("done", "indexed"),
        ("error", "error"),
    ]:
        article = _sample_article()
        article.status = article_status
        doc = article_to_document(article)
        assert doc.ingest_status == expected_ingest

        restored = document_to_article(doc)
        assert restored.status == article_status
