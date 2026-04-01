"""
Specialised retrieval for reporter parts.

Reporter genes produce a measurable output signal (fluorescence, luminescence,
colorimetric, etc.) in genetic circuit designs.
"""

from __future__ import annotations

from models.part import BioPart, PartType
from tools.search_parts import search_parts

_SIGNAL_MAP: dict[str, list[str]] = {
    "green": ["GFP", "green fluorescent protein", "sfGFP", "eGFP"],
    "red": ["RFP", "mCherry", "red fluorescent protein", "DsRed"],
    "blue": ["BFP", "blue fluorescent protein", "EBFP"],
    "yellow": ["YFP", "yellow fluorescent protein", "Venus", "Citrine"],
    "cyan": ["CFP", "cyan fluorescent protein", "cerulean"],
    "luminescence": ["luciferase", "lux operon", "bioluminescence"],
    "colorimetric": ["lacZ", "beta-galactosidase", "chromoprotein"],
}


def find_reporter(output_signal: str, limit: int = 5) -> list[BioPart]:
    """
    Find reporter parts that produce *output_signal*.

    Maps common signal descriptions (e.g. "green fluorescence") to known
    reporter gene families, then searches the vector store.
    """
    signal_lower = output_signal.lower()
    query_terms: list[str] = [output_signal]

    for key, synonyms in _SIGNAL_MAP.items():
        if key in signal_lower:
            query_terms.extend(synonyms)
            break

    candidates: dict[str, BioPart] = {}
    for term in query_terms[:4]:
        q = f"{term} reporter"
        hits = search_parts(q, limit=limit, part_type=PartType.REPORTER.value)
        for h in hits:
            candidates[h.part_id] = h

    if len(candidates) < 2:
        broader = search_parts(f"{output_signal} fluorescent reporter gene", limit=limit)
        for h in broader:
            candidates[h.part_id] = h

    return list(candidates.values())[:limit]
