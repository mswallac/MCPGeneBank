"""
General-purpose semantic search over the biological parts vector store.

Provides the top-level search_parts() function used by the LLM planner,
the circuit assembler, and all specialised finders.
"""

from __future__ import annotations

from database.vector_store import get_vector_store
from models.part import BioPart, PartType, FunctionalNode


def search_parts(
    query: str,
    limit: int = 10,
    part_type: str | None = None,
    score_threshold: float = 0.0,
) -> list[BioPart]:
    store = get_vector_store()
    raw = store.search(query, limit=limit, part_type=part_type, score_threshold=score_threshold)
    parts: list[BioPart] = []
    for r in raw:
        r.pop("score", None)
        try:
            parts.append(BioPart(**r))
        except Exception:
            continue
    return parts


def search_parts_raw(
    query: str,
    limit: int = 10,
    part_type: str | None = None,
) -> list[dict]:
    """Return raw dicts with score for API responses."""
    store = get_vector_store()
    return store.search(query, limit=limit, part_type=part_type)


_ROLE_TO_PART_TYPE: dict[str, str] = {
    "promoter": "promoter",
    "sensor": "promoter",
    "inducible_promoter": "promoter",
    "constitutive_promoter": "promoter",
    "repressor": "regulator",
    "activator": "regulator",
    "regulator": "regulator",
    "transcription_factor": "regulator",
    "reporter": "reporter",
    "output": "reporter",
    "fluorescent_protein": "reporter",
    "enzyme": "enzyme",
    "terminator": "terminator",
    "rbs": "rbs",
    "toxin": "coding",
    "antitoxin": "coding",
    "recombinase": "coding",
    "protease": "enzyme",
    "kinase": "enzyme",
}


def find_parts_for_node(node: FunctionalNode, organism: str = "", limit: int = 5) -> list[BioPart]:
    """
    Universal part finder: given a FunctionalNode from any circuit spec,
    find the best matching biological parts from the vector store.
    """
    type_filter = None
    if node.required_type:
        type_filter = node.required_type.value
    elif node.role in _ROLE_TO_PART_TYPE:
        type_filter = _ROLE_TO_PART_TYPE[node.role]

    queries: list[str] = []
    if node.search_hint:
        queries.append(node.search_hint)
    if node.description:
        queries.append(node.description)
    queries.append(f"{node.role} {node.description}")

    candidates: dict[str, BioPart] = {}
    for q in queries[:3]:
        hits = search_parts(q, limit=limit, part_type=type_filter)
        for h in hits:
            candidates[h.part_id] = h

    if not candidates and type_filter:
        for q in queries[:2]:
            hits = search_parts(q, limit=limit, part_type=None)
            for h in hits:
                candidates[h.part_id] = h

    result = list(candidates.values())

    if organism:
        org_lower = organism.lower()
        result.sort(key=lambda p: (0 if org_lower in p.organism.lower() else 1))

    return result[:limit]


def find_accessory_part(query: str, part_type: PartType, limit: int = 3) -> BioPart | None:
    """Find an accessory part (RBS, terminator, etc.) by keyword."""
    hits = search_parts(query, limit=limit, part_type=part_type.value)
    return hits[0] if hits else None
