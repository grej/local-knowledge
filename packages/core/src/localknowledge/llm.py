"""LLM client — thin wrapper around OpenAI-compatible chat completions.

Decoupled from readcast Config. Takes LLMConfig dataclass directly.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

_llm_process: subprocess.Popen | None = None


@dataclass(slots=True)
class LLMConfig:
    provider: str = "local"
    local_model: str = "mlx-community/Qwen3.5-4B-MLX-4bit"
    local_server_url: str = "http://127.0.0.1:8090"
    api_key: str = ""
    auto_start: bool = True
    startup_timeout_sec: int = 120


def _base_url(config: LLMConfig) -> str:
    if config.provider == "openai":
        return "https://api.openai.com"
    if config.provider == "anthropic":
        return "https://api.anthropic.com/v1"
    return config.local_server_url.rstrip("/")


def _headers(config: LLMConfig) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def complete(
    messages: list[dict],
    config: LLMConfig,
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> str:
    """Send a chat completion request and return the assistant message content."""
    base = _base_url(config)
    url = f"{base}/v1/chat/completions"
    body: dict = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if config.provider == "local":
        body["model"] = config.local_model

    resp = httpx.post(url, json=body, headers=_headers(config), timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def is_available(config: LLMConfig) -> bool:
    """Check whether the configured LLM endpoint is reachable."""
    try:
        base = _base_url(config)
        resp = httpx.get(f"{base}/v1/models", headers=_headers(config), timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


def ensure_llm_running(config: LLMConfig) -> None:
    """For local provider, start mlx_lm.server if not already running."""
    if config.provider != "local":
        if not config.api_key:
            raise RuntimeError(f"API key required for provider {config.provider!r}")
        return

    if is_available(config):
        return

    if config.auto_start:
        start_llm_server(config)


def start_llm_server(config: LLMConfig) -> None:
    """Spawn mlx_lm.server as a background process and wait until it responds."""
    global _llm_process

    if _llm_process is not None and _llm_process.poll() is None:
        if is_available(config):
            return
        _llm_process.terminate()
        _llm_process = None

    port = config.local_server_url.rstrip("/").rsplit(":", 1)[-1]
    cmd = [
        "python", "-m", "mlx_lm.server",
        "--model", config.local_model,
        "--port", port,
    ]
    log.info("Starting LLM server: %s", " ".join(cmd))
    _llm_process = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + config.startup_timeout_sec
    while time.monotonic() < deadline:
        if _llm_process.poll() is not None:
            raise RuntimeError("mlx_lm.server exited unexpectedly")
        if is_available(config):
            log.info("LLM server ready")
            return
        time.sleep(1.0)

    raise RuntimeError(
        f"LLM server did not become ready within {config.startup_timeout_sec}s"
    )


def stop_llm_server(config: LLMConfig) -> None:  # noqa: ARG001
    """Stop the managed mlx_lm.server process if running."""
    global _llm_process
    if _llm_process is not None:
        _llm_process.terminate()
        try:
            _llm_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _llm_process.kill()
        _llm_process = None
        log.info("LLM server stopped")


def llm_status(config: LLMConfig) -> dict:
    """Return a status dict describing the current LLM backend."""
    provider = config.provider
    available = is_available(config)
    model = config.local_model if provider == "local" else provider

    if provider == "local":
        running = _llm_process is not None and _llm_process.poll() is None
        status = "running" if running and available else "starting" if running else "stopped"
    else:
        status = "available" if available else "no_key" if not config.api_key else "unreachable"

    return {"available": available, "provider": provider, "model": model, "status": status}
