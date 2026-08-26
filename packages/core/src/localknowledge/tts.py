"""Shared kokoro-edge HTTP client and daemon lifecycle management."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import errno
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import socket
import stat
import subprocess
import threading
import time
from typing import Callable, IO, Literal, Optional
from urllib.parse import urlparse
import warnings

import httpx


DEFAULT_SOCKET_PATH = "~/.localknowledge/run/kokoro-edge.sock"
MINIMUM_KOKORO_EDGE_VERSION = (0, 2, 0)
LEGACY_ENDPOINTS = ("http://127.0.0.1:7777", "http://localhost:7777")
MODEL_STATUS_PATTERN = re.compile(
    r"(?m)^(?P<model>[^:\n]+):\s+(?P<state>downloaded|not downloaded)\s*$"
    r"\n\s*(?P<downloaded>\d+)\s*/\s*(?P<total>\d+)\s+bytes\b"
)

TTSProgressCallback = Callable[[str, str], None]


@dataclass(slots=True)
class TTSConfig:
    transport: Literal["unix", "tcp"] = "unix"
    socket_path: str = DEFAULT_SOCKET_PATH
    server_url: Optional[str] = None
    model: str = "kokoro-82m"
    voice: str = "af_sky"
    speed: float = 1.0
    language: str = "en-us"
    binary: str = "kokoro-edge"
    auto_start: bool = True
    startup_timeout_sec: int = 30
    model_download_timeout_sec: int = 1800
    model_download_stall_timeout_sec: int = 120


@dataclass(frozen=True, slots=True)
class TTSModelStatus:
    name: str
    is_available: bool
    downloaded_bytes: int
    total_bytes: int

    @property
    def percent(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return min(100, round((self.downloaded_bytes / self.total_bytes) * 100))


class TTSError(RuntimeError):
    """An actionable TTS transport or lifecycle failure."""


class TTSClient:
    """HTTP client using the same API contract over UDS or explicit TCP."""

    def __init__(
        self,
        config: TTSConfig,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        client: Optional[httpx.Client] = None,
    ):
        _validate_config(config)
        self.config = config
        if client is not None:
            self._client = client
            return

        base_url: str
        if config.transport == "unix":
            socket_path = str(_expanded_socket_path(config.socket_path))
            transport = transport or httpx.HTTPTransport(uds=socket_path)
            base_url = "http://kokoro-edge"
        else:
            base_url = str(config.server_url).rstrip("/")
        self._client = httpx.Client(base_url=base_url, transport=transport)

    @property
    def endpoint(self) -> str:
        if self.config.transport == "unix":
            return f"unix:{_expanded_socket_path(self.config.socket_path)}"
        return str(self.config.server_url).rstrip("/")

    def close(self) -> None:
        self._client.close()

    def synthesize_text(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        language: Optional[str] = None,
        response_format: str = "wav",
    ) -> bytes:
        payload = {
            "model": model or self.config.model,
            "input": text,
            "voice": voice or self.config.voice,
            "speed": self.config.speed if speed is None else speed,
            "response_format": response_format,
            "language": language or self.config.language,
        }
        response = self._request("POST", "/v1/audio/speech", timeout=120.0, json=payload)
        return response.content

    def fetch_voices(self) -> list[dict[str, object]]:
        response = self._request("GET", "/v1/voices", timeout=5.0)
        payload = self._decode_object(response, "voice")
        voices = payload.get("voices")
        if not isinstance(voices, list):
            raise TTSError(f"Invalid voice response from {self.endpoint}: expected a voices list")
        return [voice for voice in voices if isinstance(voice, dict) and "name" in voice]

    def server_status(self) -> dict[str, object]:
        response = self._request("GET", "/v1/status", timeout=2.0)
        return self._decode_object(response, "status")

    def _decode_object(self, response: httpx.Response, label: str) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise TTSError(f"Invalid {label} response from {self.endpoint}: malformed JSON") from exc
        if not isinstance(payload, dict):
            raise TTSError(f"Invalid {label} response from {self.endpoint}: expected a JSON object")
        return payload

    def _request(self, method: str, path: str, *, timeout: float, json: object = None) -> httpx.Response:
        try:
            response = self._client.request(method, path, timeout=timeout, json=json)
        except httpx.TimeoutException as exc:
            raise TTSError(f"TTS request timed out at {self.endpoint}: {exc}") from exc
        except (httpx.ConnectError, httpx.NetworkError, OSError) as exc:
            raise TTSError(_connection_error(self.endpoint, exc)) from exc
        except httpx.HTTPError as exc:
            raise TTSError(f"TTS request failed at {self.endpoint}: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(f"TTS request to {self.endpoint} failed: {_error_message(response)}")
        return response


class TTSRuntime:
    """Deterministic lifecycle controller for the configured kokoro-edge endpoint."""

    def __init__(
        self,
        config: TTSConfig,
        *,
        client_factory: Callable[[TTSConfig], object] = TTSClient,
        subprocess_factory: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        progress_callback: TTSProgressCallback | None = None,
        legacy_probe: Callable[[str], bool] | None = None,
        pid_file: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        _validate_config(config)
        self.config = config
        self._client = client_factory(config)
        self._subprocess = subprocess_factory
        self._popen = popen_factory
        self._progress_callback = progress_callback
        self._legacy_probe = legacy_probe or _probe_legacy_endpoint
        self._pid_file = pid_file or Path("~/.kokoro-edge/kokoro-edge.pid").expanduser()
        self._sleep = sleep
        self._monotonic = monotonic
        self._start_lock = threading.Lock()

    def set_progress_callback(self, callback: TTSProgressCallback | None) -> None:
        self._progress_callback = callback

    @property
    def endpoint(self) -> str:
        if self.config.transport == "unix":
            return f"unix:{self.socket_path}"
        return str(self.config.server_url).rstrip("/")

    @property
    def socket_path(self) -> Path:
        return _expanded_socket_path(self.config.socket_path)

    @property
    def binary(self) -> str:
        value = self.config.binary
        return str(Path(value).expanduser()) if "/" in value or value.startswith("~") else value

    def binary_available(self) -> bool:
        binary = Path(self.binary)
        return binary.is_file() or shutil.which(self.binary) is not None

    def model_status(self) -> TTSModelStatus:
        self._require_compatible_binary()
        return self._model_status()

    def ensure_running(self) -> dict[str, object]:
        try:
            return self._status_with_endpoint()
        except TTSError as initial_error:
            if not self.config.auto_start:
                raise initial_error

        with self._start_lock:
            try:
                return self._status_with_endpoint()
            except TTSError:
                return self._start_locked()

    def start(self) -> dict[str, object]:
        with self._start_lock:
            try:
                return self._status_with_endpoint()
            except TTSError:
                return self._start_locked()

    def stop(self) -> bool:
        endpoint_ready = True
        try:
            self._client.server_status()
        except Exception:
            endpoint_ready = False
            if not _managed_pid_is_alive(self._pid_file):
                return False

        result = self._run([self.binary, "stop"], timeout=10)
        if result.returncode != 0:
            details = _process_error(result)
            raise TTSError(f"Failed to stop kokoro-edge at {self.endpoint}: {details}")

        deadline = self._monotonic() + 5.0
        while self._monotonic() < deadline:
            try:
                self._client.server_status()
            except Exception:
                if not _managed_pid_is_alive(self._pid_file):
                    return True
                if endpoint_ready:
                    endpoint_ready = False
            self._sleep(0.1)
        raise TTSError(f"kokoro-edge stop succeeded but {self.endpoint} is still responding")

    def _start_locked(self) -> dict[str, object]:
        if self.config.transport == "unix":
            self._migrate_legacy_daemon()
            self._prepare_unix_endpoint()
        self._require_compatible_binary()
        self._ensure_model_available()
        self._emit_progress("server_start", f"Starting TTS engine with {self.config.model}")
        command = self._serve_command()
        result = self._run(command, timeout=15)
        if result.returncode != 0:
            # Another caller or process may have won after our last probe.
            try:
                return self._status_with_endpoint()
            except TTSError:
                pass
            raise TTSError(f"Failed to start kokoro-edge at {self.endpoint}: {_process_error(result)}")

        deadline = self._monotonic() + self.config.startup_timeout_sec
        last_error: Optional[Exception] = None
        while self._monotonic() < deadline:
            try:
                return self._status_with_endpoint()
            except Exception as exc:
                last_error = exc
                self._sleep(0.1)
        raise TTSError(
            f"kokoro-edge did not become ready at {self.endpoint} within "
            f"{self.config.startup_timeout_sec}s: {last_error}"
        )

    def _status_with_endpoint(self) -> dict[str, object]:
        try:
            payload = self._client.server_status()
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"TTS endpoint unavailable at {self.endpoint}: {exc}") from exc
        return payload

    def _serve_command(self) -> list[str]:
        if self.config.transport == "unix":
            return [self.binary, "serve", "-d", "--socket", str(self.socket_path), "--skip-download"]
        parsed = urlparse(str(self.config.server_url))
        return [
            self.binary,
            "serve",
            "-d",
            "--host",
            parsed.hostname or "127.0.0.1",
            "--port",
            str(parsed.port or 7777),
            "--skip-download",
        ]

    def _ensure_model_available(self) -> None:
        self._emit_progress("model_check", f"Checking TTS model {self.config.model}")
        status = self._model_status()
        if status.is_available:
            self._emit_progress("model_ready", f"TTS model {self.config.model} is ready")
            return

        size = _format_bytes(status.total_bytes)
        self._emit_progress(
            "model_download_required",
            f"TTS model {self.config.model} requires a {size} download",
        )
        self._emit_progress(
            "model_download",
            f"Downloading TTS model {self.config.model} ({status.percent}% complete)",
        )
        self._pull_model()

        self._emit_progress("model_verify", f"Verifying TTS model {self.config.model}")
        verified = self._model_status()
        if not verified.is_available or verified.downloaded_bytes != verified.total_bytes:
            raise TTSError(
                f"kokoro-edge reported a successful download, but model {self.config.model} "
                f"is incomplete ({verified.downloaded_bytes}/{verified.total_bytes} bytes)"
            )
        self._emit_progress("model_ready", f"TTS model {self.config.model} is ready")

    def _model_status(self) -> TTSModelStatus:
        command = [self.binary, "models", "list"]
        result = self._run(command, timeout=15)
        if result.returncode != 0:
            raise TTSError(f"Failed to inspect kokoro-edge models: {_process_error(result)}")
        output = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"
        for match in MODEL_STATUS_PATTERN.finditer(output):
            if match.group("model").strip() != self.config.model:
                continue
            downloaded = int(match.group("downloaded"))
            total = int(match.group("total"))
            return TTSModelStatus(
                name=self.config.model,
                is_available=match.group("state") == "downloaded" and total > 0 and downloaded == total,
                downloaded_bytes=downloaded,
                total_bytes=total,
            )
        raise TTSError(
            f"Unable to verify TTS model {self.config.model}; "
            f"'kokoro-edge models list' returned an unrecognized response"
        )

    def _pull_model(self) -> None:
        command = [self.binary, "models", "pull", self.config.model]
        try:
            process = self._popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise TTSError(
                f"Could not find {self.config.binary}. Install or upgrade kokoro-edge >= 0.2.0."
            ) from exc
        except OSError as exc:
            raise TTSError(f"Failed to start TTS model download: {exc}") from exc

        if process.stdout is None:
            _terminate_process(process)
            raise TTSError("Failed to monitor TTS model download: kokoro-edge output was unavailable")

        output_queue: Queue[str | None] = Queue()
        reader = threading.Thread(
            target=_read_process_output,
            args=(process.stdout, output_queue),
            daemon=True,
        )
        reader.start()

        started_at = self._monotonic()
        last_progress_at = started_at
        output: list[str] = []
        stream_closed = False
        while True:
            try:
                raw_line = output_queue.get(timeout=0.1)
            except Empty:
                raw_line = ""

            if raw_line is None:
                stream_closed = True
            elif raw_line:
                line = raw_line.strip()
                if line:
                    output.append(line)
                    last_progress_at = self._monotonic()
                    if not line.startswith("LLVM Profile Error"):
                        self._emit_progress("model_download", line)

            returncode = process.poll()
            if returncode is not None and stream_closed:
                break

            now = self._monotonic()
            if now - started_at >= self.config.model_download_timeout_sec:
                _terminate_process(process)
                raise TTSError(
                    f"TTS model download exceeded {self.config.model_download_timeout_sec} seconds. "
                    "Check the network connection and retry."
                )
            if now - last_progress_at >= self.config.model_download_stall_timeout_sec:
                _terminate_process(process)
                raise TTSError(
                    f"TTS model download made no progress for "
                    f"{self.config.model_download_stall_timeout_sec} seconds. "
                    "Check the network connection and retry."
                )

        returncode = process.wait(timeout=5)
        if returncode != 0:
            details = "\n".join(output[-10:]).strip() or f"exit status {returncode}"
            raise TTSError(f"Failed to download TTS model {self.config.model}: {details}")

    def _emit_progress(self, stage: str, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(stage, message)

    def _require_compatible_binary(self) -> None:
        result = self._run([self.binary, "--version"], timeout=10)
        output = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"
        match = re.search(r"(?:kokoro-edge\s+)?(\d+)\.(\d+)\.(\d+)", output)
        if result.returncode != 0 or match is None:
            raise TTSError(
                "Unable to verify kokoro-edge UDS support. Install or upgrade kokoro-edge >= 0.2.0."
            )
        version = tuple(int(part) for part in match.groups())
        if version < MINIMUM_KOKORO_EDGE_VERSION:
            raise TTSError(
                f"kokoro-edge {'.'.join(match.groups())} is incompatible; upgrade to kokoro-edge >= 0.2.0"
            )

    def _prepare_unix_endpoint(self) -> None:
        path = self.socket_path
        encoded = os.fsencode(path)
        if len(encoded) > 103:
            raise TTSError(f"Unix socket path is too long ({len(encoded)} bytes; maximum 103): {path}")

        try:
            parent_entry = path.parent.lstat()
        except FileNotFoundError:
            path.parent.mkdir(parents=True, mode=0o700)
            parent_entry = path.parent.lstat()
        if stat.S_ISLNK(parent_entry.st_mode) or not stat.S_ISDIR(parent_entry.st_mode):
            raise TTSError(f"TTS socket parent must be a directory, not a symlink: {path.parent}")
        if parent_entry.st_uid != os.geteuid():
            raise TTSError(f"Refusing to use TTS socket parent owned by uid {parent_entry.st_uid}: {path.parent}")
        os.chmod(path.parent, 0o700)
        try:
            entry = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(entry.st_mode):
            raise TTSError(f"Refusing to replace symlink at TTS socket path: {path}")
        if not stat.S_ISSOCK(entry.st_mode):
            raise TTSError(f"Refusing to replace non-socket entry at TTS socket path: {path}")
        if entry.st_uid != os.geteuid():
            raise TTSError(f"Refusing to remove TTS socket owned by uid {entry.st_uid}: {path}")
        if _managed_pid_is_alive(self._pid_file):
            raise TTSError(f"Managed kokoro-edge process is alive but its socket is unresponsive: {path}")
        if _unix_socket_accepts_connections(path):
            raise TTSError(f"A live process is already listening on Unix socket: {path}")
        path.unlink(missing_ok=True)

    def _migrate_legacy_daemon(self) -> None:
        canonical = _expanded_socket_path(DEFAULT_SOCKET_PATH)
        if self.socket_path != canonical:
            return
        active = next((endpoint for endpoint in LEGACY_ENDPOINTS if self._legacy_probe(endpoint)), None)
        if active is None:
            return
        if not _managed_pid_is_alive(self._pid_file):
            raise TTSError(
                f"Legacy kokoro-edge is responding at {active}, but readcast cannot verify ownership. "
                "Stop that listener explicitly before starting the Unix socket daemon."
            )

        warnings.warn(
            f"Migrating managed kokoro-edge from deprecated TCP endpoint {active} to {self.endpoint}",
            DeprecationWarning,
            stacklevel=2,
        )
        result = self._run([self.binary, "stop"], timeout=10)
        if result.returncode != 0:
            raise TTSError(f"Failed to stop managed legacy kokoro-edge at {active}: {_process_error(result)}")

        deadline = self._monotonic() + 5.0
        while self._monotonic() < deadline:
            if not any(self._legacy_probe(endpoint) for endpoint in LEGACY_ENDPOINTS):
                return
            self._sleep(0.1)
        raise TTSError(f"Managed legacy kokoro-edge at {active} did not stop; refusing to start a second daemon")

    def _run(self, command: list[str], *, timeout: float) -> subprocess.CompletedProcess:
        try:
            return self._subprocess(command, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise TTSError(
                f"Could not find {self.config.binary}. Install or upgrade kokoro-edge >= 0.2.0."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TTSError(f"Timed out running {' '.join(command)}") from exc


def _validate_config(config: TTSConfig) -> None:
    if config.transport not in {"unix", "tcp"}:
        raise ValueError("TTS transport must be 'unix' or 'tcp'")
    if config.transport == "unix" and not config.socket_path:
        raise ValueError("TTS socket_path is required for Unix transport")
    if config.transport == "tcp" and not config.server_url:
        raise ValueError("TTS server_url is required for TCP transport")
    if config.startup_timeout_sec <= 0:
        raise ValueError("TTS startup_timeout_sec must be positive")
    if config.model_download_timeout_sec <= 0:
        raise ValueError("TTS model_download_timeout_sec must be positive")
    if config.model_download_stall_timeout_sec <= 0:
        raise ValueError("TTS model_download_stall_timeout_sec must be positive")


def _expanded_socket_path(value: str) -> Path:
    return Path(value).expanduser().absolute()


def _format_bytes(value: int) -> str:
    if value <= 0:
        return "model asset"
    return f"{value / 1_000_000:.1f} MB"


def _read_process_output(stream: IO[str], output_queue: Queue[str | None]) -> None:
    try:
        for line in stream:
            output_queue.put(line)
    finally:
        with suppress(OSError):
            stream.close()
        output_queue.put(None)


def _terminate_process(process: subprocess.Popen) -> None:
    with suppress(OSError):
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with suppress(OSError):
            process.kill()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=2)


def _managed_pid_is_alive(pid_file: Path) -> bool:
    try:
        entry = pid_file.lstat()
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.geteuid():
            return False
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _probe_legacy_endpoint(endpoint: str) -> bool:
    try:
        response = httpx.get(f"{endpoint}/v1/status", timeout=0.5)
        if response.status_code != 200 or response.headers.get("server", "").lower() != "kokoro-edge":
            return False
        payload = response.json()
    except (httpx.HTTPError, OSError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("model"), str)
        and isinstance(payload.get("models_loaded"), list)
        and isinstance(payload.get("voices_available"), list)
    )


def _unix_socket_accepts_connections(path: Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        probe.connect(str(path))
    except OSError as exc:
        return exc.errno not in {errno.ECONNREFUSED, errno.ENOENT}
    finally:
        probe.close()
    return True


def _connection_error(endpoint: str, error: BaseException) -> str:
    message = str(error)
    lowered = message.lower()
    if "permission" in lowered or "denied" in lowered:
        kind = "permission denied"
    elif "timed out" in lowered or "timeout" in lowered:
        kind = "timeout"
    elif "refused" in lowered:
        kind = "connection refused"
    elif "no such file" in lowered:
        kind = "socket is missing"
    else:
        kind = "connection failed"
    return f"TTS {kind} at {endpoint}: {message}"


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return f"HTTP {response.status_code}"


def _process_error(result: subprocess.CompletedProcess) -> str:
    return str(getattr(result, "stderr", "")).strip() or str(getattr(result, "stdout", "")).strip() or "unknown error"
