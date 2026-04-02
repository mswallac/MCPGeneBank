"""
Ingest plasmids and sequences from Addgene using an authenticated session.

Uses your regular Addgene account (username + password) to log in and
download GenBank sequence files that are gated behind Addgene's login wall.

Set these in your .env:
    ADDGENE_USERNAME=your-username
    ADDGENE_PASSWORD=your-password

Flow:
    1. Log in to addgene.org (Django CSRF + session cookies)
    2. Search the public plasmid catalog via HTML scraping
    3. For each plasmid, visit its /sequences/ page to find GenBank links
    4. Download .gbk files and parse them with Biopython
"""

from __future__ import annotations

import logging
import re
import time
from io import StringIO
from typing import Generator

import httpx
from Bio import SeqIO
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

BASE = "https://www.addgene.org"
LOGIN_URL = f"{BASE}/users/login/"
SEARCH_URL = f"{BASE}/search/catalog/plasmids/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_TAG_KEYWORDS = [
    "metal sensing", "arsenic", "fluorescence", "biosensor", "GFP",
    "RFP", "reporter", "CRISPR", "promoter", "synthetic biology",
    "toggle switch", "kill switch", "antibiotic", "resistance",
    "luciferase", "lacZ", "IPTG", "tetracycline", "arabinose",
]

_TYPE_HINTS: dict[str, PartType] = {
    "promoter": PartType.PROMOTER,
    "gfp": PartType.REPORTER,
    "rfp": PartType.REPORTER,
    "yfp": PartType.REPORTER,
    "fluorescent": PartType.REPORTER,
    "luciferase": PartType.REPORTER,
    "reporter": PartType.REPORTER,
    "repressor": PartType.REGULATOR,
    "activator": PartType.REGULATOR,
    "crispr": PartType.REGULATOR,
    "terminator": PartType.TERMINATOR,
    "enzyme": PartType.ENZYME,
}


def _auto_tag(text: str) -> list[str]:
    lower = text.lower()
    return [kw for kw in _TAG_KEYWORDS if kw in lower]


def _guess_type(text: str) -> PartType:
    lower = text.lower()
    for hint, pt in _TYPE_HINTS.items():
        if hint in lower:
            return pt
    return PartType.PLASMID


class AddgeneSession:
    """Authenticated httpx session for addgene.org."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=30,
        )
        self._logged_in = False

    def login(self, username: str, password: str) -> bool:
        resp = self.client.get(LOGIN_URL)
        csrf = resp.cookies.get("csrftoken", "")
        if not csrf:
            soup = BeautifulSoup(resp.text, "html.parser")
            tag = soup.find("input", {"name": "csrfmiddlewaretoken"})
            csrf = tag["value"] if tag else ""

        if not csrf:
            logger.error("Could not obtain CSRF token from Addgene login page")
            return False

        resp = self.client.post(
            LOGIN_URL,
            data={
                "csrfmiddlewaretoken": csrf,
                "username": username,
                "password": password,
            },
            headers={
                **_HEADERS,
                "Referer": LOGIN_URL,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        self._logged_in = "Log Out" in resp.text or "log-out" in resp.text
        if self._logged_in:
            logger.info("Logged in to Addgene as %s", username)
        else:
            if "Log In" in resp.text:
                logger.error(
                    "Addgene login failed — check ADDGENE_USERNAME / ADDGENE_PASSWORD in .env"
                )
            else:
                self._logged_in = True
                logger.info("Addgene login appears successful for %s", username)
        return self._logged_in

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    def get(self, url: str) -> httpx.Response:
        return self.client.get(url)

    def close(self) -> None:
        self.client.close()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def _search_catalog(session: AddgeneSession, query: str, limit: int) -> list[dict]:
    """Search Addgene's public plasmid catalog. Returns basic hit metadata."""
    resp = session.get(f"{SEARCH_URL}?q={query}")
    if resp.status_code != 200:
        logger.warning("Addgene search returned %d for '%s'", resp.status_code, query)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[dict] = []

    for row in soup.select("tr[class*='search-result'], div[class*='search-result']"):
        link = row.find("a", href=re.compile(r"/\d+/"))
        if not link:
            continue
        href = link.get("href", "")
        m = re.search(r"/(\d+)/", href)
        if not m:
            continue
        name = link.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        full_text = row.get_text(separator=" ", strip=True)
        items.append({
            "id": m.group(1),
            "name": name,
            "description": full_text[:500] if full_text != name else "",
            "url": f"{BASE}{href}" if href.startswith("/") else href,
        })
        if len(items) >= limit:
            break

    if not items:
        for link in soup.find_all("a", href=re.compile(r"/\d+/")):
            href = link.get("href", "")
            m = re.search(r"/(\d+)/", href)
            if not m:
                continue
            name = link.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            parent = link.find_parent(["tr", "div", "li"])
            description = ""
            if parent:
                description = parent.get_text(separator=" ", strip=True)[:500]
            items.append({
                "id": m.group(1),
                "name": name,
                "description": description,
                "url": f"{BASE}/{m.group(1)}/",
            })
            if len(items) >= limit:
                break

    return items


def _get_sequence_ids(session: AddgeneSession, plasmid_id: str) -> list[str]:
    """Visit a plasmid's sequences page and extract sequence record IDs."""
    resp = session.get(f"{BASE}/{plasmid_id}/sequences/")
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    seq_ids: list[str] = []
    for a in soup.find_all("a", href=re.compile(r"/browse/sequence/\d+")):
        m = re.search(r"/browse/sequence/(\d+)", a["href"])
        if m:
            seq_ids.append(m.group(1))
    return seq_ids


def _download_genbank(session: AddgeneSession, plasmid_id: str, seq_id: str) -> str | None:
    """
    Try to download the GenBank file for a given sequence record.

    Addgene hosts .gbk files on media.addgene.org but the URL contains a UUID
    we can only discover from the sequence analyzer page.  We also try the
    direct /browse/sequence/{id}/ page which may embed the sequence when
    logged in.
    """
    analyzer_url = f"{BASE}/browse/sequence/{seq_id}/"
    resp = session.get(analyzer_url)
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.find_all("a", href=re.compile(r"\.gbk")):
        gbk_url = a["href"]
        if not gbk_url.startswith("http"):
            gbk_url = f"https://media.addgene.org{gbk_url}"
        logger.info("  Downloading GenBank: %s", gbk_url)
        gbk_resp = session.get(gbk_url)
        if gbk_resp.status_code == 200 and len(gbk_resp.text) > 50:
            return gbk_resp.text

    for a in soup.find_all("a", href=re.compile(r"snapgene-media.*\.gbk")):
        gbk_url = a["href"]
        if not gbk_url.startswith("http"):
            gbk_url = f"https:{gbk_url}" if gbk_url.startswith("//") else f"https://media.addgene.org{gbk_url}"
        gbk_resp = session.get(gbk_url)
        if gbk_resp.status_code == 200 and len(gbk_resp.text) > 50:
            return gbk_resp.text

    page_text = resp.text
    locus_match = re.search(r"(LOCUS\s+.+?//)", page_text, re.DOTALL)
    if locus_match:
        return locus_match.group(1)

    return None


def _parse_genbank(gbk_text: str) -> tuple[str, str, str]:
    """Parse a GenBank string. Returns (sequence, organism, description)."""
    try:
        records = list(SeqIO.parse(StringIO(gbk_text), "genbank"))
    except Exception:
        logger.debug("Failed to parse GenBank text (%d chars)", len(gbk_text))
        return "", "", ""

    if not records:
        return "", "", ""

    rec = records[0]
    seq = str(rec.seq) if rec.seq else ""
    organism = ""
    for feat in rec.features:
        if feat.type == "source":
            organism = feat.qualifiers.get("organism", [""])[0]
            break
    description = rec.description or rec.name
    return seq, organism, description


def _fetch_plasmid_page(session: AddgeneSession, plasmid_id: str) -> dict:
    """Scrape the main plasmid page for extra metadata."""
    resp = session.get(f"{BASE}/{plasmid_id}/")
    if resp.status_code != 200:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    meta: dict = {}

    for row in soup.find_all(["li", "div", "tr"]):
        text = row.get_text(separator=" ", strip=True)
        lower = text.lower()
        if "resistance" in lower:
            meta["resistance"] = text
        elif "species" in lower or "organism" in lower:
            meta["species"] = text
        elif "vector type" in lower:
            meta["vector_type"] = text
        elif "copy number" in lower:
            meta["copy_number"] = text

    purpose_el = soup.find(string=re.compile(r"Purpose", re.I))
    if purpose_el:
        parent = purpose_el.find_parent(["div", "tr", "li"])
        if parent:
            meta["purpose"] = parent.get_text(separator=" ", strip=True)[:500]

    return meta


def _build_biopart(
    entry: dict,
    sequence: str,
    organism: str,
    gbk_description: str,
    page_meta: dict,
) -> BioPart:
    name = entry["name"]
    description = gbk_description or entry.get("description", "")
    purpose = page_meta.get("purpose", "")
    if purpose and purpose not in description:
        description = f"{description} {purpose}".strip()

    if not organism or organism == "unknown":
        species_text = page_meta.get("species", "")
        if species_text:
            organism = species_text.split(":")[-1].strip()

    full_text = f"{name} {description} {page_meta.get('resistance', '')}"

    return BioPart(
        part_id=f"addgene_{entry['id']}",
        name=name,
        type=_guess_type(full_text),
        organism=organism or "unknown",
        function=description[:500],
        sequence=sequence,
        description=description[:1000],
        references=[entry.get("url", f"{BASE}/{entry['id']}/")],
        source_database="addgene",
        tags=_auto_tag(full_text),
        metadata={k: v for k, v in page_meta.items() if v},
    )


def ingest_addgene(
    queries: list[str] | None = None,
    limit: int = 25,
) -> Generator[BioPart, None, None]:
    cfg = get_settings()

    if not cfg.addgene_username or not cfg.addgene_password:
        logger.error(
            "ADDGENE_USERNAME and ADDGENE_PASSWORD not set — skipping Addgene. "
            "Add your Addgene account credentials to your .env file."
        )
        return

    session = AddgeneSession()
    try:
        if not session.login(cfg.addgene_username, cfg.addgene_password):
            logger.error("Addgene login failed, skipping ingestion")
            return

        if queries is None:
            queries = [
                "biosensor", "GFP reporter", "arsenic",
                "synthetic biology promoter", "CRISPR",
            ]

        seen: set[str] = set()
        for q in queries:
            logger.info("Addgene search: %s", q)
            try:
                entries = _search_catalog(session, q, limit=limit)
            except Exception:
                logger.exception("Addgene search failed for '%s'", q)
                continue

            logger.info("  Found %d results", len(entries))

            for entry in entries:
                pid = entry.get("id", "")
                if pid in seen or not pid:
                    continue
                seen.add(pid)

                sequence, organism, gbk_desc = "", "", ""
                try:
                    seq_ids = _get_sequence_ids(session, pid)
                    for sid in seq_ids:
                        gbk_text = _download_genbank(session, pid, sid)
                        if gbk_text:
                            sequence, organism, gbk_desc = _parse_genbank(gbk_text)
                            if sequence:
                                break
                        time.sleep(0.3)
                except Exception:
                    logger.warning("Could not fetch sequences for plasmid %s", pid)

                page_meta: dict = {}
                try:
                    page_meta = _fetch_plasmid_page(session, pid)
                except Exception:
                    logger.debug("Could not fetch plasmid page for %s", pid)

                try:
                    part = _build_biopart(entry, sequence, organism, gbk_desc, page_meta)
                    logger.info(
                        "  %s: %s (%s) — %d bp",
                        part.part_id, part.name, part.organism, len(part.sequence),
                    )
                    yield part
                except Exception:
                    logger.exception("Failed to parse Addgene entry %s", pid)

                time.sleep(0.5)
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for p in ingest_addgene(["arsenic biosensor"], limit=3):
        print(f"{p.part_id}: {p.type.value} — {p.name} — seq={len(p.sequence)}bp")
