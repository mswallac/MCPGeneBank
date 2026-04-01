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
"""

from __future__ import annotations

import logging
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


def _parse_part(raw: dict) -> BioPart | None:
    name = raw.get("name", "")
    if not name:
        return None

    title = raw.get("title", "")
    description = raw.get("description", "")
    sequence = raw.get("sequence", "") or ""
    type_obj = raw.get("type") or {}
    type_slug = type_obj.get("slug", "")

    full_text = f"{name} {title} {description}"

    return BioPart(
        part_id=name,
        name=title or name,
        type=_classify_type(type_slug, full_text),
        organism="Escherichia coli",
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
    parts are collected across all queries.
    """
    if queries is None:
        queries = [
            "promoter", "GFP", "reporter", "biosensor",
            "arsenic", "metal sensing", "regulator",
        ]

    seen: set[str] = set()
    count = 0

    for q in queries:
        if count >= limit:
            break
        logger.info("iGEM search: %s (have %d/%d)", q, count, limit)

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
                if part:
                    count += 1
                    yield part

            if len(parts_raw) < 100 or page * 100 >= total:
                break
            page += 1
            time.sleep(1.2)

        time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_igem(["arsenic", "GFP"], limit=10):
        print(f"{p.part_id}: {p.type.value} -- {p.name[:60]} -- seq={len(p.sequence)}bp")
