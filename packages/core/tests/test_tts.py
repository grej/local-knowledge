import httpx
import pytest

from localknowledge.tts import TTSClient, TTSConfig, TTSError


def _client(handler) -> TTSClient:
    return TTSClient(TTSConfig(), transport=httpx.MockTransport(handler))


def test_synthesize_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        return httpx.Response(200, content=b"RIFF\x00\x00\x00\x00WAVEfmt ", request=request)

    result = _client(handler).synthesize_text("Hello world")

    assert result.startswith(b"RIFF")


def test_fetch_voices():
    client = _client(
        lambda request: httpx.Response(
            200,
            json={"voices": [{"name": "af_sky"}, {"name": "bm_daniel"}]},
            request=request,
        )
    )

    voices = client.fetch_voices()

    assert len(voices) == 2
    assert voices[0]["name"] == "af_sky"


def test_server_status():
    client = _client(
        lambda request: httpx.Response(
            200,
            json={"status": "running", "model": "kokoro-82m"},
            request=request,
        )
    )

    assert client.server_status()["status"] == "running"


def test_server_status_error():
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TTSError):
        _client(refused).server_status()


def test_synthesize_with_voice_override():
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payloads.append(json.loads(request.content))
        return httpx.Response(200, content=b"RIFF\x00\x00\x00\x00WAVEfmt ", request=request)

    _client(handler).synthesize_text("Hello", voice="bm_daniel", speed=1.5)

    assert payloads[0]["voice"] == "bm_daniel"
    assert payloads[0]["speed"] == 1.5
