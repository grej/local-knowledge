"""Tests for paragraph-boundary text chunker."""

from localknowledge.chunker import Chunk, chunk_text


def test_single_paragraph_returns_one_chunk():
    text = "This is a single paragraph with some content about machine learning."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].index == 0


def test_multiple_paragraphs_merged_up_to_limit():
    text = "Short one.\n\nShort two.\n\nShort three."
    chunks = chunk_text(text, max_tokens=100)
    # All paragraphs fit in one merge pass, but overlap causes a trailing chunk
    # The important thing: first chunk contains all paragraphs
    assert "Short one." in chunks[0].text
    assert "Short three." in chunks[0].text


def test_long_text_produces_overlapping_chunks():
    # Create paragraphs sized so that two fit per chunk but three don't,
    # which triggers the overlap-by-one-paragraph behavior.
    paragraphs = [f"Paragraph {i} " + "word " * 20 for i in range(6)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_tokens=50)
    assert len(chunks) >= 2
    # When multiple paragraphs merge, the last paragraph of chunk N
    # should appear as the first paragraph of chunk N+1 (overlap).
    for i in range(len(chunks) - 1):
        last_para = chunks[i].text.split("\n\n")[-1]
        first_para = chunks[i + 1].text.split("\n\n")[0]
        assert last_para == first_para, (
            f"Expected overlap: chunk {i} last para != chunk {i+1} first para"
        )


def test_empty_input_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []
    assert chunk_text("\n\n\n") == []


def test_chunk_positions_correct():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    # With tiny limit, each paragraph is its own chunk
    chunks = chunk_text(text, max_tokens=3)
    for chunk in chunks:
        assert chunk.start >= 0
        assert chunk.end <= len(text)
        assert chunk.end > chunk.start
        # The chunk text should match the source at the given position
        assert chunk.text in text
    # Indices should be sequential
    for i, chunk in enumerate(chunks):
        assert chunk.index == i
