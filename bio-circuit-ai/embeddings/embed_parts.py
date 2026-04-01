"""
Embedding generation pipeline for biological parts.

Generates dense vector embeddings from the textual description and functional
annotation of each BioPart.  Uses sentence-transformers locally so no external
API call is required for embedding (the LLM API is only used during
orchestration).
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np
from sentence_transformers import SentenceTransformer

from config import get_settings
from models.part import BioPart

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        cfg = get_settings()
        logger.info("Loading embedding model: %s", cfg.embedding_model)
        _model = SentenceTransformer(cfg.embedding_model)
    return _model


def embed_text(text: str) -> list[float]:
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    model = _get_model()
    vecs = model.encode(texts, batch_size=batch_size, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


def embed_part(part: BioPart) -> list[float]:
    return embed_text(part.embedding_text())


def embed_parts(parts: Sequence[BioPart], batch_size: int = 64) -> list[list[float]]:
    texts = [p.embedding_text() for p in parts]
    return embed_texts(texts, batch_size=batch_size)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo = BioPart(
        part_id="BBa_demo",
        name="ArsR arsenic sensor promoter",
        type="promoter",
        function="Arsenic-responsive promoter from E. coli",
        description="Promoter activated in the presence of arsenite ions",
        source_database="igem",
        tags=["arsenic", "metal sensing", "biosensor"],
    )
    vec = embed_part(demo)
    print(f"Embedding dim: {len(vec)}, norm: {np.linalg.norm(vec):.4f}")
    print(f"First 8 values: {vec[:8]}")
