"""Rich formatting helpers for CLI output."""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from localknowledge.models import ChunkResult, Document, SearchResult

console = Console()


def render_search_results(results: list[SearchResult]) -> None:
    if not results:
        console.print("[dim]No results found.[/dim]")
        return
    table = Table(title="Search Results", show_lines=True)
    table.add_column("Score", style="cyan", width=8, justify="right")
    table.add_column("Title", style="bold")
    table.add_column("Type", width=10)
    table.add_column("ID", style="dim", width=12)
    table.add_column("Created", style="dim", width=20)
    for r in results:
        table.add_row(
            f"{r.score:.4f}",
            r.document.title,
            r.document.source_type,
            r.document.id[:12],
            r.document.created_at[:19],
        )
    console.print(table)


def render_documents_table(docs: list[Document]) -> None:
    if not docs:
        console.print("[dim]No documents found.[/dim]")
        return
    table = Table(title="Documents", show_lines=True)
    table.add_column("Title", style="bold")
    table.add_column("Type", width=10)
    table.add_column("Status", width=10)
    table.add_column("Created", style="dim", width=20)
    table.add_column("ID", style="dim", width=12)
    for doc in docs:
        table.add_row(
            doc.title,
            doc.source_type,
            doc.ingest_status,
            doc.created_at[:19],
            doc.id[:12],
        )
    console.print(table)


def render_document_detail(
    doc: Document,
    tags: list[dict],
    chunk_count: Optional[int] = None,
) -> None:
    lines = [
        f"[bold]Title:[/bold] {doc.title}",
        f"[bold]ID:[/bold] {doc.id}",
        f"[bold]Type:[/bold] {doc.source_type}",
        f"[bold]Product:[/bold] {doc.source_product}",
        f"[bold]Status:[/bold] {doc.ingest_status}",
        f"[bold]Created:[/bold] {doc.created_at}",
        f"[bold]Updated:[/bold] {doc.updated_at}",
    ]
    if doc.source_uri:
        lines.append(f"[bold]Source:[/bold] {doc.source_uri}")
    if doc.content_hash:
        lines.append(f"[bold]Hash:[/bold] {doc.content_hash[:16]}...")
    if tags:
        tag_str = ", ".join(t["name"] for t in tags)
        lines.append(f"[bold]Tags:[/bold] {tag_str}")
    if chunk_count is not None:
        lines.append(f"[bold]Chunks:[/bold] {chunk_count}")
    if doc.content:
        preview = doc.content[:500]
        if len(doc.content) > 500:
            preview += "..."
        lines.append(f"\n[bold]Content:[/bold]\n{preview}")
    console.print(Panel("\n".join(lines), title=doc.title, expand=False))


def render_tags_table(tags: list[dict]) -> None:
    if not tags:
        console.print("[dim]No tags found.[/dim]")
        return
    table = Table(title="Tags")
    table.add_column("Name", style="bold")
    table.add_column("Slug", style="dim")
    table.add_column("Parent", style="dim")
    table.add_column("ID", style="dim", width=12)
    for tag in tags:
        table.add_row(
            tag["name"],
            tag["slug"],
            tag.get("parent_id", "")[:12] if tag.get("parent_id") else "",
            tag["id"][:12],
        )
    console.print(table)


def render_chunk_results(results: list[ChunkResult]) -> None:
    if not results:
        console.print("[dim]No chunk results found.[/dim]")
        return
    table = Table(title="Chunk Results", show_lines=True)
    table.add_column("Score", style="cyan", width=8, justify="right")
    table.add_column("Doc ID", style="dim", width=12)
    table.add_column("Chunk", width=6, justify="right")
    table.add_column("Excerpt", style="bold", max_width=80)
    for r in results:
        excerpt = r.chunk_text[:120]
        if len(r.chunk_text) > 120:
            excerpt += "..."
        table.add_row(
            f"{r.score:.4f}",
            r.document_id[:12],
            str(r.chunk_index),
            excerpt,
        )
    console.print(table)


def render_stats(stats: dict) -> None:
    table = Table(title="Knowledge Base Stats")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    for key, value in stats.items():
        table.add_row(key.replace("_", " ").title(), str(value))
    console.print(table)
