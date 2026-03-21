"""Embedding system — pluggable backends for document similarity."""

from .base import EmbeddingBackend
from .dense import DenseBackend
from .hybrid import HybridSearch
from .registry import EmbeddingRegistry

__all__ = ["EmbeddingBackend", "DenseBackend", "HybridSearch", "EmbeddingRegistry"]
