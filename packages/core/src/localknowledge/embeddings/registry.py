"""Embedding registry — loads and manages backends."""

from __future__ import annotations

from typing import Optional

from ..db import Database
from .base import EmbeddingBackend
from .dense import DenseBackend


class EmbeddingRegistry:
    """Registry that loads and manages embedding backends."""

    def __init__(self, db: Database):
        self.db = db
        self._backends: dict[str, EmbeddingBackend] = {}

    def register(self, backend: EmbeddingBackend) -> None:
        self._backends[backend.name] = backend

    def get(self, name: str) -> Optional[EmbeddingBackend]:
        return self._backends.get(name)

    def get_or_create_dense(
        self, model_name: str | None = None, embed_fn=None
    ) -> DenseBackend:
        if "dense" not in self._backends:
            kwargs = {}
            if model_name:
                kwargs["model_name"] = model_name
            if embed_fn:
                kwargs["embed_fn"] = embed_fn
            backend = DenseBackend(self.db, **kwargs)
            self._backends["dense"] = backend
        return self._backends["dense"]

    def list_backends(self) -> list[str]:
        return list(self._backends.keys())
