"""Install / uninstall macOS launchd plist for start-on-login."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

from localknowledge.config import Config

from .config import DesktopConfig

LABEL = "com.localknowledge.desktop"
PLIST_PATH = Path("~/Library/LaunchAgents").expanduser() / f"{LABEL}.plist"


def _build_path() -> str:
    """Build a PATH that includes the directory containing lk-desktop."""
    lk_bin = shutil.which("lk-desktop")
    extra_dirs: list[str] = []
    if lk_bin:
        extra_dirs.append(str(Path(lk_bin).parent))
    pixi_bin = Path("~/.pixi/bin").expanduser()
    if pixi_bin.is_dir() and str(pixi_bin) not in extra_dirs:
        extra_dirs.append(str(pixi_bin))
    base = "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"
    prefix = ":".join(extra_dirs)
    return f"{prefix}:{base}" if prefix else base


def _build_plist() -> bytes:
    lk_bin = shutil.which("lk-desktop")
    program = lk_bin or "lk-desktop"
    plist = {
        "Label": LABEL,
        "ProgramArguments": [program],
        "EnvironmentVariables": {"PATH": _build_path()},
        "KeepAlive": True,
        "RunAtLoad": True,
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


def install() -> None:
    """Write the plist and load it via launchctl."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(_build_plist())
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=False)
    cfg = Config.load()
    desktop = DesktopConfig.load(cfg)
    desktop.start_on_login = True
    desktop.save(cfg)


def uninstall() -> None:
    """Unload and remove the plist."""
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.unlink(missing_ok=True)
    cfg = Config.load()
    desktop = DesktopConfig.load(cfg)
    desktop.start_on_login = False
    desktop.save(cfg)


def is_installed() -> bool:
    return PLIST_PATH.exists()
