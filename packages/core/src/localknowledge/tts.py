"""TTS client — HTTP interface to kokoro-edge server."""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TTSConfig:
    server_url: str = "http://127.0.0.1:7777"
    model: str = "kokoro-82m"
    voice: str = "af_sky"
    speed: float = 1.0
    language: str = "en-us"
    binary: str = "kokoro-edge"
    auto_start: bool = True
    startup_timeout_sec: int = 30


class TTSError(RuntimeError):
    pass


class TTSClient:
    def __init__(self, config: TTSConfig):
        self.config = config

    def synthesize_text(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
    ) -> bytes:
        """Synthesize text to WAV bytes."""
        url = f"{self._base_url}/v1/audio/speech"
        payload = {
            "model": self.config.model,
            "input": text,
            "voice": voice or self.config.voice,
            "speed": speed or self.config.speed,
            "response_format": "wav",
            "language": self.config.language,
        }
        try:
            response = httpx.post(url, json=payload, timeout=120.0)
        except httpx.HTTPError as exc:
            raise TTSError(f"TTS request failed: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(f"TTS synthesis failed: {_error_message(response)}")
        return response.content

    def fetch_voices(self) -> list[dict]:
        """Fetch available voices from the server."""
        url = f"{self._base_url}/v1/voices"
        try:
            response = httpx.get(url, timeout=5.0)
        except httpx.HTTPError as exc:
            raise TTSError(f"Failed to fetch voices: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(f"Failed to fetch voices: {_error_message(response)}")
        payload = response.json()
        return [v for v in payload.get("voices", []) if isinstance(v, dict) and "name" in v]

    def server_status(self) -> dict:
        """Check TTS server status."""
        url = f"{self._base_url}/v1/status"
        try:
            response = httpx.get(url, timeout=2.0)
        except httpx.HTTPError as exc:
            raise TTSError(f"TTS server not reachable: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(f"TTS status check failed: {_error_message(response)}")
        return response.json()

    def ensure_server_running(self) -> dict:
        """Start the TTS server if not already running."""
        try:
            return self.server_status()
        except TTSError:
            if not self.config.auto_start:
                raise
        return self.start_server()

    def start_server(self) -> dict:
        """Start the kokoro-edge server."""
        try:
            return self.server_status()
        except TTSError:
            pass

        parsed = urlparse(self._base_url)
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or 7777)

        result = subprocess.run(
            [self.config.binary, "serve", "-d", "--host", host, "--port", port],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise TTSError(
                f"Failed to start TTS server: {result.stderr.strip() or 'unknown error'}"
            )

        deadline = time.monotonic() + self.config.startup_timeout_sec
        while time.monotonic() < deadline:
            try:
                return self.server_status()
            except TTSError:
                time.sleep(0.5)
        raise TTSError(
            f"TTS server did not become ready within {self.config.startup_timeout_sec}s"
        )

    def stop_server(self) -> bool:
        """Stop the kokoro-edge server."""
        try:
            self.server_status()
        except TTSError:
            return False

        result = subprocess.run(
            [self.config.binary, "stop"], capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise TTSError(
                f"Failed to stop TTS server: {result.stderr.strip() or 'unknown error'}"
            )

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                self.server_status()
            except TTSError:
                return True
            time.sleep(0.25)
        raise TTSError("TTS stop command succeeded but daemon is still running")

    @property
    def _base_url(self) -> str:
        return self.config.server_url.rstrip("/")


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, str) and message.strip():
        return message.strip()
    return f"HTTP {response.status_code}"
