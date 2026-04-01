"""
Specialised retrieval for regulator / transcription factor parts.

Regulators connect the sensor input to the reporter output — typically
repressors or activators that control gene expression in response to the
sensed stimulus.
"""

from __future__ import annotations

from models.part import BioPart, PartType
from tools.search_parts import search_parts


def find_regulator(target: str, limit: int = 5) -> list[BioPart]:
    """
    Find regulatory parts associated with *target* (molecule or sensor name).

    Searches for transcription factors, repressors, and activators relevant
    to the target molecule or upstream sensor component.
    """
    queries = [
        f"{target} transcription factor",
        f"{target} repressor regulator",
        f"{target} activator regulatory protein",
    ]

    candidates: dict[str, BioPart] = {}
    for q in queries:
        hits = search_parts(q, limit=limit, part_type=PartType.REGULATOR.value)
        for h in hits:
            candidates[h.part_id] = h

    if len(candidates) < 2:
        broader = search_parts(f"{target} regulator", limit=limit)
        for h in broader:
            candidates[h.part_id] = h

    return list(candidates.values())[:limit]
