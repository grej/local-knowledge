"""Desktop configuration — reads [desktop] from ~/.localknowledge/config.toml."""

from __future__ import annotations

from dataclasses import dataclass

from localknowledge.config import Config


SECTION = "desktop"

DEFAULTS = {
    "start_on_login": False,
    "auto_start_services": True,
    "health_check_interval": 10,
}


@dataclass(slots=True)
class DesktopConfig:
    start_on_login: bool
    auto_start_services: bool
    health_check_interval: int

    @classmethod
    def load(cls, config: Config | None = None) -> DesktopConfig:
        config = config or Config.load()
        data = {**DEFAULTS, **config.product_config(SECTION)}
        return cls(
            start_on_login=bool(data["start_on_login"]),
            auto_start_services=bool(data["auto_start_services"]),
            health_check_interval=int(data["health_check_interval"]),
        )

    def save(self, config: Config | None = None) -> None:
        config = config or Config.load()
        config.set_product_config(SECTION, {
            "start_on_login": self.start_on_login,
            "auto_start_services": self.auto_start_services,
            "health_check_interval": self.health_check_interval,
        })
