"""
Vector store abstraction backed by Qdrant.

Handles collection creation, upserting BioPart embeddings, and semantic search.

Storage modes (in order of preference):
  1. Remote Qdrant server at QDRANT_URL
  2. Local on-disk Qdrant (data/qdrant_store/) — persists between restarts
  3. Pure in-memory fallback (data lost on exit)
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Sequence

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import get_settings
from embeddings.embed_parts import embed_part, embed_parts, embed_text
from models.part import BioPart

logger = logging.getLogger(__name__)

LOCAL_QDRANT_PATH = Path(__file__).resolve().parent.parent / "data" / "qdrant_store"


class VectorStore:
    def __init__(self, in_memory: bool = False):
        cfg = get_settings()
        self.collection = cfg.qdrant_collection
        self.dim = cfg.embedding_dim

        if in_memory:
            self.client = QdrantClient(":memory:")
        else:
            try:
                client = QdrantClient(url=cfg.qdrant_url, timeout=5)
                client.get_collections()
                self.client = client
                logger.info("Connected to remote Qdrant at %s", cfg.qdrant_url)
            except Exception:
                try:
                    LOCAL_QDRANT_PATH.mkdir(parents=True, exist_ok=True)
                    self.client = QdrantClient(path=str(LOCAL_QDRANT_PATH))
                    logger.info("Using local on-disk Qdrant at %s", LOCAL_QDRANT_PATH)
                except Exception:
                    logger.warning("Falling back to in-memory Qdrant (data will not persist)")
                    self.client = QdrantClient(":memory:")

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            self.client.get_collection(self.collection)
            logger.info("Collection '%s' already exists", self.collection)
        except (UnexpectedResponse, Exception):
            logger.info("Creating collection '%s'", self.collection)
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )

    def upsert_part(self, part: BioPart) -> None:
        vec = embed_part(part)
        point = PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, part.part_id)),
            vector=vec,
            payload=part.model_dump(),
        )
        self.client.upsert(collection_name=self.collection, points=[point])

    def upsert_parts(self, parts: Sequence[BioPart], batch_size: int = 64) -> int:
        parts_list = list(parts)
        total = 0
        for i in range(0, len(parts_list), batch_size):
            batch = parts_list[i : i + batch_size]
            vecs = embed_parts(batch, batch_size=batch_size)
            points = [
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, p.part_id)),
                    vector=v,
                    payload=p.model_dump(),
                )
                for p, v in zip(batch, vecs)
            ]
            self.client.upsert(collection_name=self.collection, points=points)
            total += len(points)
            logger.info("Upserted %d / %d parts", total, len(parts_list))
        return total

    def search(
        self,
        query: str,
        limit: int = 10,
        part_type: str | None = None,
        score_threshold: float = 0.0,
    ) -> list[dict]:
        query_filter = None
        if part_type:
            query_filter = Filter(
                must=[FieldCondition(key="type", match=MatchValue(value=part_type))]
            )

        # Exact-ID fast path. Part IDs (BBa_*, P*****, cello-*, igem-dist-*)
        # are short literal strings that don't embed well, so if the query
        # looks like any of our accession formats we look it up directly and
        # prepend the result to the vector-search output. Gives the LLM
        # reliable hits for canonical IDs without relying on similarity.
        import re
        q = (query or "").strip()
        id_like = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]{1,40}", q))
        exact_hits: list[dict] = []
        if id_like:
            try:
                pts, _ = self.client.scroll(
                    collection_name=self.collection,
                    scroll_filter=Filter(must=[FieldCondition(key="part_id", match=MatchValue(value=q))]),
                    limit=1, with_payload=True,
                )
                if pts and (part_type is None or pts[0].payload.get("type") == part_type):
                    exact_hits.append({**pts[0].payload, "score": 1.0})
            except Exception:
                pass

        vec = embed_text(query)
        results = self.client.query_points(
            collection_name=self.collection,
            query=vec,
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
        )
        vector_hits = [{**hit.payload, "score": hit.score} for hit in results.points]

        # Dedupe — exact hit wins if it appears in the vector results too.
        seen = {h["part_id"] for h in exact_hits}
        merged = exact_hits + [h for h in vector_hits if h.get("part_id") not in seen]
        return merged[:limit]

    def search_by_type(self, query: str, part_type: str, limit: int = 5) -> list[dict]:
        return self.search(query, limit=limit, part_type=part_type)

    def count(self) -> int:
        info = self.client.get_collection(self.collection)
        return info.points_count


_store: VectorStore | None = None


def get_vector_store(in_memory: bool = False) -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore(in_memory=in_memory)
    return _store
