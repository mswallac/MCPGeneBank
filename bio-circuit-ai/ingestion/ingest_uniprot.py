"""
Ingest protein parts from UniProt.

Uses the UniProt REST API to search for proteins relevant to synthetic biology
circuits (transcription factors, reporters, enzymes) and normalises them into
BioPart objects.
"""

from __future__ import annotations

import logging
from typing import Generator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"

_TYPE_HINTS: dict[str, PartType] = {
    "transcription factor": PartType.REGULATOR,
    "repressor": PartType.REGULATOR,
    "activator": PartType.REGULATOR,
    "fluorescent": PartType.REPORTER,
    "GFP": PartType.REPORTER,
    "luciferase": PartType.REPORTER,
    "kinase": PartType.ENZYME,
    "synthase": PartType.ENZYME,
    "protease": PartType.ENZYME,
    "promoter": PartType.PROMOTER,
}

_TAG_KEYWORDS = [
    "metal sensing", "arsenic", "fluorescence", "biosensor",
    "copper", "mercury", "lead", "zinc", "cadmium", "GFP",
    "transcription factor", "repressor",
]


def _guess_type(text: str) -> PartType:
    lower = text.lower()
    for hint, pt in _TYPE_HINTS.items():
        if hint.lower() in lower:
            return pt
    return PartType.CODING


def _auto_tag(text: str) -> list[str]:
    lower = text.lower()
    return [kw for kw in _TAG_KEYWORDS if kw in lower]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def search_uniprot(query: str, limit: int = 25) -> list[dict]:
    params = {
        "query": query,
        "format": "json",
        "size": limit,
        "fields": "accession,protein_name,organism_name,gene_names,sequence,cc_function",
    }
    resp = httpx.get(UNIPROT_SEARCH, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


def _parse_entry(entry: dict) -> BioPart:
    accession = entry.get("primaryAccession", "unknown")
    protein_name = ""
    pn = entry.get("proteinDescription", {})
    rec_name = pn.get("recommendedName")
    if rec_name:
        protein_name = rec_name.get("fullName", {}).get("value", "")
    if not protein_name:
        sub_names = pn.get("submissionNames", [])
        if sub_names:
            protein_name = sub_names[0].get("fullName", {}).get("value", "")

    organism = entry.get("organism", {}).get("scientificName", "unknown")
    gene_names = entry.get("genes", [])
    gene_str = ", ".join(
        g.get("geneName", {}).get("value", "") for g in gene_names
    )

    seq_data = entry.get("sequence", {})
    sequence = seq_data.get("value", "")

    func_comments = entry.get("comments", [])
    function = ""
    for c in func_comments:
        if c.get("commentType") == "FUNCTION":
            texts = c.get("texts", [])
            if texts:
                function = texts[0].get("value", "")
                break

    full_text = f"{protein_name} {function} {gene_str} {organism}"

    return BioPart(
        part_id=accession,
        name=protein_name or gene_str or accession,
        type=_guess_type(full_text),
        organism=organism,
        function=function or f"Protein: {protein_name}",
        sequence=sequence,
        description=f"{protein_name} ({gene_str}) from {organism}",
        references=[f"https://www.uniprot.org/uniprot/{accession}"],
        source_database="uniprot",
        tags=_auto_tag(full_text),
    )


def ingest_uniprot(queries: list[str] | None = None, limit: int = 25) -> Generator[BioPart, None, None]:
    if queries is None:
        queries = [
            "arsenic repressor AND reviewed:true",
            "GFP fluorescent protein AND reviewed:true",
            "synthetic biology transcription factor AND reviewed:true",
        ]

    seen: set[str] = set()
    for q in queries:
        logger.info("UniProt search: %s", q)
        try:
            entries = search_uniprot(q, limit=limit)
        except Exception:
            logger.exception("UniProt search failed for '%s'", q)
            continue

        for entry in entries:
            acc = entry.get("primaryAccession", "")
            if acc in seen:
                continue
            seen.add(acc)
            try:
                yield _parse_entry(entry)
            except Exception:
                logger.exception("Failed to parse UniProt entry %s", acc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_uniprot(["arsenic repressor AND reviewed:true"], limit=3):
        print(f"{p.part_id}: {p.type.value} — {p.name}")
