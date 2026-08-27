"""Safe upgrades for Pixi global Local Knowledge installations."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .launchd import LABEL, PLIST_PATH


MANAGED_EXECUTABLES = {"kokoro-edge", "lk-desktop", "lk-mcp", "lk-ui", "readcast"}


class UpgradeError(RuntimeError):
    """Raised when an installed Local Knowledge environment cannot be upgraded."""


@dataclass(frozen=True, slots=True)
class ManagedProcess:
    pid: int
    executable: str


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    environment: str
    restarted: bool


def upgrade_installation() -> UpgradeResult:
    """Upgrade the containing Pixi global environment and restore its prior launch mode."""
    env_dir, environment = _global_environment()
    pixi = _find_pixi(env_dir)
    processes = _managed_processes(env_dir)
    launchd_was_loaded = _launchd_is_loaded(env_dir)
    desktop_was_running = any(process.executable == "lk-desktop" for process in processes)
    update_error: Exception | None = None
    restart_error: Exception | None = None
    restarted = False

    try:
        if launchd_was_loaded:
            _bootout_launchd()
        _terminate_processes(processes)
        _update_environment(pixi, environment)
    except Exception as exc:
        update_error = exc
    finally:
        try:
            if launchd_was_loaded:
                _bootstrap_launchd()
                restarted = True
            elif desktop_was_running:
                _start_manual_desktop(env_dir)
                restarted = True
        except Exception as exc:
            restart_error = exc

    if update_error is not None:
        message = f"Upgrade failed: {update_error}"
        if restart_error is not None:
            message += f"; restoring the desktop also failed: {restart_error}"
        raise UpgradeError(message) from update_error
    if restart_error is not None:
        raise UpgradeError(f"Upgrade completed, but the desktop could not restart: {restart_error}") from restart_error
    return UpgradeResult(environment=environment, restarted=restarted)


def open_upgrade_terminal(executable: str | None = None) -> None:
    """Open a visible Terminal session running the installed upgrade command."""
    command_path = executable or shutil.which("lk-desktop")
    if not command_path:
        raise UpgradeError("Could not locate lk-desktop on PATH.")
    command = f"{shlex.quote(command_path)} upgrade"
    script = f'tell application "Terminal"\nactivate\ndo script {json.dumps(command)}\nend tell'
    try:
        subprocess.Popen(["osascript", "-e", script], start_new_session=True)
    except OSError as exc:
        raise UpgradeError(f"Could not open Terminal: {exc}") from exc


def _global_environment(executable: Path | None = None) -> tuple[Path, str]:
    env_dir = (executable or Path(sys.executable)).resolve().parent.parent
    pixi_home = env_dir.parent.parent
    manifest = pixi_home / "manifests" / "pixi-global.toml"
    if env_dir.parent.name != "envs" or not manifest.is_file():
        raise UpgradeError("This command only upgrades installations created by 'pixi global install'.")
    try:
        data = tomllib.loads(manifest.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise UpgradeError(f"Could not read the Pixi global manifest: {exc}") from exc
    environment = env_dir.name
    if environment not in data.get("envs", {}):
        raise UpgradeError(f"Pixi global environment {environment!r} is not present in {manifest}.")
    return env_dir, environment


def _find_pixi(env_dir: Path) -> Path:
    bundled = env_dir.parent.parent / "bin" / "pixi"
    candidates = [bundled, Path("~/.pixi/bin/pixi").expanduser()]
    path_match = shutil.which("pixi")
    if path_match:
        candidates.append(Path(path_match))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise UpgradeError("Pixi was not found. Install Pixi before upgrading Local Knowledge.")


def _managed_processes(env_dir: Path) -> list[ManagedProcess]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UpgradeError(f"Could not inspect Local Knowledge processes: {exc}") from exc

    current_pid = os.getpid()
    env_bin = env_dir / "bin"
    processes: list[ManagedProcess] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        if pid == current_pid:
            continue
        executable = _managed_executable(parts[1], env_bin)
        if executable:
            processes.append(ManagedProcess(pid=pid, executable=executable))
    return sorted(processes, key=lambda process: process.executable == "lk-desktop")


def _managed_executable(command: str, env_bin: Path) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    candidates = tokens[:1]
    if Path(tokens[0]).name.startswith("python") and len(tokens) > 1:
        candidates = tokens[1:2]
    for candidate in candidates:
        path = Path(candidate)
        if path.parent == env_bin and path.name in MANAGED_EXECUTABLES:
            return path.name
    return None


def _terminate_processes(processes: list[ManagedProcess], timeout: float = 8.0) -> None:
    ordered_pids = [process.pid for process in processes]
    pending = set(ordered_pids)
    for pid in ordered_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise UpgradeError(f"Permission denied stopping Local Knowledge process {pid}.") from exc

    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        pending = {pid for pid in pending if _process_exists(pid)}
        if pending:
            time.sleep(0.1)
    for pid in pending:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _update_environment(pixi: Path, environment: str) -> None:
    try:
        subprocess.run(
            [
                str(pixi),
                "global",
                "add",
                "--environment",
                environment,
                "--pinning-strategy",
                "no-pin",
                "local-knowledge",
                "readcast",
            ],
            check=True,
        )
        subprocess.run(
            [str(pixi), "global", "update", environment],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UpgradeError(str(exc)) from exc


def _launchd_is_loaded(env_dir: Path) -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        stdout=subprocess.PIPE,
        text=True,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    expected_program = str(env_dir / "bin" / "lk-desktop")
    return result.returncode == 0 and expected_program in result.stdout


def _bootout_launchd() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST_PATH)],
        check=True,
    )


def _bootstrap_launchd() -> None:
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)],
        check=True,
    )


def _start_manual_desktop(env_dir: Path) -> None:
    subprocess.Popen(
        [str(env_dir / "bin" / "lk-desktop")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
