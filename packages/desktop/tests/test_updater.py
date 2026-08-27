"""Contracts for upgrading an installed Pixi global environment."""

from __future__ import annotations

import signal
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from lk_desktop import app as desktop_app
from lk_desktop import updater


def _global_layout(tmp_path: Path, environment: str = "local-knowledge") -> tuple[Path, Path]:
    pixi_home = tmp_path / ".pixi"
    executable = pixi_home / "envs" / environment / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.touch()
    manifest = pixi_home / "manifests" / "pixi-global.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f'version = 1\n\n[envs.{environment}]\ndependencies = {{ local-knowledge = "*" }}\n')
    return executable, executable.parent.parent


def test_global_environment_is_derived_from_the_installed_interpreter(tmp_path: Path) -> None:
    executable, env_dir = _global_layout(tmp_path)

    assert updater._global_environment(executable) == (env_dir, "local-knowledge")


def test_editable_environment_is_rejected(tmp_path: Path) -> None:
    executable = tmp_path / ".pixi" / "envs" / "default" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.touch()

    with pytest.raises(updater.UpgradeError, match="pixi global install"):
        updater._global_environment(executable)


def test_process_discovery_only_matches_executables_in_the_installed_environment(monkeypatch, tmp_path: Path) -> None:
    _, env_dir = _global_layout(tmp_path)
    env_bin = env_dir / "bin"
    output = "\n".join(
        [
            f"101 {env_bin / 'python'} {env_bin / 'lk-desktop'}",
            f"102 {env_bin / 'python3.14'} {env_bin / 'readcast'} web --no-open",
            f"103 {env_bin / 'kokoro-edge'} serve --socket /tmp/tts.sock",
            "104 /usr/bin/python /tmp/lk-ui",
            f"105 /bin/zsh -lc {env_bin / 'lk-mcp'}",
        ]
    )
    monkeypatch.setattr(updater.os, "getpid", lambda: 101)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )

    processes = updater._managed_processes(env_dir)

    assert processes == [
        updater.ManagedProcess(pid=102, executable="readcast"),
        updater.ManagedProcess(pid=103, executable="kokoro-edge"),
    ]


def test_update_widens_pins_and_updates_both_products(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    pixi = tmp_path / "pixi"
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    updater._update_environment(pixi, "local-knowledge")

    assert commands == [
        [
            str(pixi),
            "global",
            "add",
            "--environment",
            "local-knowledge",
            "--pinning-strategy",
            "no-pin",
            "local-knowledge",
            "readcast",
        ],
        [str(pixi), "global", "update", "local-knowledge"],
    ]


def test_upgrade_stops_managed_processes_and_restores_launchagent(monkeypatch, tmp_path: Path) -> None:
    _, env_dir = _global_layout(tmp_path)
    events: list[object] = []
    processes = [updater.ManagedProcess(10, "readcast"), updater.ManagedProcess(11, "lk-desktop")]
    monkeypatch.setattr(updater, "_global_environment", lambda: (env_dir, "local-knowledge"))
    monkeypatch.setattr(updater, "_find_pixi", lambda _env_dir: tmp_path / "pixi")
    monkeypatch.setattr(updater, "_managed_processes", lambda _env_dir: processes)
    monkeypatch.setattr(updater, "_launchd_is_loaded", lambda _env_dir: True)
    monkeypatch.setattr(updater, "_bootout_launchd", lambda: events.append("bootout"))
    monkeypatch.setattr(updater, "_terminate_processes", lambda found: events.append(("terminate", found)))
    monkeypatch.setattr(updater, "_update_environment", lambda _pixi, env: events.append(("update", env)))
    monkeypatch.setattr(updater, "_bootstrap_launchd", lambda: events.append("bootstrap"))

    result = updater.upgrade_installation()

    assert result == updater.UpgradeResult(environment="local-knowledge", restarted=True)
    assert events == ["bootout", ("terminate", processes), ("update", "local-knowledge"), "bootstrap"]


def test_upgrade_restores_launchagent_after_package_failure(monkeypatch, tmp_path: Path) -> None:
    _, env_dir = _global_layout(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(updater, "_global_environment", lambda: (env_dir, "local-knowledge"))
    monkeypatch.setattr(updater, "_find_pixi", lambda _env_dir: tmp_path / "pixi")
    monkeypatch.setattr(updater, "_managed_processes", lambda _env_dir: [])
    monkeypatch.setattr(updater, "_launchd_is_loaded", lambda _env_dir: True)
    monkeypatch.setattr(updater, "_bootout_launchd", lambda: events.append("bootout"))
    monkeypatch.setattr(updater, "_terminate_processes", lambda _found: events.append("terminate"))

    def fail_update(_pixi, _environment) -> None:
        events.append("update")
        raise updater.UpgradeError("solver failed")

    monkeypatch.setattr(updater, "_update_environment", fail_update)
    monkeypatch.setattr(updater, "_bootstrap_launchd", lambda: events.append("bootstrap"))

    with pytest.raises(updater.UpgradeError, match="solver failed"):
        updater.upgrade_installation()

    assert events == ["bootout", "terminate", "update", "bootstrap"]


def test_manual_desktop_is_relaunched_without_enabling_launchd(monkeypatch, tmp_path: Path) -> None:
    _, env_dir = _global_layout(tmp_path)
    started: list[Path] = []
    monkeypatch.setattr(updater, "_global_environment", lambda: (env_dir, "local-knowledge"))
    monkeypatch.setattr(updater, "_find_pixi", lambda _env_dir: tmp_path / "pixi")
    monkeypatch.setattr(
        updater,
        "_managed_processes",
        lambda _env_dir: [updater.ManagedProcess(11, "lk-desktop")],
    )
    monkeypatch.setattr(updater, "_launchd_is_loaded", lambda _env_dir: False)
    monkeypatch.setattr(updater, "_terminate_processes", lambda _found: None)
    monkeypatch.setattr(updater, "_update_environment", lambda _pixi, _environment: None)
    monkeypatch.setattr(updater, "_start_manual_desktop", lambda found: started.append(found))

    result = updater.upgrade_installation()

    assert result.restarted is True
    assert started == [env_dir]


def test_terminal_upgrade_command_quotes_the_installed_executable(monkeypatch) -> None:
    commands: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        updater.subprocess,
        "Popen",
        lambda command, start_new_session: commands.append((command, start_new_session)),
    )

    updater.open_upgrade_terminal("/Applications/Local Knowledge Tools/lk-desktop")

    command, detached = commands[0]
    assert command[:2] == ["osascript", "-e"]
    assert "'/Applications/Local Knowledge Tools/lk-desktop' upgrade" in command[2]
    assert detached is True


def test_launchagent_is_owned_only_when_its_program_uses_the_same_environment(monkeypatch, tmp_path: Path) -> None:
    env_dir = tmp_path / ".pixi" / "envs" / "local-knowledge"
    expected = env_dir / "bin" / "lk-desktop"

    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=f"program = {expected}\n"),
    )
    assert updater._launchd_is_loaded(env_dir) is True

    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="program = /other/.pixi/envs/local-knowledge/bin/lk-desktop\n",
        ),
    )
    assert updater._launchd_is_loaded(env_dir) is False


def test_terminate_processes_escalates_only_processes_that_do_not_exit(monkeypatch) -> None:
    signals: list[tuple[int, int]] = []
    existence_checks = {20: 0, 21: 0}
    times = iter([0.0, 0.0, 2.0])

    def kill(pid: int, sent_signal: int) -> None:
        signals.append((pid, sent_signal))

    def exists(pid: int) -> bool:
        existence_checks[pid] += 1
        return pid == 21

    monkeypatch.setattr(updater.os, "kill", kill)
    monkeypatch.setattr(updater, "_process_exists", exists)
    monkeypatch.setattr(updater.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)

    updater._terminate_processes(
        [updater.ManagedProcess(20, "lk-ui"), updater.ManagedProcess(21, "lk-desktop")],
        timeout=1,
    )

    assert (20, signal.SIGTERM) in signals
    assert (21, signal.SIGTERM) in signals
    assert (20, signal.SIGKILL) not in signals
    assert (21, signal.SIGKILL) in signals


def test_upgrade_cli_reports_completion(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_app,
        "upgrade_installation",
        lambda: updater.UpgradeResult(environment="local-knowledge", restarted=True),
    )

    result = CliRunner().invoke(desktop_app.cli, ["upgrade"])

    assert result.exit_code == 0
    assert "Upgrade complete" in result.output
    assert "Services restarted" in result.output


def test_upgrade_cli_reports_package_manager_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_app,
        "upgrade_installation",
        lambda: (_ for _ in ()).throw(updater.UpgradeError("network unavailable")),
    )

    result = CliRunner().invoke(desktop_app.cli, ["upgrade"])

    assert result.exit_code == 1
    assert "network unavailable" in result.output
    assert isinstance(result.exception, SystemExit)
