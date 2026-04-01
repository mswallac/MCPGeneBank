"""
Specialised retrieval for sensor / detector parts.

A "sensor" in a genetic circuit is typically a promoter or regulatory element
that responds to a specific environmental stimulus (molecule, light, pH, etc.).
"""

from __future__ import annotations

from models.part import BioPart, PartType
from tools.search_parts import search_parts


def find_sensor(target_molecule: str, limit: int = 5) -> list[BioPart]:
    """
    Find promoter/sensor parts that detect *target_molecule*.

    Search strategy: query the vector store for promoters matching the target.
    Falls back to a broader search if promoter-specific results are sparse.
    """
    queries = [
        f"{target_molecule} sensing promoter",
        f"{target_molecule} responsive promoter",
        f"{target_molecule} detector biosensor",
    ]

    candidates: dict[str, BioPart] = {}
    for q in queries:
        hits = search_parts(q, limit=limit, part_type=PartType.PROMOTER.value)
        for h in hits:
            candidates[h.part_id] = h

    if len(candidates) < 2:
        broader = search_parts(f"{target_molecule} sensor", limit=limit)
        for h in broader:
            candidates[h.part_id] = h

    return list(candidates.values())[:limit]
