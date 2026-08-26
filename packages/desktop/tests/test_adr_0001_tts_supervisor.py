"""Desktop supervisor contracts from ADR-0001."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from localknowledge.config import Config
from localknowledge.tts import TTSModelStatus
from lk_desktop import app as desktop_app
from lk_desktop.config import DesktopConfig
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


def test_health_discovery_marks_already_running_services_healthy(monkeypatch, tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path / ".localknowledge", FakeRuntime(), FakeClient())
    probes: list[str] = []

    def probe(service) -> bool:
        probes.append(service.slug)
        return True

    monkeypatch.setattr(supervisor, "_probe", probe)

    supervisor.check_health(discover_running=True)

    assert probes == [service.slug for service in desktop_app.SERVICES]
    assert all(state.status == "running" for state in supervisor.states.values())


def test_health_tick_does_not_discover_intentionally_stopped_services(monkeypatch, tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path / ".localknowledge", FakeRuntime(), FakeClient())
    monkeypatch.setattr(
        supervisor,
        "_probe",
        lambda _service: pytest.fail("normal health ticks must skip stopped services"),
    )

    supervisor.check_health()

    assert all(state.status == "stopped" for state in supervisor.states.values())


def test_status_command_discovers_services_started_by_another_supervisor(monkeypatch) -> None:
    calls: list[bool] = []
    states = {service.slug: ServiceState(status="running") for service in desktop_app.SERVICES}
    supervisor = SimpleNamespace(
        states=states,
        check_health=lambda *, discover_running=False: calls.append(discover_running),
    )
    monkeypatch.setattr(desktop_app.Config, "load", lambda: SimpleNamespace(base_dir=Path("/tmp/lk-test")))
    monkeypatch.setattr(desktop_app, "ProcessSupervisor", lambda _base_dir: supervisor)

    result = CliRunner().invoke(desktop_app.cli, ["status"])

    assert result.exit_code == 0
    assert calls == [True]
    assert result.output.count("Running") == len(desktop_app.SERVICES)


def test_desktop_populates_menu_before_first_startup_timer(monkeypatch) -> None:
    refreshes: list[object] = []

    monkeypatch.setattr(desktop_app.rumps.App, "__init__", lambda self, *_args, **_kwargs: None)
    monkeypatch.setattr(desktop_app.Config, "load", lambda: SimpleNamespace(base_dir=Path("/tmp/lk-test")))
    monkeypatch.setattr(
        desktop_app.DesktopConfig,
        "load",
        lambda _config: SimpleNamespace(auto_start_services=True, open_client_on_start=True),
    )
    monkeypatch.setattr(desktop_app, "ProcessSupervisor", lambda _base_dir: SimpleNamespace())
    monkeypatch.setattr(
        desktop_app.LKDesktopApp,
        "_refresh_menu",
        lambda self: refreshes.append(self),
    )

    app = desktop_app.LKDesktopApp()

    assert refreshes == [app]


def test_launchagent_auto_start_never_opens_a_modal_for_missing_model(monkeypatch) -> None:
    class DownloadSupervisor:
        def __init__(self) -> None:
            self.states = {"kokoro-edge": ServiceState()}
            self.start_calls = 0

        def tts_model_status(self) -> TTSModelStatus:
            return TTSModelStatus("kokoro-82m", False, 0, 341_747_187)

        def start_all(self) -> None:
            self.start_calls += 1

    supervisor = DownloadSupervisor()
    fake_app = SimpleNamespace(
        supervisor=supervisor,
        _service_start_pending=True,
        _tts_model_status=None,
        _pending_notification=None,
    )
    fake_app._mark_model_setup_required = lambda status: desktop_app.LKDesktopApp._mark_model_setup_required(
        fake_app,
        status,
    )

    monkeypatch.setattr(
        desktop_app.rumps,
        "alert",
        lambda **_kwargs: pytest.fail("automatic LaunchAgent startup must never open a modal alert"),
    )

    desktop_app.LKDesktopApp._run_auto_start(fake_app)

    state = supervisor.states["kokoro-edge"]
    assert supervisor.start_calls == 0
    assert state.status == "setup_required"
    assert state.activity == "model_download_required"
    assert state.detail == "Model download required (341.7 MB)"
    assert fake_app._service_start_pending is False
    assert fake_app._pending_notification == (
        "TTS Model Download Required",
        "Local Knowledge setup",
        "Open the LK menu and choose Download TTS Model (341.7 MB).",
    )


def test_model_setup_notification_is_non_blocking(monkeypatch) -> None:
    notifications: list[tuple[str, str, str]] = []
    fake_app = SimpleNamespace(
        _pending_notification=(
            "TTS Model Download Required",
            "Local Knowledge setup",
            "Open the LK menu and choose Download TTS Model (341.7 MB).",
        )
    )

    monkeypatch.setattr(desktop_app.rumps, "notification", lambda *args: notifications.append(args))

    desktop_app.LKDesktopApp._dispatch_pending_notification(fake_app)

    assert notifications == [
        (
            "TTS Model Download Required",
            "Local Knowledge setup",
            "Open the LK menu and choose Download TTS Model (341.7 MB).",
        )
    ]
    assert fake_app._pending_notification is None


def test_setup_required_menu_exposes_download_action(monkeypatch, tmp_path: Path) -> None:
    class FakeMenuItem:
        def __init__(self, title: str, callback=None) -> None:
            self.title = title
            self.callback = callback
            self.state = False

    class FakeMenu:
        def __init__(self) -> None:
            self.items: list[object] = []

        def clear(self) -> None:
            self.items.clear()

        def add(self, item: object) -> None:
            self.items.append(item)

    states = {service.slug: ServiceState() for service in desktop_app.SERVICES}
    states["kokoro-edge"].status = "setup_required"
    states["kokoro-edge"].detail = "Model download required (341.7 MB)"

    def noop(*_args) -> None:
        return None

    fake_app = SimpleNamespace(
        supervisor=SimpleNamespace(states=states, logs_dir=tmp_path),
        _doc_count=None,
        _project_count=None,
        _tts_model_status=TTSModelStatus("kokoro-82m", False, 0, 341_747_187),
        _start_all=noop,
        _stop_all=noop,
        _open_logs=noop,
        _toggle_login=noop,
        _toggle_open_client_on_start=noop,
        _quit=noop,
        desktop_config=SimpleNamespace(open_client_on_start=True),
        menu=FakeMenu(),
    )

    monkeypatch.setattr(desktop_app.rumps, "MenuItem", FakeMenuItem)
    monkeypatch.setattr(desktop_app.rumps, "separator", "separator")
    monkeypatch.setattr(desktop_app, "is_installed", lambda: False)

    desktop_app.LKDesktopApp._refresh_menu(fake_app)

    titles = [item.title for item in fake_app.menu.items if isinstance(item, FakeMenuItem)]
    assert "\u25cb TTS Engine    Model download required (341.7 MB)" in titles
    assert "Download TTS Model (341.7 MB)\u2026" in titles
    assert "Start All Services" in titles
    assert "Open Client on Startup" in titles


def test_explicit_download_action_runs_existing_start_pipeline() -> None:
    class DownloadSupervisor:
        def __init__(self) -> None:
            self.start_calls = 0

        def start_all(self) -> None:
            self.start_calls += 1

    supervisor = DownloadSupervisor()
    fake_app = SimpleNamespace(
        supervisor=supervisor,
        _service_start_pending=True,
    )

    desktop_app.LKDesktopApp._run_start_all(fake_app)

    assert supervisor.start_calls == 1
    assert fake_app._service_start_pending is False


def test_desktop_config_opens_installed_client_on_start_by_default(tmp_path: Path) -> None:
    config = Config.load(tmp_path / ".localknowledge")

    desktop = DesktopConfig.load(config)

    assert desktop.open_client_on_start is True
    desktop.open_client_on_start = False
    desktop.save(config)
    assert DesktopConfig.load(config).open_client_on_start is False


def test_native_client_opens_once_after_readcast_is_healthy(monkeypatch) -> None:
    opened: list[bool] = []
    readcast_state = ServiceState(status="starting")
    fake_app = SimpleNamespace(
        _client_open_pending=True,
        supervisor=SimpleNamespace(states={"readcast": readcast_state}),
    )

    monkeypatch.setattr(desktop_app, "_open_native_client", lambda: opened.append(True) or True)

    desktop_app.LKDesktopApp._open_client_if_ready(fake_app)
    assert opened == []
    assert fake_app._client_open_pending is True

    readcast_state.status = "running"
    desktop_app.LKDesktopApp._open_client_if_ready(fake_app)
    desktop_app.LKDesktopApp._open_client_if_ready(fake_app)

    assert opened == [True]
    assert fake_app._client_open_pending is False


def test_automatic_client_launch_has_no_browser_fallback(monkeypatch) -> None:
    browsers: list[str] = []

    monkeypatch.setattr(desktop_app, "_find_native_client", lambda: None)
    monkeypatch.setattr(desktop_app.webbrowser, "open", lambda url: browsers.append(url))

    assert desktop_app._open_native_client() is False
    assert browsers == []


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
