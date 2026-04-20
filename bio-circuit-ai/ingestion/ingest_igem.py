"""
Ingest biological parts from the iGEM Registry of Standard Biological Parts.

Uses the **new** iGEM Registry REST API at api.registry.igem.org (launched to
replace the legacy parts.igem.org site which is now read-only).

Key endpoints:
    GET /v1/parts?search=...&pageSize=...&page=...  — paginated search
    GET /v1/parts/slugs/{slug}                       — single part by slug
    GET /v1/parts/types                              — list part types

Rate limits (per IP):
    short  — 5 requests / 5 seconds
    medium — 60 requests / ~60 seconds
    large  — 200 requests / ~9 minutes

The script paces itself to stay well within these limits.

Quality filters (applied at ingest, not at query time):
    * organism is inferred from description text, not hardcoded
    * primers, PCR artifacts, scaffolds, and composite devices are dropped
    * parts whose description is "to do" or empty are dropped
    * parts where the declared `type` contradicts the description (e.g.
      `type=promoter` but description reads as a primer) are dropped
"""

from __future__ import annotations

import logging
import re
import time
from typing import Generator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

IGEM_API = "https://api.registry.igem.org/v1"

_TAG_KEYWORDS = [
    "metal sensing", "arsenic", "fluorescence", "green", "red", "blue",
    "biosensor", "antibiotic", "resistance", "toxin", "signaling",
    "quorum sensing", "light", "temperature", "pH", "copper", "lead",
    "mercury", "zinc", "cadmium", "GFP", "RFP", "YFP", "CFP",
    "luciferase", "lacZ", "toggle", "repressilator", "kill switch",
    "IPTG", "tetracycline", "arabinose", "AHL",
]

SLUG_TYPE_MAP = {
    "promoter": PartType.PROMOTER,
    "rbs": PartType.RBS,
    "coding": PartType.CODING,
    "reporter": PartType.REPORTER,
    "regulatory": PartType.REGULATOR,
    "terminator": PartType.TERMINATOR,
    "plasmid": PartType.PLASMID,
    "plasmid-backbone": PartType.PLASMID,
    "generator": PartType.CODING,
    "signalling": PartType.REGULATOR,
    "inverter": PartType.REGULATOR,
    "measurement": PartType.REPORTER,
    "primer": PartType.OTHER,
    "cell": PartType.OTHER,
    "device": PartType.OTHER,
    "intermediate": PartType.OTHER,
    "conjugation": PartType.OTHER,
    "t7": PartType.PROMOTER,
    "protein-domain": PartType.CODING,
    "scar": PartType.OTHER,
    "dna": PartType.OTHER,
}

TEXT_TYPE_HINTS = {
    "promoter": PartType.PROMOTER,
    "terminator": PartType.TERMINATOR,
    "rbs": PartType.RBS,
    "ribosome binding": PartType.RBS,
    "gfp": PartType.REPORTER,
    "rfp": PartType.REPORTER,
    "yfp": PartType.REPORTER,
    "cfp": PartType.REPORTER,
    "fluorescent": PartType.REPORTER,
    "reporter": PartType.REPORTER,
    "luciferase": PartType.REPORTER,
    "lacz": PartType.REPORTER,
    "repressor": PartType.REGULATOR,
    "activator": PartType.REGULATOR,
    "regulator": PartType.REGULATOR,
    "transcription factor": PartType.REGULATOR,
}


# ── Organism inference ────────────────────────────────────────────────
#
# iGEM descriptions are free-form but usually mention the source organism
# when it's relevant. We pattern-match for common bacteria / yeast / other
# chassis. Ordering matters: more specific species names come first so that
# "E. coli" doesn't accidentally match "Escherichia coli Nissle", and genus-
# only fallbacks sit below their species entries.
_ORGANISM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:e\.?\s*coli|escherichia\s*coli)\b", re.I), "Escherichia coli"),
    (re.compile(r"\b(?:b\.?\s*subtilis|bacillus\s*subtilis)\b", re.I), "Bacillus subtilis"),
    (re.compile(r"\bbacillus\b", re.I), "Bacillus"),
    (re.compile(r"\b(?:s\.?\s*aureus|staphylococcus\s*aureus)\b", re.I), "Staphylococcus aureus"),
    (re.compile(r"\bstaphylococcus\b", re.I), "Staphylococcus"),
    (re.compile(r"\b(?:p\.?\s*aeruginosa|pseudomonas\s*aeruginosa)\b", re.I), "Pseudomonas aeruginosa"),
    (re.compile(r"\b(?:p\.?\s*putida|pseudomonas\s*putida)\b", re.I), "Pseudomonas putida"),
    (re.compile(r"\bpseudomonas\b", re.I), "Pseudomonas"),
    (re.compile(r"\b(?:m\.?\s*tuberculosis|mycobacterium\s*tuberculosis)\b", re.I), "Mycobacterium tuberculosis"),
    (re.compile(r"\b(?:m\.?\s*marinum|mycobacterium\s*marinum)\b", re.I), "Mycobacterium marinum"),
    (re.compile(r"\bmycobacterium\b", re.I), "Mycobacterium"),
    (re.compile(r"\b(?:s\.?\s*cerevisiae|saccharomyces\s*cerevisiae)\b", re.I), "Saccharomyces cerevisiae"),
    (re.compile(r"\b(?:s\.?\s*pombe|schizosaccharomyces\s*pombe)\b", re.I), "Schizosaccharomyces pombe"),
    (re.compile(r"\b(?:c\.?\s*albicans|candida\s*albicans|candida)\b", re.I), "Candida albicans"),
    (re.compile(r"\byeast\b", re.I), "yeast (unspecified)"),
    (re.compile(r"\b(?:s\.?\s*flexneri|shigella\s*flexneri|shigella)\b", re.I), "Shigella flexneri"),
    (re.compile(r"\b(?:s\.?\s*marcescens|serratia\s*marcescens|serratia)\b", re.I), "Serratia marcescens"),
    (re.compile(r"\bsynechocystis\b", re.I), "Synechocystis"),
    (re.compile(r"\b(?:cyanobacteria|cyanobacterium)\b", re.I), "cyanobacteria"),
    (re.compile(r"\b(?:mammal|human|mouse|HEK293|CHO)\b", re.I), "mammalian"),
    # Phage and transposons commonly appear in iGEM terminators/promoters
    (re.compile(r"\b(?:bacteriophage|phage\s*(?:fd|T7|lambda))\b", re.I), "bacteriophage"),
]


def _infer_organism(text: str) -> str:
    """Infer the source organism from a part's free-form description text.

    Returns a canonical organism name (e.g. "Escherichia coli", "Bacillus
    subtilis"), "bacteriophage" for phage-derived parts, or "unknown" when
    the description has no organism signal.
    """
    if not text:
        return "unknown"
    for pat, name in _ORGANISM_PATTERNS:
        if pat.search(text):
            return name
    return "unknown"


# ── Junk / miscategorized filter ──────────────────────────────────────
#
# iGEM's quality control is loose — teams submit primers, PCR artifacts,
# composite devices, etc. under any part type they like. Some of the junk
# is obvious from the description; filter at ingest so downstream search
# doesn't have to.
_JUNK_PATTERNS: list[re.Pattern[str]] = [
    # Primers and PCR artifacts
    re.compile(r"\b(?:forward|reverse)\s+primer\b", re.I),
    re.compile(r"\bcolony\s+pcr\b", re.I),
    re.compile(r"\bcol[_\-]?pcr\b", re.I),
    re.compile(r"\bsequencing\s+primer\b", re.I),
    re.compile(r"\bPCR\s+primer\b", re.I),
    re.compile(r"\bamplification\s+of\s+the\b", re.I),
    re.compile(r"\bused\s+for\s+(?:colony\s+)?PCR\b", re.I),
    # Composite devices that bundle reporter+regulator+reporter+etc.
    # Match regardless of what words precede "reporter device" / "sensing device".
    re.compile(r"\breporter\s+device\b", re.I),
    re.compile(r"\bsensing\s+device\b", re.I),
    re.compile(r"\bchromoprotein\s+reporter\b", re.I),
    re.compile(r"\bexpression\s+cassette\b", re.I),
    re.compile(r"\bexpression\s+device\b", re.I),
    re.compile(r"\btranscription\s+unit\b", re.I),
    re.compile(r"\bco-?expresses?\b", re.I),
    # Cassette-style compound names: "... promoter-RBS-X-terminator" etc.
    # Require hyphen/plus delimiters between part-type words (not bare
    # spaces) so natural-language descriptions that mention multiple part
    # types don't get caught.
    re.compile(
        r"\b(?:promoter|rbs|cds|terminator)\b[^\n]{0,40}?[-+]"
        r"[^\n]{0,40}?\b(?:promoter|rbs|cds|terminator|gene|protein|coding|reporter)\b",
        re.I,
    ),
    # Tags, scars, fusion helpers — not standalone parts
    re.compile(r"\bspytag\b", re.I),
    re.compile(r"\bsortase\s+tag\b", re.I),
    re.compile(r"\bscar\s+sequence\b", re.I),
    re.compile(r"\bfiller\s+sequence\b", re.I),
    re.compile(r"\bcolor(?:less)?\s+(?:vector|plasmid)\b", re.I),
]

_TO_DO_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*to\s*do\s*$", re.I),
    re.compile(r"^\s*$"),
    re.compile(r"^\s*tbd\s*$", re.I),
    re.compile(r"^\s*placeholder\s*$", re.I),
]


def _is_junk(name: str, title: str, description: str, type_slug: str) -> tuple[bool, str]:
    """Return (is_junk, reason).

    Scans TITLE + DESCRIPTION combined — composite cassettes often only
    reveal themselves in the title (e.g. "X-Y-Z-terminator"), while primers
    often only reveal themselves in the description.
    """
    if type_slug in {"primer", "cell", "intermediate", "conjugation", "scar", "dna"}:
        return True, f"type_slug={type_slug}"

    name_blob = f"{name} {title}".lower()
    combined = f"{title} {description or ''}".strip()

    # Drop empty / TODO descriptions — not usable for embedding or LLM reasoning
    if any(p.search(description or "") for p in _TO_DO_PATTERNS):
        return True, "description is placeholder/empty"

    for pat in _JUNK_PATTERNS:
        if pat.search(combined):
            return True, f"junk pattern: {pat.pattern[:50]}"

    # Name-based red flags — iGEM teams often bake the word into the part name
    if any(tok in name_blob for tok in (
        "primer", "colpcr", "col_pcr", "_fwd", "_rev", "fwd_primer", "rev_primer",
    )):
        return True, f"name looks like a primer: {name}"

    return False, ""


def _classify_type(type_slug: str, text: str) -> PartType:
    pt = SLUG_TYPE_MAP.get(type_slug)
    if pt and pt != PartType.OTHER:
        return pt
    lower = text.lower()
    for hint, hpt in TEXT_TYPE_HINTS.items():
        if hint in lower:
            return hpt
    return pt or PartType.OTHER


def _auto_tag(text: str) -> list[str]:
    lower = text.lower()
    return [kw for kw in _TAG_KEYWORDS if kw in lower]


class _RateLimitError(Exception):
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=3, max=30),
    retry=retry_if_exception_type(_RateLimitError),
)
def _api_get(path: str, params: dict | None = None) -> dict:
    url = f"{IGEM_API}{path}"
    resp = httpx.get(url, params=params, timeout=30,
                     headers={"Accept": "application/json"})
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("retry-after", "10"))
        logger.warning("Rate limited, sleeping %ds", retry_after)
        time.sleep(retry_after)
        raise _RateLimitError("429")
    resp.raise_for_status()
    return resp.json()


def search_parts(query: str, page: int = 1, page_size: int = 100) -> tuple[list[dict], int]:
    """Search the new iGEM Registry. Returns (parts_list, total_count)."""
    data = _api_get("/parts", params={
        "search": query,
        "pageSize": min(page_size, 100),
        "page": page,
    })
    return data.get("data", []), data.get("total", 0)


def fetch_part_by_slug(slug: str) -> dict | None:
    try:
        return _api_get(f"/parts/slugs/{slug}")
    except Exception:
        logger.warning("Failed to fetch part by slug: %s", slug)
        return None


# Canonical iGEM parts that every synthetic-biology demo assumes is present.
# Keyword-based scrape queries (in scrape_300.py) return iGEM's newest parts
# first and bury these well-known classics, so we pull them explicitly by
# slug. Covers the Anderson constitutive promoter library, standard RBSs,
# double terminators, classic fluorescent reporters, canonical TFs and
# their cognate inducible promoters, and the frontline metal-sensing
# biosensor parts.
CANONICAL_IGEM_IDS: list[str] = [
    # Anderson constitutive promoter library (BBa_J23100–J23119)
    *(f"BBa_J2310{d}" for d in range(10)),
    *(f"BBa_J2311{d}" for d in range(10)),
    # Standard RBSs (Salis / Elowitz lineages)
    "BBa_B0030", "BBa_B0031", "BBa_B0032", "BBa_B0033", "BBa_B0034",
    # Terminators
    "BBa_B0010", "BBa_B0012", "BBa_B0015", "BBa_B1006",
    # Fluorescent reporters
    "BBa_E0040",   # GFP mut3b
    "BBa_E1010",   # mRFP1
    "BBa_E0030",   # EYFP
    "BBa_I13521",  # RFP+LVA for toggle switches
    "BBa_K592100", # mCherry codon-optimized
    # Classic regulators (CDS) and their cognate promoters
    "BBa_C0012", "BBa_R0010",   # LacI / PLacI
    "BBa_C0040", "BBa_R0040",   # TetR / PTet
    "BBa_C0051", "BBa_R0051",   # cI / PcI
    "BBa_C0061", "BBa_C0062", "BBa_R0062",  # LuxI / LuxR / PLux
    "BBa_C0080", "BBa_I0500",   # AraC / pBAD
    # Metal-sensing biosensor parts (arsenic / mercury / copper / lead)
    "BBa_K4767001",    # Pars (current arsenic-responsive promoter in registry)
    "BBa_K5060011",    # ArsR protein (UniProt P52144)
    "BBa_K346001",     # Pmer mercury-responsive promoter (may or may not exist)
    "BBa_K346002",     # MerR mercury regulator
    "BBa_J45992",      # PcopA copper-responsive promoter
]


def _id_to_slug(part_id: str) -> str:
    """iGEM slugs are the `name` lowercased with underscores → hyphens."""
    return part_id.lower().replace("_", "-")


def ingest_igem_canonical() -> Generator[BioPart, None, None]:
    """Pull a curated list of canonical iGEM parts by slug.

    Bypasses search ranking entirely — each part is fetched directly via
    its `/parts/slugs/{slug}` endpoint. Pieces that no longer exist in the
    registry are logged and skipped. All the usual junk/organism filters
    still apply via _parse_part.
    """
    seen: set[str] = set()
    for pid in CANONICAL_IGEM_IDS:
        if pid in seen:
            continue
        seen.add(pid)
        slug = _id_to_slug(pid)
        raw = fetch_part_by_slug(slug)
        if not raw:
            logger.info("Canonical iGEM part %s not in registry — skipping", pid)
            continue
        part = _parse_part(raw)
        if part is None:
            logger.info("Canonical iGEM part %s filtered as junk — skipping", pid)
            continue
        yield part
        time.sleep(0.3)  # keep well under the 5-req/5s short rate limit


def _parse_part(raw: dict) -> BioPart | None:
    """Parse a raw iGEM API response into a BioPart. Returns None for junk."""
    name = raw.get("name", "")
    if not name:
        return None

    title = raw.get("title", "") or ""
    description = raw.get("description", "") or ""
    sequence = raw.get("sequence", "") or ""
    type_obj = raw.get("type") or {}
    type_slug = (type_obj.get("slug", "") or "").lower()
    source = raw.get("source", "") or ""

    # Drop primers, composites, TODO entries, mis-categorized parts
    is_junk, reason = _is_junk(name, title, description, type_slug)
    if is_junk:
        logger.debug("iGEM skip %s: %s", name, reason)
        return None

    full_text = f"{name} {title} {description}"
    organism_text = f"{description} {title} {source}"
    organism = _infer_organism(organism_text)

    return BioPart(
        part_id=name,
        name=title or name,
        type=_classify_type(type_slug, full_text),
        organism=organism,
        function=description or title,
        sequence=sequence,
        description=description or title,
        references=[f"https://registry.igem.org/parts/{raw.get('slug', name.lower())}"],
        source_database="igem",
        tags=_auto_tag(full_text),
    )


def ingest_igem(
    queries: list[str] | None = None,
    limit: int = 50,
) -> Generator[BioPart, None, None]:
    """
    Ingest parts from the new iGEM Registry API.

    Iterates through search queries, paginating each until `limit` unique
    parts are collected across all queries. Junk parts (primers, devices,
    empty descriptions) are dropped at parse time and do NOT count toward
    the limit — you'll always get `limit` real parts.
    """
    if queries is None:
        queries = [
            "promoter", "GFP", "reporter", "biosensor",
            "arsenic", "metal sensing", "regulator",
        ]

    seen: set[str] = set()
    count = 0
    dropped = 0

    for q in queries:
        if count >= limit:
            break
        logger.info("iGEM search: %s (have %d/%d, dropped %d)", q, count, limit, dropped)

        page = 1
        while count < limit:
            try:
                parts_raw, total = search_parts(q, page=page, page_size=100)
            except Exception:
                logger.warning("iGEM search failed for '%s' page %d", q, page)
                break

            if not parts_raw:
                break

            for raw in parts_raw:
                if count >= limit:
                    break
                part_name = raw.get("name", "")
                if part_name in seen or not part_name:
                    continue
                seen.add(part_name)

                part = _parse_part(raw)
                if part is None:
                    dropped += 1
                    continue

                count += 1
                yield part

            if len(parts_raw) < 100 or page * 100 >= total:
                break
            page += 1
            time.sleep(1.2)

        time.sleep(1)

    logger.info("iGEM ingest done: kept %d, dropped %d junk/mis-typed", count, dropped)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_igem(["arsenic", "GFP"], limit=10):
        print(f"{p.part_id}: {p.type.value} [{p.organism}] -- {p.name[:60]} -- seq={len(p.sequence)}bp")
