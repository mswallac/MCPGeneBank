"""
Ingest Cello UCF part libraries for E. coli.

Cello (Cellocad, https://cellocad.org) publishes User Constraints Files (UCFs)
at https://github.com/CIDARLAB/Cello-UCF. Each UCF is a JSON document with a
curated, characterized set of parts — promoters, RBSs, terminators, ribozyme
insulators, and gate CDSs — measured in specific E. coli strains for specific
placement landing pads. The parts in Cello's E. coli UCFs are the gold
standard for combinatorial circuit design: every entry has measured
dynamic range, and TF/cognate-promoter pairs are explicitly grouped.

We pull the three E. coli UCFs from the `develop` branch:
    Eco1C1G1T1  (first-generation, ~50 characterized parts, genome-integrated)
    Eco1C2G2T2  (second-generation)
    Eco2C1G3T1  (newer characterization set)

Together they give ~150-200 unique atomic parts, all explicitly intended for
E. coli — no wrong-host machinery, no composite cassettes, no primers.

Each UCF is a JSON list; we want entries with `collection=parts` and
`type in {promoter, rbs, terminator, cds, ribozyme}`. Scars are skipped
(too short / structural).
"""
from __future__ import annotations

import logging
from typing import Generator

import httpx

from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

CELLO_UCFS: list[str] = [
    "https://raw.githubusercontent.com/CIDARLAB/Cello-UCF/develop/files/v2/ucf/Eco/Eco1C1G1T1.UCF.json",
    "https://raw.githubusercontent.com/CIDARLAB/Cello-UCF/develop/files/v2/ucf/Eco/Eco1C2G2T2.UCF.json",
    "https://raw.githubusercontent.com/CIDARLAB/Cello-UCF/develop/files/v2/ucf/Eco/Eco2C1G3T1.UCF.json",
]

# Which UCF part `type` values we ingest and how they map to our PartType enum.
# Scars and motif_library are skipped; ribozymes are kept because they're
# useful insulators in real Cello designs.
_TYPE_MAP: dict[str, PartType] = {
    "promoter": PartType.PROMOTER,
    "rbs": PartType.RBS,
    "terminator": PartType.TERMINATOR,
    "cds": PartType.CODING,
    "ribozyme": PartType.OTHER,  # valid atomic part but no exact enum slot
}


def _fetch_ucf(url: str) -> list[dict]:
    """Download and parse a UCF JSON file. Returns the top-level list or [] on failure."""
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Failed to fetch UCF %s: %s", url, e)
        return []
    if not isinstance(data, list):
        logger.warning("UCF %s is not a list (got %s)", url, type(data).__name__)
        return []
    return data


def _ucf_label(url: str) -> str:
    """'Eco1C1G1T1' from the URL."""
    leaf = url.rsplit("/", 1)[-1]  # Eco1C1G1T1.UCF.json
    return leaf.split(".", 1)[0]


def _collection_parts(ucf: list[dict]) -> Generator[dict, None, None]:
    """Yield entries with collection='parts'."""
    for entry in ucf:
        if entry.get("collection") == "parts":
            yield entry


def _to_biopart(raw: dict, ucf_label: str) -> BioPart | None:
    name = raw.get("name", "") or ""
    seq = raw.get("dnasequence", "") or ""
    part_type = (raw.get("type", "") or "").lower()
    if not name or not seq or part_type not in _TYPE_MAP:
        return None

    pt = _TYPE_MAP[part_type]
    # Every Cello UCF in the Eco directory is explicitly for E. coli — no
    # inference needed. Annotate with the specific UCF for traceability.
    ucf_note = f"Cello {ucf_label} UCF"
    description = f"{ucf_note} characterized {part_type} '{name}' (sequence length {len(seq)} bp)."

    # IDs must not contain colons — Knox's tusSpec parser uses `:` as the
    # field delimiter between part_id, role, and label. A "cello:X:Y" ID
    # would get split and mangled into bogus role/label fields.
    return BioPart(
        part_id=f"cello-{ucf_label}-{name}",
        name=name,
        type=pt,
        organism="Escherichia coli",
        function=f"Cello-characterized {part_type}",
        sequence=seq,
        description=description,
        references=[f"https://github.com/CIDARLAB/Cello-UCF (UCF {ucf_label})"],
        source_database="cello",
        tags=["cello", part_type, ucf_label],
        metadata={"ucf": ucf_label, "cello_type": part_type},
    )


def ingest_cello(ucfs: list[str] | None = None) -> Generator[BioPart, None, None]:
    """Yield BioParts from all Cello E. coli UCFs.

    Dedupe by part name — if the same promoter appears across multiple UCFs
    we emit it once (with whichever UCF yielded it first). The ID carries
    the first UCF label so it's still traceable.
    """
    urls = ucfs if ucfs is not None else CELLO_UCFS
    seen: set[str] = set()
    total = 0
    for url in urls:
        label = _ucf_label(url)
        logger.info("Cello UCF: fetching %s", label)
        ucf = _fetch_ucf(url)
        if not ucf:
            continue
        kept = 0
        for raw in _collection_parts(ucf):
            name = raw.get("name", "")
            if not name or name in seen:
                continue
            part = _to_biopart(raw, label)
            if part is None:
                continue
            seen.add(name)
            kept += 1
            yield part
        logger.info("Cello UCF %s: kept %d unique parts", label, kept)
        total += kept
    logger.info("Cello total: %d unique parts across %d UCFs", total, len(urls))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_cello():
        print(f"{p.part_id}: {p.type.value:10s} -- {p.name:25s} -- seq={len(p.sequence)}bp")
