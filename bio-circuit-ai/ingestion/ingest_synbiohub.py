"""
Ingest biological parts from SynBioHub (synbiohub.org).

SynBioHub is the community-curated SBOL (Synthetic Biology Open Language)
repository. Parts land here with standardized SBOL `role` terms mapped to
the Sequence Ontology (SO:) — far cleaner metadata than iGEM's free-form
descriptions. Most submissions come from the CIDAR Lab, iGEM, and
individual research groups, with peer review at submission.

API:
    POST /search — structured search with predicate filters
        Content-Type: application/x-www-form-urlencoded
        Body: collection=...&objectType=ComponentDefinition&role=...
    GET /search/<query>?offset=X&limit=Y — full-text search
    Accept: application/json

Docs: https://wiki.synbiohub.org/wiki/Docs:Getting_Started_with_SynBioHub

Rate limit: none published; we self-pace at 1 req/sec.
"""

from __future__ import annotations

import logging
import time
from typing import Generator

import httpx

from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

SYNBIOHUB_API = "https://synbiohub.org"

# SBOL role URIs → our PartType enum. These are canonical Sequence Ontology
# identifiers used across all SBOL-compliant registries.
_SO_ROLE_MAP: dict[str, PartType] = {
    "http://identifiers.org/so/SO:0000167": PartType.PROMOTER,       # promoter
    "http://identifiers.org/so/SO:0000139": PartType.RBS,            # ribosome_entry_site
    "http://identifiers.org/so/SO:0000316": PartType.CODING,         # CDS
    "http://identifiers.org/so/SO:0000141": PartType.TERMINATOR,     # terminator
    "http://identifiers.org/so/SO:0000704": PartType.CODING,         # gene
    "http://identifiers.org/so/SO:0000155": PartType.PLASMID,        # plasmid
    "http://identifiers.org/so/SO:0000031": PartType.OTHER,          # aptamer
    "http://identifiers.org/so/SO:0000374": PartType.OTHER,          # ribozyme
    "http://identifiers.org/sbo/SBO:0000252": PartType.CODING,       # polypeptide chain
    # Less common but occasionally used
    "http://identifiers.org/so/SO:0000188": PartType.OTHER,          # intron
    "http://identifiers.org/so/SO:0000179": PartType.OTHER,          # 5' UTR
    "http://identifiers.org/so/SO:0000205": PartType.OTHER,          # 3' UTR
}


def _search_synbiohub(query: str, offset: int = 0, limit: int = 50) -> list[dict]:
    """Full-text search. Returns a list of part records."""
    url = f"{SYNBIOHUB_API}/search/{query}"
    resp = httpx.get(
        url,
        params={"offset": offset, "limit": limit},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code >= 400:
        logger.warning("SynBioHub search '%s' -> HTTP %d", query, resp.status_code)
        return []
    try:
        data = resp.json()
    except Exception:
        logger.warning("SynBioHub returned non-JSON for '%s'", query)
        return []
    # SynBioHub returns a bare list of hits at this endpoint
    return data if isinstance(data, list) else []


def _infer_type_from_role(role_uri: str, full_text: str) -> PartType:
    """Map an SBOL role URI to our PartType. Falls back to text hints."""
    if role_uri in _SO_ROLE_MAP:
        pt = _SO_ROLE_MAP[role_uri]
        if pt != PartType.OTHER:
            return pt
    low = full_text.lower()
    if "promoter" in low:
        return PartType.PROMOTER
    if "rbs" in low or "ribosome binding" in low:
        return PartType.RBS
    if "terminator" in low:
        return PartType.TERMINATOR
    if "reporter" in low or any(fp in low for fp in ("gfp", "rfp", "yfp", "cfp", "mcherry", "luciferase")):
        return PartType.REPORTER
    if "regulator" in low or "repressor" in low or "activator" in low or "transcription factor" in low:
        return PartType.REGULATOR
    if "cds" in low or "protein" in low or "gene" in low:
        return PartType.CODING
    return PartType.OTHER


def _infer_organism(text: str) -> str:
    """Minimal organism regex — reuses iGEM's patterns via lazy import."""
    from ingestion.ingest_igem import _infer_organism as _infer  # noqa: E501
    return _infer(text)


def _parse_part(raw: dict) -> BioPart | None:
    """Parse a SynBioHub hit into a BioPart. Returns None if unusable."""
    display_id = raw.get("displayId") or raw.get("name") or ""
    if not display_id:
        return None

    name = raw.get("name", display_id) or display_id
    description = raw.get("description", "") or ""
    role = raw.get("type", "") or ""
    uri = raw.get("uri", "") or ""
    version = raw.get("version", "")
    full_text = f"{name} {description} {role}"

    # SynBioHub API doesn't always return sequence in search results — we'd
    # have to fetch the SBOL file separately. For the demo we rely on the
    # description-level metadata; sequence is empty until a separate pass.
    sequence = raw.get("sequence", "") or ""

    # Drop obvious junk by the same heuristics we use for iGEM — tightly
    # curated submissions but the odd composite still sneaks through.
    from ingestion.ingest_igem import _is_junk
    is_junk, reason = _is_junk(display_id, name, description, "")
    if is_junk:
        logger.debug("SynBioHub skip %s: %s", display_id, reason)
        return None

    part_type = _infer_type_from_role(role, full_text)

    return BioPart(
        part_id=display_id,
        name=name,
        type=part_type,
        organism=_infer_organism(f"{description} {name}"),
        function=description,
        sequence=sequence,
        description=description,
        references=[uri] if uri else [],
        source_database="synbiohub",
        tags=[],
        metadata={"version": version, "sbol_role": role},
    )


def ingest_synbiohub(
    queries: list[str] | None = None,
    limit: int = 50,
) -> Generator[BioPart, None, None]:
    """Ingest parts from SynBioHub across the given search queries.

    Junk parts are filtered at parse time and do not count toward `limit`.
    """
    if queries is None:
        queries = [
            "promoter", "terminator", "rbs",
            "gfp", "rfp", "mcherry",
            "arsenic biosensor", "mercury biosensor",
            "toggle switch", "repressilator",
            "anderson promoter", "sigma70",
        ]

    seen: set[str] = set()
    count = 0
    dropped = 0

    for q in queries:
        if count >= limit:
            break
        logger.info("SynBioHub search: %s (have %d/%d, dropped %d)", q, count, limit, dropped)

        offset = 0
        while count < limit:
            hits = _search_synbiohub(q, offset=offset, limit=50)
            if not hits:
                break

            for raw in hits:
                if count >= limit:
                    break
                did = raw.get("displayId") or raw.get("name") or ""
                if not did or did in seen:
                    continue
                seen.add(did)

                part = _parse_part(raw)
                if part is None:
                    dropped += 1
                    continue
                count += 1
                yield part

            if len(hits) < 50:
                break
            offset += 50
            time.sleep(1.0)

        time.sleep(1.0)

    logger.info("SynBioHub ingest done: kept %d, dropped %d", count, dropped)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_synbiohub(["promoter", "gfp"], limit=10):
        print(f"{p.part_id}: {p.type.value} [{p.organism}] -- {p.name[:60]}")
