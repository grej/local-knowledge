"""Unified configuration system — TOML at ~/.localknowledge/config.toml."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
from pathlib import Path
from typing import Any
import tomllib

from .llm import LLMConfig
from .tts import TTSConfig


@dataclass(slots=True)
class DatabaseConfig:
    path: str = "store.db"
    busy_timeout: int = 5000


@dataclass(slots=True)
class EmbeddingsConfig:
    model: str = "BAAI/bge-small-en-v1.5"
    dimensions: int = 384  # informational — actual dims are determined by the model
    auto_embed: bool = True
    auto_tag: bool = True


@dataclass(slots=True)
class Config:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    base_dir: Path = field(default_factory=lambda: Path("~/.localknowledge").expanduser())
    _product_configs: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def config_path(self) -> Path:
        return self.base_dir / "config.toml"

    @classmethod
    def load(cls, base_dir: Path | None = None) -> Config:
        base = (base_dir or Path("~/.localknowledge")).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        config = cls(base_dir=base)
        if not config.config_path.exists():
            config.save()
            return config

        with config.config_path.open("rb") as f:
            data = tomllib.load(f)

        config.database = _merge_dataclass(DatabaseConfig, config.database, data.get("database", {}))
        config.tts = _merge_dataclass(TTSConfig, config.tts, data.get("tts", {}))
        config.llm = _merge_dataclass(LLMConfig, config.llm, data.get("llm", {}))
        config.embeddings = _merge_dataclass(EmbeddingsConfig, config.embeddings, data.get("embeddings", {}))

        # Load product-specific sections
        known_sections = {"database", "tts", "llm", "embeddings"}
        for key, value in data.items():
            if key not in known_sections and isinstance(value, dict):
                config._product_configs[key] = value

        return config

    def save(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        content = self._to_toml()
        self.config_path.write_text(content, encoding="utf-8")

    def set_value(self, dotted_key: str, value: str) -> None:
        section_name, _, field_name = dotted_key.partition(".")
        if not section_name or not field_name:
            raise KeyError("Config keys must use section.key format")

        section = getattr(self, section_name, None)
        if section is None or not hasattr(section, field_name):
            raise KeyError(dotted_key)

        current = getattr(section, field_name)
        setattr(section, field_name, _coerce_value(current, value))
        self.save()

    def product_config(self, name: str) -> dict[str, Any]:
        return self._product_configs.get(name, {})

    def set_product_config(self, name: str, data: dict[str, Any]) -> None:
        self._product_configs[name] = data
        self.save()

    def _to_toml(self) -> str:
        lines: list[str] = []

        lines.append("[database]")
        lines.append(f'path = {json.dumps(self.database.path)}')
        lines.append(f"busy_timeout = {self.database.busy_timeout}")
        lines.append("")

        lines.append("[tts]")
        lines.append(f'server_url = {json.dumps(self.tts.server_url)}')
        lines.append(f'model = {json.dumps(self.tts.model)}')
        lines.append(f'voice = {json.dumps(self.tts.voice)}')
        lines.append(f"speed = {self.tts.speed}")
        lines.append(f'language = {json.dumps(self.tts.language)}')
        lines.append(f'binary = {json.dumps(self.tts.binary)}')
        lines.append(f"auto_start = {str(self.tts.auto_start).lower()}")
        lines.append(f"startup_timeout_sec = {self.tts.startup_timeout_sec}")
        lines.append("")

        lines.append("[llm]")
        lines.append(f'provider = {json.dumps(self.llm.provider)}')
        lines.append(f'local_model = {json.dumps(self.llm.local_model)}')
        lines.append(f'local_server_url = {json.dumps(self.llm.local_server_url)}')
        lines.append(f'api_key = {json.dumps(self.llm.api_key)}')
        lines.append(f"auto_start = {str(self.llm.auto_start).lower()}")
        lines.append(f"startup_timeout_sec = {self.llm.startup_timeout_sec}")
        lines.append("")

        lines.append("[embeddings]")
        lines.append(f'model = {json.dumps(self.embeddings.model)}')
        lines.append(f"dimensions = {self.embeddings.dimensions}")
        lines.append(f"auto_embed = {str(self.embeddings.auto_embed).lower()}")
        lines.append(f"auto_tag = {str(self.embeddings.auto_tag).lower()}")
        lines.append("")

        for name, data in sorted(self._product_configs.items()):
            lines.append(f"[{name}]")
            for key, value in sorted(data.items()):
                if isinstance(value, dict):
                    lines.append(f"[{name}.{key}]")
                    for k, v in sorted(value.items()):
                        lines.append(f"{json.dumps(k)} = {json.dumps(v)}")
                elif isinstance(value, bool):
                    lines.append(f"{key} = {str(value).lower()}")
                elif isinstance(value, (int, float)):
                    lines.append(f"{key} = {value}")
                else:
                    lines.append(f'{key} = {json.dumps(str(value))}')
            lines.append("")

        return "\n".join(lines)


def _merge_dataclass(cls, current, data: dict) -> Any:
    allowed = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in allowed}
    return cls(**{**asdict(current), **filtered})


def _coerce_value(current: object, raw: str) -> object:
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    return raw
