"""Paragraph-boundary text chunker with overlap for embedding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Chunk:
    """A contiguous slice of source text."""

    text: str
    start: int
    end: int
    index: int


def chunk_text(text: str, max_tokens: int = 300) -> list[Chunk]:
    """Split *text* into overlapping chunks at paragraph boundaries.

    Strategy:
    - Split on double newlines (paragraph boundaries)
    - Merge short consecutive paragraphs up to *max_tokens*
    - Never split mid-sentence
    - Overlap by one paragraph between chunks
    """
    paragraphs: list[tuple[str, int, int]] = []
    pos = 0
    for segment in text.split("\n\n"):
        stripped = segment.strip()
        if stripped:
            start = text.find(stripped, pos)
            end = start + len(stripped)
            paragraphs.append((stripped, start, end))
            pos = end

    if not paragraphs:
        stripped = text.strip()
        if stripped:
            return [Chunk(text=stripped, start=0, end=len(text), index=0)]
        return []

    def _approx_tokens(s: str) -> int:
        return len(s.split())

    raw: list[tuple[str, int, int]] = []
    i = 0
    while i < len(paragraphs):
        merged_parts = [paragraphs[i]]
        token_count = _approx_tokens(paragraphs[i][0])
        j = i + 1
        while j < len(paragraphs) and token_count + _approx_tokens(paragraphs[j][0]) <= max_tokens:
            merged_parts.append(paragraphs[j])
            token_count += _approx_tokens(paragraphs[j][0])
            j += 1

        chunk_text_str = "\n\n".join(p[0] for p in merged_parts)
        chunk_start = merged_parts[0][1]
        chunk_end = merged_parts[-1][2]
        raw.append((chunk_text_str, chunk_start, chunk_end))

        # Overlap: step back by one paragraph so the last paragraph of this chunk
        # becomes the first paragraph of the next chunk.
        if j > i + 1:
            i = j - 1
        else:
            i = j

    return [Chunk(text=t, start=s, end=e, index=idx) for idx, (t, s, e) in enumerate(raw)]
