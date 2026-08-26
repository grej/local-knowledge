"""Process supervisor — starts, stops, and health-checks managed services."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx
from localknowledge.config import Config
from localknowledge.tts import TTSClient, TTSRuntime

from .services import SERVICES, SERVICE_MAP, ServiceDef

log = logging.getLogger(__name__)

BACKOFF_DELAYS = [5, 10, 30, 60, 120]
MAX_RESTARTS = len(BACKOFF_DELAYS)
HEALTHY_RESET_SECS = 300  # reset restart counter after 5 min healthy
LOG_MAX_BYTES = 1_000_000


@dataclass
class ServiceState:
    status: str = "stopped"  # stopped | starting | running | error | not_found
    process: subprocess.Popen | None = None
    restart_count: int = 0
    last_restart: float | None = None
    healthy_since: float | None = None


class ProcessSupervisor:
    def __init__(
        self,
        base_dir: Path | None = None,
        *,
        config: Config | None = None,
        tts_runtime: object | None = None,
        tts_client: object | None = None,
    ):
        self.config = config or Config.load(base_dir)
        self.base_dir = base_dir or self.config.base_dir
        self.tts_config = self.config.tts
        self.tts_runtime = tts_runtime or TTSRuntime(self.tts_config)
        self.tts_client = tts_client or TTSClient(self.tts_config)
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.states: dict[str, ServiceState] = {s.slug: ServiceState() for s in SERVICES}

    # ── Start / stop ────────────────────────────────────────────────

    def start_all(self) -> None:
        for svc in self._topo_order():
            if any(not self._wait_healthy(dep, timeout=30) for dep in svc.depends_on):
                log.error("%s: dependency failed to become healthy", svc.slug)
                self.states[svc.slug].status = "error"
                continue
            self._start_one(svc)

    def stop_all(self) -> None:
        for svc in reversed(self._topo_order()):
            self._stop_one(svc)

    def _start_one(self, svc: ServiceDef) -> None:
        state = self.states[svc.slug]
        if state.status in ("running", "starting"):
            return
        if svc.slug == "kokoro-edge":
            state.status = "starting"
            state.last_restart = time.monotonic()
            try:
                self.tts_runtime.ensure_running()
            except Exception:
                log.exception("%s: failed to start through shared TTS runtime", svc.slug)
                state.status = "error"
                return
            state.process = None
            state.status = "running"
            state.healthy_since = time.monotonic()
            return
        assert svc.start_cmd is not None
        if not shutil.which(svc.start_cmd[0]):
            log.warning("%s: binary %r not found", svc.slug, svc.start_cmd[0])
            state.status = "not_found"
            return

        self._truncate_log(svc.slug)
        log_file = self.logs_dir / f"{svc.slug}.log"
        fh = log_file.open("a")
        try:
            proc = subprocess.Popen(
                svc.start_cmd,
                stdout=fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError:
            log.exception("%s: failed to start", svc.slug)
            fh.close()
            state.status = "error"
            return
        state.process = proc
        state.status = "starting"
        state.last_restart = time.monotonic()
        log.info("%s: started (pid %d)", svc.slug, proc.pid)

    def _stop_one(self, svc: ServiceDef) -> None:
        state = self.states[svc.slug]
        if state.status in ("stopped", "not_found"):
            return

        if svc.slug == "kokoro-edge":
            try:
                self.tts_runtime.stop()
            except Exception:
                log.exception("%s: failed to stop through shared TTS runtime", svc.slug)
                state.status = "error"
                return
        elif svc.stop_cmd and shutil.which(svc.stop_cmd[0]):
            with suppress(subprocess.SubprocessError):
                subprocess.run(svc.stop_cmd, timeout=5)
        elif state.process:
            state.process.terminate()
            try:
                state.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                state.process.kill()
                state.process.wait(timeout=2)

        state.process = None
        state.status = "stopped"
        state.healthy_since = None
        log.info("%s: stopped", svc.slug)

    # ── Health checks ───────────────────────────────────────────────

    def check_health(self) -> None:
        for svc in SERVICES:
            state = self.states[svc.slug]
            if state.status in ("stopped", "not_found"):
                continue
            alive = self._probe(svc)
            if alive:
                if state.status != "running":
                    log.info("%s: now healthy", svc.slug)
                state.status = "running"
                if state.healthy_since is None:
                    state.healthy_since = time.monotonic()
                elif time.monotonic() - state.healthy_since > HEALTHY_RESET_SECS:
                    state.restart_count = 0
            elif state.status in ("running", "starting", "error"):
                self._handle_failure(svc, state)

    def _probe(self, svc: ServiceDef) -> bool:
        if svc.slug == "kokoro-edge":
            try:
                self.tts_client.server_status()
                return True
            except Exception:
                return False
        if not svc.health_url:
            # No health URL — check process is alive
            return self.states[svc.slug].process is not None and self.states[svc.slug].process.poll() is None
        try:
            # SSE health endpoints never finish their response body. Probe headers only.
            with httpx.stream("GET", svc.health_url, timeout=2) as response:
                return response.status_code < 500
        except (httpx.HTTPError, OSError):
            return False

    def _handle_failure(self, svc: ServiceDef, state: ServiceState) -> None:
        log.warning("%s: health check failed (restarts: %d)", svc.slug, state.restart_count)
        state.healthy_since = None
        if state.restart_count >= MAX_RESTARTS:
            state.status = "error"
            return
        delay = BACKOFF_DELAYS[min(state.restart_count, len(BACKOFF_DELAYS) - 1)]
        if state.last_restart and time.monotonic() - state.last_restart < delay:
            return  # too soon to retry
        state.restart_count += 1
        self._stop_one(svc)
        self._start_one(svc)

    # ── Helpers ─────────────────────────────────────────────────────

    def _wait_healthy(self, slug: str, timeout: float = 30) -> bool:
        svc = SERVICE_MAP[slug]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._probe(svc):
                self.states[slug].status = "running"
                return True
            time.sleep(1)
        log.warning("%s: timed out waiting for health", slug)
        return False

    def _topo_order(self) -> list[ServiceDef]:
        no_deps = [s for s in SERVICES if not s.depends_on]
        with_deps = [s for s in SERVICES if s.depends_on]
        return no_deps + with_deps

    def _truncate_log(self, slug: str) -> None:
        log_file = self.logs_dir / f"{slug}.log"
        if log_file.exists() and log_file.stat().st_size > LOG_MAX_BYTES:
            log_file.write_text("")
