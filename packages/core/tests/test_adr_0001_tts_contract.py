"""Executable contracts from ADR-0001 for the shared TTS boundary.

These tests intentionally inject the HTTP transport and subprocess factory.  A
readcast or desktop caller must not need to know how the UDS client or daemon
process is constructed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import tomllib
import uuid

import httpx
import pytest

from localknowledge.config import Config
from localknowledge.tts import TTSClient, TTSConfig, TTSError, TTSRuntime


DEFAULT_SOCKET = "~/.localknowledge/run/kokoro-edge.sock"


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.handler(request)
        response.request = request
        return response


class FakeClient:
    def __init__(self, status: dict[str, object] | Exception):
        self.status = status
        self.status_calls = 0

    def server_status(self) -> dict[str, object]:
        self.status_calls += 1
        if isinstance(self.status, Exception):
            raise self.status
        return self.status


def _status_payload() -> dict[str, object]:
    return {
        "version": "0.2.0",
        "model": "kokoro-82m",
        "models_loaded": ["kokoro-82m"],
        "voices_available": ["af_sky"],
        "uptime_seconds": 12,
    }


def _model_list_output(*, downloaded: int = 341_747_187, total: int = 341_747_187) -> str:
    state = "downloaded" if downloaded == total and total > 0 else "not downloaded"
    return f"kokoro-82m: {state}\n  {downloaded} / {total} bytes (341.7 MB / 341.7 MB)\n  /tmp/kokoro-82m\n"


class FakePullProcess:
    def __init__(self, output: str, returncode: int = 0) -> None:
        self.stdout = io.StringIO(output)
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


@pytest.fixture
def socket_dir() -> Path:
    path = Path("/tmp") / f"lk-tts-contract-{uuid.uuid4().hex}"
    path.mkdir(mode=0o700)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_tts_config_defaults_to_the_canonical_uds_endpoint() -> None:
    config = TTSConfig()

    assert config.transport == "unix"
    assert config.socket_path == DEFAULT_SOCKET
    assert config.server_url is None
    assert config.model == "kokoro-82m"
    assert config.voice == "af_sky"
    assert config.speed == 1.0
    assert config.language == "en-us"
    assert config.binary == "kokoro-edge"
    assert config.auto_start is True
    assert config.startup_timeout_sec == 30
    assert config.model_download_timeout_sec == 1800
    assert config.model_download_stall_timeout_sec == 120


@pytest.mark.parametrize("legacy_url", [None, "http://127.0.0.1:7777", "http://localhost:7777"])
def test_config_migrates_known_loopback_defaults_to_uds(base_dir: Path, legacy_url: str | None) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    value = "server_url = %r\n" % legacy_url if legacy_url is not None else ""
    (base_dir / "config.toml").write_text("[tts]\n" + value, encoding="utf-8")
    before = (base_dir / "config.toml").read_text(encoding="utf-8")

    config = Config.load(base_dir)

    assert config.tts.transport == "unix"
    assert config.tts.socket_path == DEFAULT_SOCKET
    assert config.tts.server_url is None
    # Loading a legacy file is an in-memory migration; it does not write as a side effect.
    assert (base_dir / "config.toml").read_text(encoding="utf-8") == before


def test_config_migrates_custom_url_to_explicit_tcp_with_warning(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "config.toml").write_text(
        '[tts]\nserver_url = "http://192.0.2.44:9000"\n',
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match="TCP"):
        config = Config.load(base_dir)

    assert config.tts.transport == "tcp"
    assert config.tts.server_url == "http://192.0.2.44:9000"


def test_unix_config_save_omits_irrelevant_tcp_setting(base_dir: Path) -> None:
    Config.load(base_dir)

    saved = (base_dir / "config.toml").read_text(encoding="utf-8")

    assert 'transport = "unix"' in saved
    assert f'socket_path = "{DEFAULT_SOCKET}"' in saved
    assert "server_url" not in tomllib.loads(saved)["tts"]


def test_tcp_config_requires_an_explicit_server_url(base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "config.toml").write_text('[tts]\ntransport = "tcp"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="server_url.*TCP|TCP.*server_url"):
        Config.load(base_dir)


def test_client_builds_an_httpx_uds_transport_and_synthetic_base_url(monkeypatch, tmp_path: Path) -> None:
    created_transports: list[dict[str, object]] = []
    created_clients: list[dict[str, object]] = []

    class FakeHTTPTransport:
        def __init__(self, **kwargs):
            created_transports.append(kwargs)

    class FakeHTTPClient:
        def __init__(self, **kwargs):
            created_clients.append(kwargs)

        def close(self) -> None:
            return None

    monkeypatch.setattr("localknowledge.tts.httpx.HTTPTransport", FakeHTTPTransport)
    monkeypatch.setattr("localknowledge.tts.httpx.Client", FakeHTTPClient)
    config = TTSConfig(socket_path=str(tmp_path / "kokoro-edge.sock"))

    TTSClient(config)

    assert created_transports == [{"uds": str(tmp_path / "kokoro-edge.sock")}]
    assert created_clients[0]["transport"] is not None
    assert created_clients[0]["base_url"] == "http://kokoro-edge"


def test_client_uses_only_the_explicit_url_in_tcp_mode(monkeypatch) -> None:
    created_transports: list[dict[str, object]] = []
    created_clients: list[dict[str, object]] = []

    class FakeHTTPTransport:
        def __init__(self, **kwargs):
            created_transports.append(kwargs)

    class FakeHTTPClient:
        def __init__(self, **kwargs):
            created_clients.append(kwargs)

    monkeypatch.setattr("localknowledge.tts.httpx.HTTPTransport", FakeHTTPTransport)
    monkeypatch.setattr("localknowledge.tts.httpx.Client", FakeHTTPClient)

    TTSClient(TTSConfig(transport="tcp", server_url="http://127.0.0.1:9000"))

    assert created_transports == []
    assert created_clients == [{"base_url": "http://127.0.0.1:9000", "transport": None}]


def test_client_uses_one_http_contract_for_status_voices_and_speech() -> None:
    responses = {
        "/v1/status": httpx.Response(200, json=_status_payload()),
        "/v1/voices": httpx.Response(200, json={"voices": [{"name": "af_sky", "language": "en-us"}]}),
        "/v1/audio/speech": httpx.Response(200, content=b"RIFF-wav-bytes"),
    }
    transport = RecordingTransport(lambda request: responses[request.url.raw_path.decode()])
    config = TTSConfig()
    client = TTSClient(config, transport=transport)

    assert client.server_status()["model"] == "kokoro-82m"
    assert client.fetch_voices() == [{"name": "af_sky", "language": "en-us"}]
    assert client.synthesize_text(
        "hello",
        model="other-model",
        voice="af_heart",
        speed=1.25,
        language="en-gb",
        response_format="wav",
    ) == b"RIFF-wav-bytes"

    assert [(request.method, request.url.path) for request in transport.requests] == [
        ("GET", "/v1/status"),
        ("GET", "/v1/voices"),
        ("POST", "/v1/audio/speech"),
    ]
    speech_request = transport.requests[-1]
    assert speech_request.read() == (
        b'{"model":"other-model","input":"hello","voice":"af_heart",'
        b'"speed":1.25,"response_format":"wav","language":"en-gb"}'
    )


def test_client_normalizes_timeout_and_http_errors_without_tcp_fallback() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("socket timed out")

    transport = RecordingTransport(timeout)
    config = TTSConfig()
    client = TTSClient(config, transport=transport)

    with pytest.raises(TTSError, match="timeout|timed out"):
        client.server_status()

    assert all("127.0.0.1:7777" not in str(request.url) for request in transport.requests)

    error_transport = RecordingTransport(
        lambda request: httpx.Response(503, json={"message": "model is warming"}, request=request)
    )
    error_client = TTSClient(config, transport=error_transport)
    with pytest.raises(TTSError, match="model is warming"):
        error_client.server_status()


def test_client_normalizes_malformed_json_with_the_uds_endpoint() -> None:
    transport = RecordingTransport(
        lambda request: httpx.Response(200, content=b"not-json", request=request)
    )
    client = TTSClient(TTSConfig(), transport=transport)

    with pytest.raises(TTSError, match=r"unix:.*malformed JSON"):
        client.server_status()


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("[Errno 2] No such file or directory", "socket is missing"),
        ("[Errno 61] Connection refused", "connection refused"),
        ("[Errno 13] Permission denied", "permission denied"),
    ],
)
def test_client_distinguishes_unix_connection_failures(message: str, kind: str) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(message, request=request)

    client = TTSClient(TTSConfig(), transport=RecordingTransport(fail))

    with pytest.raises(TTSError, match=rf"{kind}.*unix:"):
        client.server_status()


def test_runtime_reuses_a_healthy_daemon_without_spawning(tmp_path: Path) -> None:
    client = FakeClient(_status_payload())
    spawned: list[list[str]] = []

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(tmp_path / "kokoro-edge.sock")),
        client_factory=lambda _config: client,
        subprocess_factory=lambda command, **_kwargs: spawned.append(command),
    )

    assert runtime.ensure_running() == _status_payload()
    assert client.status_calls == 1
    assert spawned == []


def test_runtime_respects_disabled_auto_start(socket_dir: Path) -> None:
    original = TTSError("Unix socket is missing")
    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock"), auto_start=False),
        client_factory=lambda _config: FakeClient(original),
        subprocess_factory=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
    )

    with pytest.raises(TTSError, match="Unix socket is missing"):
        runtime.ensure_running()


def test_runtime_keeps_a_live_socket_for_a_healthy_daemon(socket_dir: Path) -> None:
    socket_path = socket_dir / "kokoro-edge.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)

    try:
        runtime = TTSRuntime(
            TTSConfig(socket_path=str(socket_path)),
            client_factory=lambda _config: FakeClient(_status_payload()),
            subprocess_factory=lambda *_args, **_kwargs: pytest.fail("must reuse the live daemon"),
        )

        assert runtime.ensure_running() == _status_payload()
        assert socket_path.exists()
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)


def test_runtime_concurrent_start_race_spawns_once_and_reprobes(socket_dir: Path) -> None:
    class RaceClient:
        def __init__(self) -> None:
            self.ready = False
            self.calls = 0
            self.lock = threading.Lock()

        def server_status(self) -> dict[str, object]:
            with self.lock:
                self.calls += 1
                if not self.ready:
                    raise TTSError("unix endpoint refused connection")
                return _status_payload()

    client = RaceClient()
    spawn_count = 0
    spawn_lock = threading.Lock()

    def spawn(_command, **_kwargs):
        nonlocal spawn_count
        if _command[-1] == "--version":
            return subprocess.CompletedProcess(_command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        if _command[-2:] == ["models", "list"]:
            return subprocess.CompletedProcess(_command, 0, stdout=_model_list_output(), stderr="")
        with spawn_lock:
            spawn_count += 1
            client.ready = True
        return subprocess.CompletedProcess([], 0)

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock"), startup_timeout_sec=1),
        client_factory=lambda _config: client,
        subprocess_factory=spawn,
        sleep=lambda _seconds: None,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: runtime.ensure_running(), range(2)))

    assert results == [_status_payload(), _status_payload()]
    assert spawn_count == 1


def test_runtime_downloads_and_verifies_a_missing_model_before_starting(socket_dir: Path) -> None:
    client = FakeClient(TTSError("Unix socket is missing"))
    model_downloaded = False
    run_commands: list[list[str]] = []
    pull_commands: list[list[str]] = []
    events: list[tuple[str, str]] = []

    def run(command, **_kwargs):
        run_commands.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        if command[-2:] == ["models", "list"]:
            output = _model_list_output() if model_downloaded else _model_list_output(downloaded=0)
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
        assert command[-1] == "--skip-download"
        client.status = _status_payload()
        return subprocess.CompletedProcess(command, 0, stdout="started", stderr="")

    def popen(command, **_kwargs):
        nonlocal model_downloaded
        pull_commands.append(command)
        model_downloaded = True
        return FakePullProcess(
            "Downloading model.onnx...\n"
            "Downloading model.onnx... 341.7 MB/341.7 MB (100%)\n"
            "Model ready: kokoro-82m\n"
        )

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock"), startup_timeout_sec=1),
        client_factory=lambda _config: client,
        subprocess_factory=run,
        popen_factory=popen,
        progress_callback=lambda stage, message: events.append((stage, message)),
        sleep=lambda _seconds: None,
    )

    assert runtime.ensure_running() == _status_payload()
    assert pull_commands == [["kokoro-edge", "models", "pull", "kokoro-82m"]]
    assert sum(command[-2:] == ["models", "list"] for command in run_commands) == 2
    assert run_commands[-1] == [
        "kokoro-edge",
        "serve",
        "-d",
        "--socket",
        str(socket_dir / "kokoro-edge.sock"),
        "--skip-download",
    ]
    stages = [stage for stage, _message in events]
    assert stages[0:3] == ["model_check", "model_download_required", "model_download"]
    assert "model_verify" in stages
    assert stages[-2:] == ["model_ready", "server_start"]


def test_runtime_rejects_a_model_that_remains_incomplete_after_pull(socket_dir: Path) -> None:
    client = FakeClient(TTSError("Unix socket is missing"))
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        if command[-2:] == ["models", "list"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=_model_list_output(downloaded=100, total=200),
                stderr="",
            )
        raise AssertionError(f"daemon must not start with an incomplete model: {command}")

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock")),
        client_factory=lambda _config: client,
        subprocess_factory=run,
        popen_factory=lambda command, **_kwargs: FakePullProcess("Model ready: kokoro-82m\n"),
    )

    with pytest.raises(TTSError, match=r"successful download.*incomplete.*100/200"):
        runtime.ensure_running()

    assert not any("serve" in command for command in commands)


def test_runtime_reports_model_download_command_failure(socket_dir: Path) -> None:
    client = FakeClient(TTSError("Unix socket is missing"))

    def run(command, **_kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        if command[-2:] == ["models", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout=_model_list_output(downloaded=0), stderr="")
        raise AssertionError(f"daemon must not start after a failed download: {command}")

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock")),
        client_factory=lambda _config: client,
        subprocess_factory=run,
        popen_factory=lambda command, **_kwargs: FakePullProcess("network unreachable\n", returncode=2),
    )

    with pytest.raises(TTSError, match=r"Failed to download.*network unreachable"):
        runtime.ensure_running()


def test_runtime_aborts_a_stalled_model_download(socket_dir: Path) -> None:
    client = FakeClient(TTSError("Unix socket is missing"))

    class StalledPullProcess(FakePullProcess):
        def __init__(self) -> None:
            super().__init__("")
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout: float) -> int:
            return -15 if self.terminated else 0

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

    stalled = StalledPullProcess()
    clock = 0

    def monotonic() -> float:
        nonlocal clock
        clock += 1
        return float(clock)

    def run(command, **_kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        if command[-2:] == ["models", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout=_model_list_output(downloaded=0), stderr="")
        raise AssertionError(f"daemon must not start after a stalled download: {command}")

    runtime = TTSRuntime(
        TTSConfig(
            socket_path=str(socket_dir / "kokoro-edge.sock"),
            model_download_timeout_sec=10,
            model_download_stall_timeout_sec=1,
        ),
        client_factory=lambda _config: client,
        subprocess_factory=run,
        popen_factory=lambda command, **_kwargs: stalled,
        monotonic=monotonic,
    )

    with pytest.raises(TTSError, match=r"no progress for 1 seconds.*network"):
        runtime.ensure_running()

    assert stalled.terminated is True


def test_runtime_rejects_an_incompatible_binary_with_upgrade_guidance(socket_dir: Path) -> None:
    client = FakeClient(TTSError("unix endpoint is unavailable"))

    def subprocess_factory(command, **_kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.1.0", stderr="")
        raise AssertionError(f"daemon must not start: {command}")

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock")),
        client_factory=lambda _config: client,
        subprocess_factory=subprocess_factory,
    )

    with pytest.raises(TTSError, match=r"kokoro-edge.*0\.2\.0|upgrade"):
        runtime.ensure_running()


def test_runtime_reports_failed_spawn_when_no_concurrent_winner(socket_dir: Path) -> None:
    client = FakeClient(TTSError("Unix socket is missing"))

    def run(command, **_kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        if command[-2:] == ["models", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout=_model_list_output(), stderr="")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="bind failed")

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock")),
        client_factory=lambda _config: client,
        subprocess_factory=run,
    )

    with pytest.raises(TTSError, match="bind failed"):
        runtime.ensure_running()


def test_runtime_stop_uses_pid_managed_command_and_verifies_shutdown(socket_dir: Path) -> None:
    class StopClient:
        ready = True

        def server_status(self) -> dict[str, object]:
            if not self.ready:
                raise TTSError("Unix socket is missing")
            return _status_payload()

    client = StopClient()
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(command)
        client.ready = False
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_dir / "kokoro-edge.sock")),
        client_factory=lambda _config: client,
        subprocess_factory=run,
        pid_file=socket_dir / "missing.pid",
        sleep=lambda _seconds: None,
    )

    assert runtime.stop() is True
    assert commands == [["kokoro-edge", "stop"]]


def test_runtime_rejects_overlong_socket_path_before_spawning() -> None:
    path = "/tmp/" + "x" * 104
    runtime = TTSRuntime(
        TTSConfig(socket_path=path),
        client_factory=lambda _config: FakeClient(TTSError("Unix socket is missing")),
        subprocess_factory=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
    )

    with pytest.raises(TTSError, match="too long.*maximum 103"):
        runtime.ensure_running()


def test_runtime_removes_only_an_owned_stale_socket_before_start(socket_dir: Path) -> None:
    socket_path = socket_dir / "kokoro-edge.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.close()
    assert socket_path.exists()

    client = FakeClient(TTSError("unix endpoint refused connection"))
    spawn_observations: list[tuple[list[str], bool]] = []

    def spawn(command, **_kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        if command[-2:] == ["models", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout=_model_list_output(), stderr="")
        spawn_observations.append((command, socket_path.exists()))
        client.status = _status_payload()
        return subprocess.CompletedProcess(command, 0)

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_path), startup_timeout_sec=1),
        client_factory=lambda _config: client,
        subprocess_factory=spawn,
        pid_file=socket_dir / "missing.pid",
        sleep=lambda _seconds: None,
    )

    assert runtime.ensure_running() == _status_payload()
    assert spawn_observations == [
        (["kokoro-edge", "serve", "-d", "--socket", str(socket_path), "--skip-download"], False)
    ]


@pytest.mark.parametrize("kind", ["regular", "symlink"])
def test_runtime_never_removes_a_regular_file_or_symlink_at_socket_path(socket_dir: Path, kind: str) -> None:
    socket_path = socket_dir / "kokoro-edge.sock"
    target = socket_dir / "unrelated.txt"
    target.write_text("keep me", encoding="utf-8")
    if kind == "regular":
        socket_path.write_text("keep me too", encoding="utf-8")
    else:
        socket_path.symlink_to(target)

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_path)),
        client_factory=lambda _config: FakeClient(TTSError("unix endpoint unavailable")),
        subprocess_factory=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
    )

    with pytest.raises(TTSError, match="socket|symlink|regular|endpoint"):
        runtime.ensure_running()

    assert socket_path.exists() or socket_path.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep me"


@pytest.mark.skipif(os.geteuid() != 0, reason="requires root to create a foreign-owned socket entry")
def test_runtime_never_removes_a_foreign_owned_socket(socket_dir: Path) -> None:
    socket_path = socket_dir / "kokoro-edge.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.close()
    os.chown(socket_path, 1, -1)

    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_path)),
        client_factory=lambda _config: FakeClient(TTSError("unix endpoint refused connection")),
        subprocess_factory=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
    )

    with pytest.raises(TTSError, match="owner|permission|socket|endpoint"):
        runtime.ensure_running()
    assert socket_path.exists()


def test_runtime_rejects_a_symlinked_socket_parent(socket_dir: Path) -> None:
    target = socket_dir / "target"
    target.mkdir()
    parent = socket_dir / "run"
    parent.symlink_to(target, target_is_directory=True)
    socket_path = parent / "kokoro-edge.sock"
    runtime = TTSRuntime(
        TTSConfig(socket_path=str(socket_path)),
        client_factory=lambda _config: FakeClient(TTSError("unix endpoint unavailable")),
        subprocess_factory=lambda *_args, **_kwargs: pytest.fail("must not spawn"),
    )

    with pytest.raises(TTSError, match="parent|symlink"):
        runtime.ensure_running()

    assert parent.is_symlink()


def test_runtime_migrates_only_an_owned_legacy_tcp_daemon(monkeypatch, socket_dir: Path) -> None:
    monkeypatch.setenv("HOME", str(socket_dir))
    pid_file = socket_dir / ".kokoro-edge" / "kokoro-edge.pid"
    pid_file.parent.mkdir()
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    legacy_ready = True
    client = FakeClient(TTSError("Unix socket is missing"))
    commands: list[list[str]] = []

    def legacy_probe(_endpoint: str) -> bool:
        return legacy_ready

    def run(command, **_kwargs):
        nonlocal legacy_ready
        commands.append(command)
        if command[-1] == "stop":
            legacy_ready = False
        elif command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="kokoro-edge 0.2.0", stderr="")
        elif command[-2:] == ["models", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout=_model_list_output(), stderr="")
        else:
            client.status = _status_payload()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runtime = TTSRuntime(
        TTSConfig(),
        client_factory=lambda _config: client,
        subprocess_factory=run,
        legacy_probe=legacy_probe,
        pid_file=pid_file,
        sleep=lambda _seconds: None,
    )

    with pytest.warns(DeprecationWarning, match="deprecated TCP"):
        assert runtime.ensure_running() == _status_payload()

    assert commands[0] == ["kokoro-edge", "stop"]
    assert commands[-1] == [
        "kokoro-edge",
        "serve",
        "-d",
        "--socket",
        str(socket_dir / ".localknowledge/run/kokoro-edge.sock"),
        "--skip-download",
    ]


def test_runtime_refuses_to_kill_an_unowned_legacy_listener(monkeypatch, socket_dir: Path) -> None:
    monkeypatch.setenv("HOME", str(socket_dir))
    commands: list[list[str]] = []
    runtime = TTSRuntime(
        TTSConfig(),
        client_factory=lambda _config: FakeClient(TTSError("Unix socket is missing")),
        subprocess_factory=lambda command, **_kwargs: commands.append(command),
        legacy_probe=lambda _endpoint: True,
        pid_file=socket_dir / "missing.pid",
    )

    with pytest.raises(TTSError, match="cannot verify ownership|Stop that listener"):
        runtime.ensure_running()

    assert commands == []
