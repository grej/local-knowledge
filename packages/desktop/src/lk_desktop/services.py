"""Service definitions for the Local Knowledge ecosystem."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ServiceDef:
    slug: str
    display_name: str
    start_cmd: list[str]
    health_url: str | None = None
    stop_cmd: list[str] | None = None
    web_url: str | None = None
    depends_on: list[str] = field(default_factory=list)


SERVICES: list[ServiceDef] = [
    ServiceDef(
        slug="kokoro-edge",
        display_name="TTS Engine",
        start_cmd=["kokoro-edge", "serve"],
        health_url="http://127.0.0.1:7777/v1/status",
        stop_cmd=["kokoro-edge", "stop"],
    ),
    ServiceDef(
        slug="readcast",
        display_name="Readcast",
        start_cmd=["readcast", "web", "--no-open"],
        health_url="http://127.0.0.1:8765/api/status",
        web_url="http://127.0.0.1:8765",
        depends_on=["kokoro-edge"],
    ),
    ServiceDef(
        slug="lk-ui",
        display_name="Knowledge Base",
        start_cmd=["lk-ui"],
        health_url="http://127.0.0.1:8321/",
        web_url="http://127.0.0.1:8321",
    ),
    ServiceDef(
        slug="lk-mcp",
        display_name="MCP Server",
        start_cmd=["lk-mcp"],
        health_url="http://127.0.0.1:8322/sse",
    ),
]

SERVICE_MAP: dict[str, ServiceDef] = {s.slug: s for s in SERVICES}
