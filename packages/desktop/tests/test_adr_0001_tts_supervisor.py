"""Desktop supervisor contracts from ADR-0001."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from localknowledge.config import Config
from localknowledge.tts import TTSModelStatus
from lk_desktop import app as desktop_app
from lk_desktop.services import SERVICE_MAP
from lk_desktop.supervisor import ProcessSupervisor, ServiceState


class FakeRuntime:
    def __init__(self, status: dict[str, object] | None = None) -> None:
        self.status = status or {"model": "kokoro-82m", "models_loaded": ["kokoro-82m"]}
        self.ensure_calls = 0
        self.stop_calls = 0
        self.progress_callback = None

    def set_progress_callback(self, callback) -> None:
        self.progress_callback = callback

    def model_status(self) -> TTSModelStatus:
        return TTSModelStatus("kokoro-82m", True, 341_747_187, 341_747_187)

    def ensure_running(self) -> dict[str, object]:
        self.ensure_calls += 1
        return self.status

    def stop(self) -> bool:
        self.stop_calls += 1
        return True


class FakeClient:
    def __init__(self, status: dict[str, object] | None = None) -> None:
        self.status = status or {"model": "kokoro-82m", "models_loaded": ["kokoro-82m"]}
        self.status_calls = 0

    def server_status(self) -> dict[str, object]:
        self.status_calls += 1
        return self.status


def _supervisor(base_dir: Path, runtime: FakeRuntime, client: FakeClient) -> ProcessSupervisor:
    config = Config.load(base_dir)
    return ProcessSupervisor(
        base_dir,
        config=config,
        tts_runtime=runtime,
        tts_client=client,
    )


def test_tts_service_definition_has_no_static_tcp_endpoint_or_process_commands() -> None:
    tts = SERVICE_MAP["kokoro-edge"]

    assert tts.start_cmd is None
    assert tts.health_url is None
    assert tts.stop_cmd is None
    assert "127.0.0.1:7777" not in repr(tts)
    assert "localhost:7777" not in repr(tts)


def test_starting_tts_delegates_to_runtime_without_spawning_a_process(monkeypatch, tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client = FakeClient()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, client)

    monkeypatch.setattr(
        "lk_desktop.supervisor.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("TTS must not be launched as a foreground process"),
    )

    supervisor._start_one(SERVICE_MAP["kokoro-edge"])

    assert runtime.ensure_calls == 1
    assert supervisor.states["kokoro-edge"].status == "running"
    assert supervisor.states["kokoro-edge"].process is None


def test_tts_download_progress_is_exposed_in_service_state(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, FakeClient())

    assert runtime.progress_callback is not None
    runtime.progress_callback("model_download", "Downloading model.onnx... 170 MB/341.7 MB (50%)")

    state = supervisor.states["kokoro-edge"]
    assert state.activity == "model_download"
    assert state.detail == "Downloading model.onnx... 170 MB/341.7 MB (50%)"


def test_health_tick_does_not_restart_tts_during_model_download(monkeypatch, tmp_path: Path) -> None:
    runtime = FakeRuntime()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, FakeClient())
    state = supervisor.states["kokoro-edge"]
    state.status = "starting"
    state.activity = "model_download"
    state.detail = "Downloading kokoro-82m (10%)"

    monkeypatch.setattr(
        supervisor,
        "_probe",
        lambda _service: pytest.fail("an active synchronous TTS start must not be probed or restarted"),
    )

    supervisor.check_health()

    assert runtime.ensure_calls == 0
    assert runtime.stop_calls == 0
    assert state.status == "starting"
    assert state.detail == "Downloading kokoro-82m (10%)"


def test_desktop_prompts_before_a_required_model_download(monkeypatch) -> None:
    alerts: list[dict[str, object]] = []

    class DownloadSupervisor:
        states = {"kokoro-edge": ServiceState()}

        def tts_model_status(self) -> TTSModelStatus:
            return TTSModelStatus("kokoro-82m", False, 0, 341_747_187)

    fake_app = SimpleNamespace(
        supervisor=DownloadSupervisor(),
        # A prior failed attempt must not suppress the prompt on retry.
        _download_notice_shown=True,
    )

    def alert(**kwargs):
        alerts.append(kwargs)
        return 1

    monkeypatch.setattr(desktop_app.rumps, "alert", alert)

    assert desktop_app.LKDesktopApp._confirm_model_download(fake_app) is True
    assert fake_app._download_notice_shown is True
    assert alerts[0]["title"] == "TTS Model Download Required"
    assert alerts[0]["ok"] == "Download"
    assert alerts[0]["cancel"] == "Not Now"
    assert "341.7 MB" in alerts[0]["message"]
    assert "progress" in alerts[0]["message"]
    assert "SHA-256" in alerts[0]["message"]


def test_tts_probe_uses_shared_client_status_not_httpx_or_a_tcp_health_url(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client = FakeClient()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, client)

    assert supervisor._probe(SERVICE_MAP["kokoro-edge"]) is True
    assert client.status_calls == 1


def test_http_health_probe_reads_only_headers_for_sse_endpoint(monkeypatch, tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path / ".localknowledge", FakeRuntime(), FakeClient())
    calls: list[tuple[str, str, int]] = []

    class HeaderOnlyResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def stream(method: str, url: str, *, timeout: int):
        calls.append((method, url, timeout))
        return HeaderOnlyResponse()

    monkeypatch.setattr("lk_desktop.supervisor.httpx.stream", stream)
    monkeypatch.setattr(
        "lk_desktop.supervisor.httpx.get",
        lambda *_args, **_kwargs: pytest.fail("SSE probes must not wait for the response body"),
    )

    assert supervisor._probe(SERVICE_MAP["lk-mcp"]) is True
    assert calls == [("GET", "http://127.0.0.1:8322/sse", 2)]


def test_tts_stop_delegates_to_the_same_runtime_that_started_it(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client = FakeClient()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, client)
    supervisor._start_one(SERVICE_MAP["kokoro-edge"])

    supervisor._stop_one(SERVICE_MAP["kokoro-edge"])

    assert runtime.stop_calls == 1
    assert supervisor.states["kokoro-edge"].status == "stopped"


def test_dependency_readiness_waits_for_a_successful_uds_status_probe(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    client = FakeClient()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, client)

    assert supervisor._wait_healthy("kokoro-edge", timeout=0.1) is True

    assert client.status_calls == 1
    assert supervisor.states["kokoro-edge"].status == "running"


def test_desktop_uses_the_shared_configured_socket_path(tmp_path: Path) -> None:
    base_dir = tmp_path / ".localknowledge"
    config = Config.load(base_dir)
    config.tts.socket_path = str(base_dir / "custom-run" / "tts.sock")
    config.save()

    supervisor = ProcessSupervisor(config=config)

    assert supervisor.tts_config.socket_path == str(base_dir / "custom-run" / "tts.sock")
    assert "kokoro-edge.sock" not in str(supervisor.tts_config.socket_path)


def test_failed_tts_start_is_reported_without_a_foreground_process(tmp_path: Path) -> None:
    class FailingRuntime(FakeRuntime):
        def ensure_running(self) -> dict[str, object]:
            self.ensure_calls += 1
            raise RuntimeError("socket permission denied")

    runtime = FailingRuntime()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, FakeClient())

    supervisor._start_one(SERVICE_MAP["kokoro-edge"])

    assert runtime.ensure_calls == 1
    assert supervisor.states["kokoro-edge"].status == "error"
    assert supervisor.states["kokoro-edge"].process is None


def test_failed_tts_start_retries_through_shared_runtime_after_backoff(tmp_path: Path) -> None:
    class RecoveringRuntime(FakeRuntime):
        ready = False

        def ensure_running(self) -> dict[str, object]:
            self.ensure_calls += 1
            if self.ensure_calls == 1:
                raise RuntimeError("socket unavailable")
            self.ready = True
            return self.status

    class RuntimeClient(FakeClient):
        def __init__(self, runtime: RecoveringRuntime) -> None:
            super().__init__()
            self.runtime = runtime

        def server_status(self) -> dict[str, object]:
            self.status_calls += 1
            if not self.runtime.ready:
                raise RuntimeError("socket unavailable")
            return self.status

    runtime = RecoveringRuntime()
    supervisor = _supervisor(tmp_path / ".localknowledge", runtime, RuntimeClient(runtime))
    service = SERVICE_MAP["kokoro-edge"]
    supervisor._start_one(service)
    supervisor.states[service.slug].last_restart = 0

    supervisor.check_health()

    assert runtime.ensure_calls == 2
    assert runtime.stop_calls == 1
    assert supervisor.states[service.slug].restart_count == 1
    assert supervisor.states[service.slug].status == "running"


def test_start_all_does_not_launch_readcast_when_tts_never_becomes_healthy(monkeypatch, tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path / ".localknowledge", FakeRuntime(), FakeClient())
    started: list[str] = []

    def start_one(service) -> None:
        started.append(service.slug)
        supervisor.states[service.slug].status = "starting"

    monkeypatch.setattr(supervisor, "_start_one", start_one)
    monkeypatch.setattr(supervisor, "_wait_healthy", lambda slug, timeout: False)

    supervisor.start_all()

    assert "kokoro-edge" in started
    assert "readcast" not in started
    assert supervisor.states["readcast"].status == "error"


def test_start_all_probes_tts_before_launching_readcast(monkeypatch, tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path / ".localknowledge", FakeRuntime(), FakeClient())
    events: list[str] = []

    monkeypatch.setattr(supervisor, "_start_one", lambda service: events.append(f"start:{service.slug}"))
    monkeypatch.setattr(
        supervisor,
        "_wait_healthy",
        lambda slug, timeout: events.append(f"probe:{slug}") or True,
    )

    supervisor.start_all()

    assert events.index("probe:kokoro-edge") < events.index("start:readcast")
