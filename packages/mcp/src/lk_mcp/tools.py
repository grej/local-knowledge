"""MCP tool definitions for Local Knowledge."""

from __future__ import annotations

from localknowledge.service import KnowledgeService

from .server import mcp

_svc: KnowledgeService | None = None


def _get_svc() -> KnowledgeService:
    global _svc
    if _svc is None:
        _svc = KnowledgeService()
    return _svc


@mcp.tool()
def list_projects() -> list[dict]:
    """List all projects in the knowledge base with document counts and top topics."""
    svc = _get_svc()
    projects = svc.list_projects()
    for p in projects:
        topics = svc.get_project_topics(p["slug"])
        p["top_topics"] = [t["name"] for t in topics[:5]]
    return projects


@mcp.tool()
def search(
    query: str,
    project: str | None = None,
    topics: list[str] | None = None,
    mode: str = "hybrid",
    limit: int = 20,
) -> list[dict]:
    """Search the knowledge base. Optionally filter by project or topics.

    Args:
        query: Search query text
        project: Optional project slug to filter results
        topics: Optional list of topic names to filter results
        mode: Search mode - "hybrid" (default), "fts", or "semantic"
        limit: Maximum results to return
    """
    svc = _get_svc()
    results = svc.search(query, mode=mode, limit=limit)

    # Filter by project
    if project:
        project_docs = set(d.id for d in svc.get_project_documents(project, limit=10000))
        results = [r for r in results if r.document.id in project_docs]

    # Filter by topics
    if topics:
        allowed = set(svc.tags.search_by_tags(topics, match_all=True))
        results = [r for r in results if r.document.id in allowed]

    return [
        {
            "document_id": r.document.id,
            "title": r.document.title,
            "score": round(r.score, 4),
            "source": r.source,
            "excerpt": (r.document.content or "")[:500],
            "source_type": r.document.source_type,
            "created_at": r.document.created_at,
        }
        for r in results[:limit]
    ]


@mcp.tool()
def find_connections(
    query: str | None = None,
    doc_id: str | None = None,
    exclude_project: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Find semantically related documents, optionally excluding same-project docs.

    Args:
        query: Search by text similarity
        doc_id: Search by document similarity
        exclude_project: Project slug to exclude from results
        limit: Maximum results
    """
    svc = _get_svc()

    if doc_id:
        results = svc.dense.find_similar(doc_id, top_k=limit * 2)
    elif query:
        results = svc.dense.find_similar_by_text(query, top_k=limit * 2)
    else:
        return []

    # Filter out same-project docs
    excluded_ids: set[str] = set()
    if exclude_project:
        excluded_ids = set(d.id for d in svc.get_project_documents(exclude_project, limit=10000))

    output = []
    for did, score in results:
        if did in excluded_ids:
            continue
        doc = svc.docs.get(did)
        if not doc:
            continue
        tags = svc.get_document_tags(did)
        output.append({
            "document_id": did,
            "title": doc.title,
            "score": round(score, 4),
            "tags": [t["name"] for t in tags],
        })
        if len(output) >= limit:
            break

    return output


@mcp.tool()
def get_context(project: str) -> dict:
    """Get full context for a project: documents, topics, and related projects.

    Args:
        project: Project slug
    """
    svc = _get_svc()
    tag = svc.tags.get_by_slug(project)
    if not tag or tag.get("tag_type") != "project":
        return {"error": f"Project '{project}' not found"}

    docs = svc.get_project_documents(project, limit=50)
    topics = svc.get_project_topics(project)

    # Find related projects via centroid similarity
    centroid = svc.centroids.get_centroid(tag["id"])
    related_projects = []
    if centroid:
        import numpy as np
        from localknowledge.embeddings.dense import cosine_similarity, embedding_from_bytes

        centroid_vec = np.array(centroid)
        all_centroids = svc.centroids.get_all_centroids()
        for other_id, other_slug, other_emb in all_centroids:
            if other_id == tag["id"]:
                continue
            sim = cosine_similarity(centroid_vec, np.array(other_emb))
            if sim > 0.3:
                # Find shared topics
                other_topics = svc.get_project_topics(other_slug)
                project_topic_names = {t["name"] for t in topics}
                shared = [t["name"] for t in other_topics if t["name"] in project_topic_names]
                related_projects.append({
                    "name": other_slug,
                    "similarity": round(sim, 4),
                    "shared_topics": shared,
                })
        related_projects.sort(key=lambda r: r["similarity"], reverse=True)

    # Check for summary document
    summary = None
    for doc in docs:
        if doc.source_type == "session_summary":
            summary = doc.content
            break

    return {
        "name": project,
        "description": tag.get("description"),
        "summary": summary,
        "document_count": len(docs),
        "recent_documents": [
            {"id": d.id, "title": d.title, "source_type": d.source_type, "created_at": d.created_at}
            for d in docs[:10]
        ],
        "top_topics": [{"name": t["name"], "doc_count": t["doc_count"]} for t in topics[:10]],
        "related_projects": related_projects[:5],
    }


@mcp.tool()
def ingest(
    text: str,
    title: str | None = None,
    source_type: str = "note",
    source_url: str | None = None,
    source_conversation: str | None = None,
    parent_document_id: str | None = None,
    projects: list[str] | None = None,
    topics: list[str] | None = None,
) -> dict:
    """Ingest text into the knowledge base with optional tagging and provenance.

    Args:
        text: The text content to ingest
        title: Optional title (derived from text if not provided)
        source_type: Type of content - "note", "conversation_extract", "ai_generated", "session_summary"
        source_url: Optional source URL
        source_conversation: Conversation ID for provenance tracking
        parent_document_id: Link to a parent/source document
        projects: Project slugs to tag the document with
        topics: Topic names to tag the document with
    """
    svc = _get_svc()

    doc = svc.add_text(
        text,
        title=title,
        source_type=source_type,
        source_uri=source_url,
        source_conversation=source_conversation,
        parent_document_id=parent_document_id,
    )

    # Apply explicit tags
    applied_projects = []
    applied_topics = []

    if projects:
        for slug in projects:
            tag = svc.tags.get_by_slug(slug)
            if tag and tag.get("tag_type") == "project":
                svc.tags.tag_document(doc.id, tag["id"], source="mcp")
                applied_projects.append(tag["name"])

    if topics:
        for name in topics:
            tag = svc.tags.get_or_create(name)
            svc.tags.tag_document(doc.id, tag["id"], source="mcp")
            applied_topics.append(tag["name"])

    # Get auto-tag suggestions
    suggestions = svc.autotagger.suggest_all(doc.id)

    return {
        "document_id": doc.id,
        "title": doc.title,
        "source_type": doc.source_type,
        "tags": {
            "projects": applied_projects,
            "topics": applied_topics,
        },
        "suggested_projects": [
            {"name": s.tag_name, "score": round(s.score, 4)}
            for s in suggestions if s.tag_type == "project"
        ],
        "suggested_topics": [
            {"name": s.tag_name, "score": round(s.score, 4), "action": s.action}
            for s in suggestions if s.tag_type == "topic"
        ],
    }


@mcp.tool()
def tag(
    doc_id: str,
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> dict:
    """Add or remove tags from a document.

    Args:
        doc_id: Document ID
        add: Tag names to add
        remove: Tag names to remove
    """
    svc = _get_svc()
    doc = svc.docs.get(doc_id)
    if not doc:
        return {"error": f"Document '{doc_id}' not found"}

    if add:
        for name in add:
            tag_obj = svc.tags.get_or_create(name)
            svc.tags.tag_document(doc_id, tag_obj["id"], source="mcp")

    if remove:
        for name in remove:
            from localknowledge.models import slugify
            tag_obj = svc.tags.get_by_slug(slugify(name))
            if tag_obj:
                svc.tags.untag_document(doc_id, tag_obj["id"])

    current = svc.get_document_tags(doc_id)
    return {
        "document_id": doc_id,
        "tags": [{"name": t["name"], "slug": t["slug"], "tag_type": t.get("tag_type", "topic")} for t in current],
    }


@mcp.tool()
def suggest_projects(doc_id: str) -> list[dict]:
    """Get project membership suggestions for a document based on centroid similarity.

    Args:
        doc_id: Document ID to get suggestions for
    """
    svc = _get_svc()
    suggestions = svc.suggest_projects(doc_id)
    return [
        {"name": s.tag_name, "slug": s.tag_slug, "score": round(s.score, 4)}
        for s in suggestions
    ]


@mcp.tool()
def refresh_project_context(project: str) -> dict:
    """Recompute a project's centroid embedding. Call sparingly — this is expensive.

    Args:
        project: Project slug
    """
    svc = _get_svc()
    success = svc.refresh_project_centroid(project)
    if not success:
        return {"error": f"Project '{project}' not found or has no documents"}
    return {"project": project, "status": "refreshed"}
