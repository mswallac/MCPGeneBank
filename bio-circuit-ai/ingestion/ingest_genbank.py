"""
Ingest biological parts from NCBI GenBank via Entrez utilities.

Uses Biopython's Entrez module to search and fetch nucleotide records, then
normalises them into BioPart objects.
"""

from __future__ import annotations

import logging
import re
from typing import Generator

from Bio import Entrez, SeqIO
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

_TYPE_HINTS: dict[str, PartType] = {
    "promoter": PartType.PROMOTER,
    "GFP": PartType.REPORTER,
    "RFP": PartType.REPORTER,
    "fluorescent": PartType.REPORTER,
    "luciferase": PartType.REPORTER,
    "repressor": PartType.REGULATOR,
    "activator": PartType.REGULATOR,
    "transcription factor": PartType.REGULATOR,
    "terminator": PartType.TERMINATOR,
    "ribosome binding": PartType.RBS,
}

_TAG_KEYWORDS = [
    "metal sensing", "arsenic", "fluorescence", "biosensor", "copper",
    "mercury", "lead", "zinc", "cadmium", "antibiotic", "GFP", "RFP",
]


def _init_entrez() -> None:
    cfg = get_settings()
    Entrez.email = cfg.ncbi_email or "biocircuit@example.com"
    if cfg.ncbi_api_key:
        Entrez.api_key = cfg.ncbi_api_key


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
def search_genbank(query: str, limit: int = 50) -> list[str]:
    _init_entrez()
    handle = Entrez.esearch(db="nucleotide", term=query, retmax=limit)
    record = Entrez.read(handle)
    handle.close()
    return record.get("IdList", [])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def fetch_genbank_record(accession_id: str) -> BioPart | None:
    _init_entrez()
    handle = Entrez.efetch(db="nucleotide", id=accession_id, rettype="gb", retmode="text")
    records = list(SeqIO.parse(handle, "genbank"))
    handle.close()

    if not records:
        return None

    rec = records[0]
    description = rec.description or rec.name
    organism = ""
    for feat in rec.features:
        if feat.type == "source":
            organism = feat.qualifiers.get("organism", [""])[0]
            break

    try:
        sequence = str(rec.seq)
    except Exception:
        sequence = ""

    full_text = f"{rec.name} {description} {organism}"

    return BioPart(
        part_id=rec.id,
        name=rec.name,
        type=_guess_type(full_text),
        organism=organism or "unknown",
        function=description,
        sequence=sequence,
        description=description,
        references=[f"https://www.ncbi.nlm.nih.gov/nuccore/{rec.id}"],
        source_database="genbank",
        tags=_auto_tag(full_text),
    )


def ingest_genbank(queries: list[str] | None = None, limit: int = 20) -> Generator[BioPart, None, None]:
    if queries is None:
        queries = [
            "arsenic biosensor synthetic biology",
            "GFP reporter plasmid",
            "synthetic promoter E. coli",
        ]

    seen: set[str] = set()
    for q in queries:
        logger.info("GenBank search: %s", q)
        try:
            ids = search_genbank(q, limit=limit)
        except Exception:
            logger.exception("GenBank search failed for '%s'", q)
            continue

        for gid in ids:
            if gid in seen:
                continue
            seen.add(gid)
            try:
                part = fetch_genbank_record(gid)
                if part:
                    yield part
            except Exception:
                logger.exception("Failed to fetch GenBank record %s", gid)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_genbank(["arsenic sensor"], limit=3):
        print(f"{p.part_id}: {p.type.value} — {p.function[:80]}")
