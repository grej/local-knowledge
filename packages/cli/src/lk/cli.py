"""lk — Local Knowledge CLI built on Click."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from localknowledge.service import KnowledgeService

from .output import (
    console,
    render_chunk_results,
    render_document_detail,
    render_documents_table,
    render_search_results,
    render_stats,
    render_tags_table,
)


def _service(ctx: click.Context) -> KnowledgeService:
    if "service" not in ctx.obj:
        ctx.obj["service"] = KnowledgeService(base_dir=ctx.obj.get("base_dir"))
    return ctx.obj["service"]


@click.group()
@click.option(
    "--base-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override base directory (default: ~/.localknowledge)",
)
@click.pass_context
def cli(ctx: click.Context, base_dir: Optional[Path]) -> None:
    """lk — Local Knowledge Platform CLI."""
    ctx.ensure_object(dict)
    if base_dir:
        ctx.obj["base_dir"] = base_dir


@cli.command()
@click.option("--text", "-t", type=str, default=None, help="Text content to add")
@click.option("--file", "-f", "file_path", type=click.Path(exists=True, path_type=Path), default=None, help="File to add")
@click.option("--title", type=str, default=None, help="Document title")
@click.option("--type", "source_type", type=str, default="note", help="Document type (default: note)")
@click.pass_context
def add(ctx: click.Context, text: Optional[str], file_path: Optional[Path], title: Optional[str], source_type: str) -> None:
    """Add a document to the knowledge base."""
    svc = _service(ctx)
    if file_path:
        doc = svc.add_file(file_path)
    elif text:
        doc = svc.add_text(text, title=title, source_type=source_type)
    else:
        # Read from stdin
        text = click.get_text_stream("stdin").read()
        if not text.strip():
            raise click.UsageError("Provide --text, --file, or pipe content via stdin.")
        doc = svc.add_text(text, title=title, source_type=source_type)
    console.print(f"[green]Added:[/green] {doc.title} [dim]({doc.id})[/dim]")


@cli.command()
@click.argument("query")
@click.option("--fts", is_flag=True, help="FTS-only search")
@click.option("--semantic", is_flag=True, help="Semantic-only search")
@click.option("--chunks", is_flag=True, help="Show chunk-level results")
@click.option("--tags", "tag_filter", type=str, default=None, help="Filter by tags (comma-separated)")
@click.option("--project", type=str, default=None, help="Filter by project slug")
@click.option("--limit", "-n", type=int, default=20, help="Max results")
@click.pass_context
def search(ctx: click.Context, query: str, fts: bool, semantic: bool, chunks: bool, tag_filter: str | None, project: str | None, limit: int) -> None:
    """Search the knowledge base."""
    svc = _service(ctx)

    # Build allowed doc IDs for project filter
    project_allowed: set[str] | None = None
    if project:
        project_allowed = set(d.id for d in svc.get_project_documents(project, limit=10000))

    if chunks:
        results = svc.search_chunks(query, limit=limit)
        if tag_filter:
            tag_names = [t.strip() for t in tag_filter.split(",")]
            allowed = set(svc.tags.search_by_tags(tag_names, match_all=True))
            results = [r for r in results if r.document_id in allowed]
        if project_allowed is not None:
            results = [r for r in results if r.document_id in project_allowed]
        render_chunk_results(results)
    else:
        mode = "fts" if fts else "semantic" if semantic else "hybrid"
        results = svc.search(query, mode=mode, limit=limit)
        if tag_filter:
            tag_names = [t.strip() for t in tag_filter.split(",")]
            allowed = set(svc.tags.search_by_tags(tag_names, match_all=True))
            results = [r for r in results if r.document.id in allowed]
        if project_allowed is not None:
            results = [r for r in results if r.document.id in project_allowed]
        render_search_results(results)


@cli.command(name="list")
@click.option("--type", "source_type", type=str, default=None, help="Filter by type")
@click.option("--limit", "-n", type=int, default=50, help="Max results")
@click.pass_context
def list_docs(ctx: click.Context, source_type: Optional[str], limit: int) -> None:
    """List documents in the knowledge base."""
    svc = _service(ctx)
    docs = svc.list_documents(source_type=source_type, limit=limit)
    render_documents_table(docs)


@cli.command()
@click.argument("doc_id")
@click.pass_context
def show(ctx: click.Context, doc_id: str) -> None:
    """Show document details."""
    svc = _service(ctx)
    doc = svc.get_document(doc_id)
    if not doc:
        raise click.ClickException(f"Document {doc_id} not found.")
    tags = svc.get_document_tags(doc_id)
    stats = svc.embedding_stats()
    chunk_count = _chunk_count(svc, doc_id)
    render_document_detail(doc, tags, chunk_count=chunk_count)


def _chunk_count(svc: KnowledgeService, doc_id: str) -> int | None:
    """Return chunk count for a document, or None if not embedded."""
    from contextlib import closing

    from localknowledge.embeddings.dense import TABLE

    with closing(svc.db.connect()) as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE document_id = ?", (doc_id,)
        ).fetchone()
    count = row[0] if row else 0
    return count if count > 0 else None


@cli.command()
@click.pass_context
def tags(ctx: click.Context) -> None:
    """List all tags."""
    svc = _service(ctx)
    render_tags_table(svc.list_tags())


@cli.command()
@click.argument("doc_id")
@click.argument("tag_name")
@click.pass_context
def tag(ctx: click.Context, doc_id: str, tag_name: str) -> None:
    """Tag a document."""
    svc = _service(ctx)
    doc = svc.get_document(doc_id)
    if not doc:
        raise click.ClickException(f"Document {doc_id} not found.")
    result = svc.tag_document(doc_id, tag_name)
    console.print(f"[green]Tagged:[/green] {doc.title} with [bold]{result['name']}[/bold]")


@cli.command()
@click.argument("doc_id", required=False)
@click.option("--all", "embed_all", is_flag=True, help="Embed all unembedded documents")
@click.pass_context
def embed(ctx: click.Context, doc_id: Optional[str], embed_all: bool) -> None:
    """Generate embeddings for documents."""
    svc = _service(ctx)
    if embed_all:
        count = svc.embed_all()
        console.print(f"[green]Embedded {count} document(s).[/green]")
    elif doc_id:
        if svc.embed_document(doc_id):
            console.print(f"[green]Embedded document {doc_id[:12]}.[/green]")
        else:
            raise click.ClickException(f"Could not embed {doc_id} (not found or no content).")
    else:
        raise click.UsageError("Provide a DOC_ID or use --all.")


@cli.command()
@click.argument("doc_id")
@click.pass_context
def delete(ctx: click.Context, doc_id: str) -> None:
    """Soft-delete a document."""
    svc = _service(ctx)
    if svc.delete_document(doc_id):
        console.print(f"[yellow]Deleted:[/yellow] {doc_id[:12]}")
    else:
        raise click.ClickException(f"Document {doc_id} not found.")


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show knowledge base statistics."""
    svc = _service(ctx)
    data = svc.embedding_stats()
    data["tags"] = len(svc.list_tags())
    render_stats(data)


@cli.group(invoke_without_command=True)
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show or update configuration."""
    if ctx.invoked_subcommand is None:
        svc = _service(ctx)
        cfg = svc.get_config()
        for section, values in cfg.items():
            if isinstance(values, dict):
                console.print(f"\n[bold]\\[{section}][/bold]")
                for k, v in values.items():
                    console.print(f"  {k} = {v}")
            else:
                console.print(f"{section} = {values}")


@config.command(name="set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set a config value (e.g. embeddings.auto_embed false)."""
    svc = _service(ctx.parent)
    try:
        svc.set_config(key, value)
        console.print(f"[green]Set {key} = {value}[/green]")
    except KeyError:
        raise click.ClickException(f"Unknown config key: {key}")


# -- Project commands ----------------------------------------------------------

@cli.group()
@click.pass_context
def project(ctx: click.Context) -> None:
    """Manage projects."""
    pass


@project.command(name="create")
@click.argument("name")
@click.option("--description", "-d", type=str, default=None, help="Project description")
@click.pass_context
def project_create(ctx: click.Context, name: str, description: Optional[str]) -> None:
    """Create a new project."""
    svc = _service(ctx)
    p = svc.create_project(name, description=description)
    console.print(f"[green]Created project:[/green] {p['name']} [dim]({p['slug']})[/dim]")


@project.command(name="list")
@click.pass_context
def project_list(ctx: click.Context) -> None:
    """List all projects."""
    svc = _service(ctx)
    projects = svc.list_projects()
    if not projects:
        console.print("[dim]No projects found.[/dim]")
        return
    from rich.table import Table

    table = Table(title="Projects")
    table.add_column("Name", style="bold")
    table.add_column("Slug", style="dim")
    table.add_column("Docs", justify="right")
    table.add_column("Description")
    for p in projects:
        table.add_row(
            p["name"],
            p["slug"],
            str(p.get("doc_count", 0)),
            p.get("description") or "",
        )
    console.print(table)


@project.command(name="context")
@click.argument("slug")
@click.pass_context
def project_context(ctx: click.Context, slug: str) -> None:
    """Show project context: documents, topics, and summary."""
    svc = _service(ctx)
    tag = svc.tags.get_by_slug(slug)
    if not tag or tag.get("tag_type") != "project":
        raise click.ClickException(f"Project '{slug}' not found.")

    docs = svc.get_project_documents(slug, limit=20)
    topics = svc.get_project_topics(slug)

    console.print(f"\n[bold]{tag['name']}[/bold] [dim]({slug})[/dim]")
    if tag.get("description"):
        console.print(f"  {tag['description']}")
    console.print(f"  Documents: {len(docs)}")

    if topics:
        topic_str = ", ".join(t["name"] for t in topics[:10])
        console.print(f"  Topics: {topic_str}")

    if docs:
        console.print()
        render_documents_table(docs)


@project.command(name="refresh")
@click.argument("slug")
@click.pass_context
def project_refresh(ctx: click.Context, slug: str) -> None:
    """Refresh project centroid embedding."""
    svc = _service(ctx)
    if svc.refresh_project_centroid(slug):
        console.print(f"[green]Refreshed centroid for project:[/green] {slug}")
    else:
        raise click.ClickException(f"Project '{slug}' not found or has no documents.")


# -- Auto-tag commands ---------------------------------------------------------

@cli.command(name="auto-tag")
@click.argument("doc_id")
@click.pass_context
def auto_tag(ctx: click.Context, doc_id: str) -> None:
    """Auto-tag a document (applies high-confidence topic tags)."""
    svc = _service(ctx)
    doc = svc.get_document(doc_id)
    if not doc:
        raise click.ClickException(f"Document {doc_id} not found.")

    suggestions = svc.auto_tag(doc_id)
    if not suggestions:
        console.print("[dim]No tag suggestions.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Tag Suggestions for {doc.title}")
    table.add_column("Tag", style="bold")
    table.add_column("Type")
    table.add_column("Score", justify="right", style="cyan")
    table.add_column("Action")
    for s in suggestions:
        action_style = "[green]auto[/green]" if s.action == "auto" else "[dim]suggest[/dim]"
        table.add_row(s.tag_name, s.tag_type, f"{s.score:.4f}", action_style)
    console.print(table)


@cli.command()
@click.argument("doc_id")
@click.pass_context
def suggest(ctx: click.Context, doc_id: str) -> None:
    """Show tag suggestions for a document (without applying)."""
    svc = _service(ctx)
    doc = svc.get_document(doc_id)
    if not doc:
        raise click.ClickException(f"Document {doc_id} not found.")

    suggestions = svc.autotagger.suggest_all(doc_id)
    if not suggestions:
        console.print("[dim]No suggestions.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Suggestions for {doc.title}")
    table.add_column("Tag", style="bold")
    table.add_column("Type")
    table.add_column("Score", justify="right", style="cyan")
    for s in suggestions:
        table.add_row(s.tag_name, s.tag_type, f"{s.score:.4f}")
    console.print(table)
