"""
Ingest plasmids and parts from Addgene.

Addgene provides a public search API and plasmid detail pages.  This script
queries for relevant plasmids and normalises the results into BioPart objects.
"""

from __future__ import annotations

import logging
import re
from typing import Generator

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

ADDGENE_SEARCH = "https://www.addgene.org/search/catalog/plasmids/"
ADDGENE_API = "https://www.addgene.org/search/api/"

_HEADERS = {
    "User-Agent": "BioCircuitAI/0.1 (academic research; +https://github.com/bio-circuit-ai)",
}

_TAG_KEYWORDS = [
    "metal sensing", "arsenic", "fluorescence", "biosensor", "GFP",
    "RFP", "reporter", "CRISPR", "promoter", "synthetic biology",
]


def _auto_tag(text: str) -> list[str]:
    lower = text.lower()
    return [kw for kw in _TAG_KEYWORDS if kw in lower]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def search_addgene(query: str, limit: int = 25) -> list[dict]:
    """
    Search Addgene for plasmids matching a query.

    Returns a list of dicts with keys: id, name, description, url.
    """
    headers = {**_HEADERS, "Accept": "application/json"}
    params = {"q": query, "page_size": limit}
    resp = httpx.get(ADDGENE_API, params=params, headers=headers, timeout=30, follow_redirects=True)

    if resp.status_code == 200:
        try:
            data = resp.json()
            results = data.get("results", data.get("plasmids", []))
            return [
                {
                    "id": str(r.get("id", r.get("addgene_id", ""))),
                    "name": r.get("name", ""),
                    "description": r.get("description", r.get("purpose", "")),
                    "url": r.get("url", f"https://www.addgene.org/{r.get('id', '')}/"),
                }
                for r in results[:limit]
            ]
        except Exception:
            pass

    resp2 = httpx.get(
        ADDGENE_SEARCH, params={"q": query}, headers=_HEADERS, timeout=30, follow_redirects=True,
    )
    if resp2.status_code != 200:
        return []

    soup = BeautifulSoup(resp2.text, "html.parser")
    items: list[dict] = []

    for link in soup.find_all("a", href=re.compile(r"/\d+/")):
        href = link.get("href", "")
        plasmid_id = re.search(r"/(\d+)/", href)
        if not plasmid_id:
            continue
        name = link.text.strip()
        if not name or len(name) < 3:
            continue
        parent = link.find_parent(["tr", "div", "li"])
        description = ""
        if parent:
            desc_el = parent.find(string=True, recursive=True)
            full_text = parent.get_text(separator=" ", strip=True)
            description = full_text[:300] if full_text != name else ""
        items.append({
            "id": plasmid_id.group(1),
            "name": name,
            "description": description,
            "url": f"https://www.addgene.org{href}" if href.startswith("/") else href,
        })
        if len(items) >= limit:
            break
    return items


def _to_biopart(entry: dict) -> BioPart:
    full_text = f"{entry['name']} {entry['description']}"
    return BioPart(
        part_id=f"addgene_{entry['id']}",
        name=entry["name"],
        type=PartType.PLASMID,
        organism="unknown",
        function=entry["description"][:500],
        sequence="",
        description=entry["description"][:1000],
        references=[entry["url"]],
        source_database="addgene",
        tags=_auto_tag(full_text),
    )


def ingest_addgene(queries: list[str] | None = None, limit: int = 25) -> Generator[BioPart, None, None]:
    if queries is None:
        queries = ["biosensor", "GFP reporter", "arsenic", "synthetic biology promoter"]

    seen: set[str] = set()
    for q in queries:
        logger.info("Addgene search: %s", q)
        try:
            entries = search_addgene(q, limit=limit)
        except Exception:
            logger.exception("Addgene search failed for '%s'", q)
            continue

        for entry in entries:
            eid = entry.get("id", "")
            if eid in seen or not eid:
                continue
            seen.add(eid)
            try:
                yield _to_biopart(entry)
            except Exception:
                logger.exception("Failed to parse Addgene entry %s", eid)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_addgene(["arsenic biosensor"], limit=3):
        print(f"{p.part_id}: {p.type.value} — {p.name}")
