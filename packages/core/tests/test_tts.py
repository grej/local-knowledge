from unittest.mock import MagicMock, patch

from localknowledge.tts import TTSClient, TTSConfig, TTSError


def test_synthesize_text():
    config = TTSConfig()
    client = TTSClient(config)
    with patch("localknowledge.tts.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, content=b"RIFF\x00\x00\x00\x00WAVEfmt "
        )
        result = client.synthesize_text("Hello world")
    assert result.startswith(b"RIFF")
    call_kwargs = mock_post.call_args
    assert "v1/audio/speech" in call_kwargs.args[0]


def test_fetch_voices():
    config = TTSConfig()
    client = TTSClient(config)
    with patch("localknowledge.tts.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"voices": [{"name": "af_sky"}, {"name": "bm_daniel"}]},
        )
        voices = client.fetch_voices()
    assert len(voices) == 2
    assert voices[0]["name"] == "af_sky"


def test_server_status():
    config = TTSConfig()
    client = TTSClient(config)
    with patch("localknowledge.tts.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "running", "model": "kokoro-82m"},
        )
        status = client.server_status()
    assert status["status"] == "running"


def test_server_status_error():
    import httpx as real_httpx

    config = TTSConfig()
    client = TTSClient(config)
    with patch(
        "localknowledge.tts.httpx.get",
        side_effect=real_httpx.ConnectError("refused"),
    ):
        try:
            client.server_status()
            assert False, "Should have raised"
        except TTSError:
            pass


def test_synthesize_with_voice_override():
    config = TTSConfig()
    client = TTSClient(config)
    with patch("localknowledge.tts.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, content=b"RIFF\x00\x00\x00\x00WAVEfmt "
        )
        client.synthesize_text("Hello", voice="bm_daniel", speed=1.5)
    payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert payload["voice"] == "bm_daniel"
    assert payload["speed"] == 1.5
