"""Database migrations registry."""

from . import v001_initial, v002_chunk_embeddings, v003_tag_type_and_centroids

ALL_MIGRATIONS = [v001_initial, v002_chunk_embeddings, v003_tag_type_and_centroids]
