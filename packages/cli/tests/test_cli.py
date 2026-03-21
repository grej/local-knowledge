"""CLI integration tests using Click CliRunner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from click.testing import CliRunner

from lk.cli import cli


def _mock_embed(texts, model_name=None):
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


def _invoke(runner, args, base_dir):
    return runner.invoke(cli, ["--base-dir", str(base_dir)] + args)


def test_add_text(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        result = _invoke(runner, ["add", "--text", "Hello world", "--title", "Greeting"], base_dir)
    assert result.exit_code == 0
    assert "Added" in result.output
    assert "Greeting" in result.output


def test_add_file(base_dir):
    runner = CliRunner()
    f = base_dir / "test-doc.md"
    f.write_text("# My Notes\nSome content here.", encoding="utf-8")
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        result = _invoke(runner, ["add", "--file", str(f)], base_dir)
    assert result.exit_code == 0
    assert "Added" in result.output


def test_list(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        _invoke(runner, ["add", "--text", "Doc one", "--title", "First"], base_dir)
        _invoke(runner, ["add", "--text", "Doc two", "--title", "Second"], base_dir)
        result = _invoke(runner, ["list"], base_dir)
    assert result.exit_code == 0
    assert "First" in result.output
    assert "Second" in result.output


def test_search(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        _invoke(runner, ["add", "--text", "Quantum computing with qubits", "--title", "Quantum"], base_dir)
        result = _invoke(runner, ["search", "quantum"], base_dir)
    assert result.exit_code == 0
    assert "Quantum" in result.output


def test_show(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        add_result = _invoke(runner, ["add", "--text", "Show me this", "--title", "ShowDoc"], base_dir)
    # Extract doc ID from output (format: "Added: ShowDoc (abcdef123456)")
    doc_id = add_result.output.split("(")[1].split(")")[0]

    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        result = _invoke(runner, ["show", doc_id], base_dir)
    assert result.exit_code == 0
    assert "ShowDoc" in result.output


def test_tags_and_tag(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        add_result = _invoke(runner, ["add", "--text", "Tag this", "--title", "Taggable"], base_dir)
    doc_id = add_result.output.split("(")[1].split(")")[0]

    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        result = _invoke(runner, ["tag", doc_id, "science"], base_dir)
    assert result.exit_code == 0
    assert "science" in result.output

    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        result = _invoke(runner, ["tags"], base_dir)
    assert result.exit_code == 0
    assert "science" in result.output


def test_embed_all(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        # Disable auto_embed first
        _invoke(runner, ["config", "set", "embeddings.auto_embed", "false"], base_dir)
        _invoke(runner, ["add", "--text", "Embed this", "--title", "Embeddable"], base_dir)
        result = _invoke(runner, ["embed", "--all"], base_dir)
    assert result.exit_code == 0
    assert "Embedded" in result.output


def test_delete(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        add_result = _invoke(runner, ["add", "--text", "Delete me", "--title", "Deletable"], base_dir)
    doc_id = add_result.output.split("(")[1].split(")")[0]

    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        result = _invoke(runner, ["delete", doc_id], base_dir)
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_config_show(base_dir):
    runner = CliRunner()
    result = _invoke(runner, ["config"], base_dir)
    assert result.exit_code == 0
    assert "embeddings" in result.output


def test_config_set(base_dir):
    runner = CliRunner()
    result = _invoke(runner, ["config", "set", "embeddings.auto_embed", "false"], base_dir)
    assert result.exit_code == 0
    assert "Set" in result.output


def test_stats(base_dir):
    runner = CliRunner()
    with patch("localknowledge.embeddings.dense._embed_texts", _mock_embed):
        _invoke(runner, ["add", "--text", "Stats test", "--title", "Stats"], base_dir)
        result = _invoke(runner, ["stats"], base_dir)
    assert result.exit_code == 0
    assert "Total" in result.output
