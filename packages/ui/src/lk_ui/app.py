"""FastAPI application for Local Knowledge UI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from localknowledge.service import KnowledgeService

STATIC_DIR = Path(__file__).parent / "static"


class AddDocumentRequest(BaseModel):
    text: str
    title: Optional[str] = None
    source_type: str = "note"


class TagRequest(BaseModel):
    name: str


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.svc = KnowledgeService()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Local Knowledge", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def svc(request: Request) -> KnowledgeService:
        return request.app.state.svc

    # -- Pages -----------------------------------------------------------------

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    # -- Documents -------------------------------------------------------------

    @app.get("/api/documents")
    async def list_documents(request: Request, type: Optional[str] = None, limit: int = 50):
        docs = svc(request).list_documents(source_type=type, limit=limit)
        return [_doc_dict(d) for d in docs]

    @app.get("/api/documents/{doc_id}")
    async def get_document(request: Request, doc_id: str):
        s = svc(request)
        doc = s.get_document(doc_id)
        if not doc:
            raise HTTPException(404, "Document not found")
        tags = s.get_document_tags(doc_id)
        chunk_count = _chunk_count(s, doc_id)
        return {**_doc_dict(doc), "tags": tags, "chunk_count": chunk_count}

    @app.post("/api/documents")
    async def add_document(request: Request, body: AddDocumentRequest):
        doc = svc(request).add_text(body.text, title=body.title, source_type=body.source_type)
        return _doc_dict(doc)

    @app.delete("/api/documents/{doc_id}")
    async def delete_document(request: Request, doc_id: str):
        if not svc(request).delete_document(doc_id):
            raise HTTPException(404, "Document not found")
        return {"ok": True}

    # -- Search ----------------------------------------------------------------

    @app.get("/api/search")
    async def search_documents(
        request: Request, q: str = "", mode: str = "hybrid", limit: int = 20
    ):
        results = svc(request).search(q, mode=mode, limit=limit)
        return [
            {**_doc_dict(r.document), "score": r.score, "source": r.source}
            for r in results
        ]

    @app.get("/api/search/chunks")
    async def search_chunks(request: Request, q: str = "", limit: int = 20):
        results = svc(request).search_chunks(q, limit=limit)
        return [
            {
                "document_id": r.document_id,
                "chunk_text": r.chunk_text,
                "chunk_index": r.chunk_index,
                "chunk_start": r.chunk_start,
                "chunk_end": r.chunk_end,
                "score": r.score,
            }
            for r in results
        ]

    # -- Tags ------------------------------------------------------------------

    @app.get("/api/tags")
    async def list_tags(request: Request):
        return svc(request).list_tags()

    @app.post("/api/documents/{doc_id}/tags")
    async def tag_document(request: Request, doc_id: str, body: TagRequest):
        s = svc(request)
        if not s.get_document(doc_id):
            raise HTTPException(404, "Document not found")
        tag = s.tag_document(doc_id, body.name)
        return tag

    # -- Projects --------------------------------------------------------------

    @app.get("/api/projects")
    async def list_projects(request: Request):
        return svc(request).list_projects()

    @app.post("/api/projects")
    async def create_project(request: Request, body: CreateProjectRequest):
        return svc(request).create_project(body.name, description=body.description)

    @app.get("/api/projects/{slug}/documents")
    async def project_documents(request: Request, slug: str, limit: int = 50):
        docs = svc(request).get_project_documents(slug, limit=limit)
        return [_doc_dict(d) for d in docs]

    @app.get("/api/projects/{slug}/topics")
    async def project_topics(request: Request, slug: str):
        return svc(request).get_project_topics(slug)

    # -- Auto-tag suggestions --------------------------------------------------

    @app.post("/api/documents/{doc_id}/suggest")
    async def suggest_tags(request: Request, doc_id: str):
        s = svc(request)
        if not s.get_document(doc_id):
            raise HTTPException(404, "Document not found")
        suggestions = s.autotagger.suggest_all(doc_id)
        return [
            {
                "tag_name": sg.tag_name,
                "tag_slug": sg.tag_slug,
                "tag_type": sg.tag_type,
                "score": round(sg.score, 4),
                "action": sg.action,
            }
            for sg in suggestions
        ]

    # -- Embeddings & Stats ----------------------------------------------------

    @app.post("/api/embed")
    async def embed_all(request: Request):
        count = svc(request).embed_all()
        return {"embedded": count}

    @app.get("/api/stats")
    async def stats(request: Request):
        s = svc(request)
        embed_stats = s.embedding_stats()
        config = s.get_config()
        return {**embed_stats, "config": config}

    return app


def _doc_dict(doc) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "source_type": doc.source_type,
        "source_product": doc.source_product,
        "ingest_status": doc.ingest_status,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "content": doc.content,
        "source_uri": doc.source_uri,
        "content_hash": doc.content_hash,
    }


def _chunk_count(svc: KnowledgeService, doc_id: str) -> int | None:
    from contextlib import closing

    from localknowledge.embeddings.dense import TABLE

    with closing(svc.db.connect()) as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE document_id = ?", (doc_id,)
        ).fetchone()
    count = row[0] if row else 0
    return count if count > 0 else None


def _free_port(port: int) -> None:
    """Kill any process listening on *port*."""
    import signal
    import subprocess

    try:
        out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    for pid_str in out.splitlines():
        pid = int(pid_str)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def main():
    import uvicorn

    port = int(os.environ.get("LK_PORT", "8321"))
    _free_port(port)
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
