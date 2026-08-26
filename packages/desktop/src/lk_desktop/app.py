"""macOS menu bar app and CLI entry point."""

from __future__ import annotations

import sqlite3
import sys
import threading
import subprocess as _sp
import webbrowser
from contextlib import closing

import click
import rumps

from localknowledge.config import Config
from localknowledge.db import Database

from .config import DesktopConfig
from .launchd import install as launchd_install, uninstall as launchd_uninstall, is_installed
from .services import SERVICES
from .supervisor import ProcessSupervisor

STATUS_ICONS = {
    "running": "\u25cf",     # ● green (described in menu)
    "starting": "\u25d4",    # ◔ half circle
    "stopped": "\u25cb",     # ○ open circle
    "not_found": "\u25cb",   # ○ open circle
    "error": "\u25cf",       # ● (red, described in menu)
}

STATUS_LABELS = {
    "running": "Running",
    "starting": "Starting\u2026",
    "stopped": "Stopped",
    "not_found": "Not installed",
    "error": "Error",
}


class LKDesktopApp(rumps.App):
    def __init__(self):
        super().__init__("LK", quit_button=None)
        self.lk_config = Config.load()
        self.desktop_config = DesktopConfig.load(self.lk_config)
        self.supervisor = ProcessSupervisor(self.lk_config.base_dir)
        self._doc_count: int | None = None
        self._project_count: int | None = None
        self._stats_tick = 0
        self._auto_start_pending = self.desktop_config.auto_start_services
        self._download_notice_shown = False
        self._service_start_pending = False

    @rumps.timer(0.5)
    def startup_tick(self, timer):
        timer.stop()
        if self._auto_start_pending:
            self._auto_start_pending = False
            self._start_all(None)

    @rumps.timer(1)
    def menu_tick(self, _):
        self._refresh_menu()

    @rumps.timer(10)
    def health_tick(self, _):
        self.supervisor.check_health()
        self._stats_tick += 1
        if self._doc_count is None or self._stats_tick % 6 == 0:
            self._refresh_stats()
        self._refresh_menu()

    def _refresh_stats(self) -> None:
        try:
            db = Database(self.lk_config.base_dir)
            with closing(db.connect()) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"
                ).fetchone()
                self._doc_count = row[0] if row else 0
                row = conn.execute(
                    "SELECT COUNT(DISTINCT project) FROM documents "
                    "WHERE deleted_at IS NULL AND project IS NOT NULL"
                ).fetchone()
                self._project_count = row[0] if row else 0
        except (sqlite3.Error, Exception):
            self._doc_count = None
            self._project_count = None

    def _refresh_menu(self) -> None:
        items: list[rumps.MenuItem | None] = []

        # Service items
        for svc in SERVICES:
            state = self.supervisor.states[svc.slug]
            icon = STATUS_ICONS.get(state.status, "\u25cb")
            label = STATUS_LABELS.get(state.status, state.status)
            if state.detail and state.status == "starting":
                label = _short_status(state.detail)
            elif state.detail and state.status == "error":
                label = f"Error: {_short_status(state.detail)}"

            if svc.web_url and state.status == "running":
                title = f"{icon} {svc.display_name}"
                item = rumps.MenuItem(title, callback=lambda _, url=svc.web_url: _open_ui(url))
            else:
                title = f"{icon} {svc.display_name}    {label}"
                item = rumps.MenuItem(title)
            items.append(item)

        items.append(None)  # separator

        # Stats
        if self._doc_count is not None:
            parts = [f"{self._doc_count} documents"]
            if self._project_count:
                parts.append(f"{self._project_count} projects")
            items.append(rumps.MenuItem("\u2022 " + " \u00b7 ".join(parts)))
            items.append(None)

        # Actions
        items.append(rumps.MenuItem("Start All Services", callback=self._start_all))
        items.append(rumps.MenuItem("Stop All Services", callback=self._stop_all))
        items.append(None)

        items.append(rumps.MenuItem("View Logs\u2026", callback=self._open_logs))

        login_item = rumps.MenuItem("Start on Login", callback=self._toggle_login)
        login_item.state = is_installed()
        items.append(login_item)

        items.append(None)
        items.append(rumps.MenuItem("Quit Local Knowledge", callback=self._quit))

        self.menu.clear()
        for item in items:
            if item is None:
                self.menu.add(rumps.separator)
            else:
                self.menu.add(item)

    def _start_all(self, _) -> None:
        if self._service_start_pending:
            return
        if not self._confirm_model_download():
            return
        self._service_start_pending = True
        threading.Thread(target=self._run_start_all, daemon=True).start()

    def _run_start_all(self) -> None:
        try:
            self.supervisor.start_all()
        finally:
            self._service_start_pending = False

    def _confirm_model_download(self) -> bool:
        try:
            status = self.supervisor.tts_model_status()
        except Exception:
            # The background start path reports binary and model inspection errors in the service row.
            return True
        if status.is_available:
            return True

        size = f"{status.total_bytes / 1_000_000:.1f} MB" if status.total_bytes > 0 else "about 330 MB"
        resume = (
            f" Existing verified assets are {status.percent}% complete and will be reused."
            if status.downloaded_bytes
            else ""
        )
        result = rumps.alert(
            title="TTS Model Download Required",
            message=(
                f"Local Knowledge needs to download {status.name} ({size}) before the TTS Engine can start."
                f"{resume}\n\nDownload progress will appear next to TTS Engine in this menu. "
                "The model is verified by file size and SHA-256 before Readcast starts."
            ),
            ok="Download",
            cancel="Not Now",
        )
        if result != 1:
            state = self.supervisor.states["kokoro-edge"]
            state.detail = "Model download postponed"
            return False
        self._download_notice_shown = True
        return True

    def _stop_all(self, _) -> None:
        threading.Thread(target=self.supervisor.stop_all, daemon=True).start()

    def _open_logs(self, _) -> None:
        _sp.run(["open", str(self.supervisor.logs_dir)])

    def _toggle_login(self, sender) -> None:
        if is_installed():
            launchd_uninstall()
        else:
            launchd_install()
        sender.state = is_installed()

    def _quit(self, _) -> None:
        self.supervisor.stop_all()
        rumps.quit_application()


# ── CLI ─────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Local Knowledge desktop manager."""
    if ctx.invoked_subcommand is None:
        _run_app()


@cli.command()
def install():
    """Enable start-on-login via launchd."""
    launchd_install()
    click.echo("Installed launchd plist. lk-desktop will start on login.")


@cli.command()
def uninstall():
    """Disable start-on-login."""
    launchd_uninstall()
    click.echo("Removed launchd plist.")


@cli.command()
def status():
    """Print service status (no GUI)."""
    config = Config.load()
    supervisor = ProcessSupervisor(config.base_dir)
    supervisor.check_health()

    for svc in SERVICES:
        state = supervisor.states[svc.slug]
        icon = STATUS_ICONS.get(state.status, "\u25cb")
        label = STATUS_LABELS.get(state.status, state.status)
        click.echo(f"  {icon} {svc.display_name:20s} {label}")


_LK_APP_BUNDLE = "com.localknowledge.app"


def _open_ui(url: str) -> None:
    """Open the Tauri native app if installed, otherwise fall back to browser."""
    try:
        result = _sp.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{_LK_APP_BUNDLE}'"],
            capture_output=True, text=True, timeout=3,
        )
        app_path = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    except (OSError, IndexError):
        app_path = None

    if app_path:
        _sp.Popen(["open", "-a", app_path])
    else:
        webbrowser.open(url)


def _short_status(message: str, limit: int = 80) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "\u2026"


def _run_app() -> None:
    app = LKDesktopApp()
    app.run()


def main():
    if len(sys.argv) > 1:
        cli()
    else:
        _run_app()
