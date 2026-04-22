"""
Ingest parts from the iGEM-Engineering/iGEM-distribution repo.

This repo contains the official curated packages that make up iGEM's annual
DNA distribution kits. Unlike the open-ended iGEM Registry (which we have
to filter heavily against composites / scars / junk), every package here
is a vetted bundle: Anderson promoters, Fluorescent Reporter Proteins,
metal-sensing, RBS Collection, etc. Each is maintained by a named author
and reviewed via PR.

Each package directory exposes a `views/Parts and Devices.csv` with full
sequences. We skip the `Libraries and Composites.csv` file — composites
are the same kind of junk our _is_junk filter rejects in the open-Registry
ingester.

CSV format (after a handful of metadata header rows):
    Part Name, Role, Design Notes, Altered Sequence, Part Description,
    Data Source Prefix, Data Source ID, Source Organism, Target Organism,
    Final Product, Circular, length (bp), Sequence

Source: https://github.com/iGEM-Engineering/iGEM-distribution
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Generator

import httpx

from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

REPO_RAW = "https://raw.githubusercontent.com/iGEM-Engineering/iGEM-distribution/main"
API_CONTENTS = "https://api.github.com/repos/iGEM-Engineering/iGEM-distribution/contents/"

# Role normalizer — the CSV's "Role" column is free-form ("T7 promoter",
# "Promoter + RBS + CDS", "synthetic regulatable promoter", etc.). We look
# for keywords and keep only entries that map to a single atomic part type.
# Anything containing a "+" in the role is a composite and gets rejected.
def _classify_role(role: str) -> PartType | None:
    if not role:
        return None
    lower = role.lower()
    if "+" in lower or "," in lower:
        return None
    if "promoter" in lower:
        return PartType.PROMOTER
    if "rbs" in lower or "ribosome" in lower or "shine" in lower:
        return PartType.RBS
    if "terminator" in lower:
        return PartType.TERMINATOR
    if lower.strip() in {"cds", "coding", "coding_sequence", "coding sequence"}:
        return PartType.CODING
    if "reporter" in lower:
        return PartType.REPORTER
    if "regulator" in lower or "repressor" in lower or "activator" in lower:
        return PartType.REGULATOR
    if "enzyme" in lower:
        return PartType.ENZYME
    # Plasmids, scars, operators, engineered regions, devices, etc. — skip.
    return None


def _list_packages() -> list[str]:
    """Return the names of top-level package directories in the distribution repo."""
    try:
        resp = httpx.get(API_CONTENTS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Failed to list iGEM-distribution repo contents: %s", e)
        return []
    excluded = {".github", "docs", "scripts"}
    return [e["name"] for e in data
            if e.get("type") == "dir" and e["name"] not in excluded]


def _fetch_package_csv(package: str) -> str:
    """Fetch the Parts and Devices CSV for one package, or '' on failure."""
    url = f"{REPO_RAW}/{httpx.QueryParams({'k': package})['k']}/views/Parts and Devices.csv"
    # Manual encoding — httpx's QueryParams is for query strings, not path segments.
    # iGEM package names contain spaces, which we need to encode as %20.
    from urllib.parse import quote
    url = f"{REPO_RAW}/{quote(package)}/views/{quote('Parts and Devices.csv')}"
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return ""
    return resp.text


def _find_data_table(text: str) -> list[dict[str, str]]:
    """
    The CSV has free-form metadata rows at the top (Collection Name, Authors,
    Collection Description, Example Data, ...) before the actual data table,
    which begins on a row whose first cell is exactly 'Part Name'. We scan
    for that header then parse the rest with csv.DictReader.
    """
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    header_idx = -1
    for i, r in enumerate(rows):
        if r and r[0].strip() == "Part Name":
            header_idx = i
            break
    if header_idx < 0:
        return []
    header = [c.strip() for c in rows[header_idx]]
    data: list[dict[str, str]] = []
    for r in rows[header_idx + 1:]:
        # CSV may have trailing rows that are all empty (separator) — skip them.
        if not any(cell.strip() for cell in r):
            continue
        # Pad short rows with empty strings so DictReader-style zip works.
        while len(r) < len(header):
            r.append("")
        data.append({header[i]: r[i].strip() for i in range(len(header))})
    return data


def _fetch_igem_sequence(bba_id: str) -> str:
    """Lazy-import to avoid a circular hit when ingest_igem imports us
    from scrape_clean. Returns the DNA sequence for an iGEM part by BBa
    ID, or '' if the registry lookup fails."""
    from ingestion.ingest_igem import fetch_part_by_slug, _id_to_slug
    slug = _id_to_slug(bba_id)
    try:
        raw = fetch_part_by_slug(slug)
    except Exception as e:
        logger.warning("iGEM fetch failed for %s: %s", bba_id, e)
        return ""
    if not raw:
        return ""
    return (raw.get("sequence", "") or "").strip()


def _to_biopart(package: str, row: dict[str, str]) -> BioPart | None:
    name = row.get("Part Name", "")
    raw_role = row.get("Role", "").strip()
    if not name or not raw_role:
        return None
    pt = _classify_role(raw_role)
    if pt is None:
        return None

    source_prefix = (row.get("Data Source Prefix", "") or "").strip()
    source_id = (row.get("Data Source ID", "") or name).strip()
    is_igem = source_prefix.lower() in {"igem registry", "igem", "bba"}

    # Stable part_id: prefer BBa_ for iGEM registry parts, fall back to a
    # namespaced id from the package + part name otherwise.
    if is_igem:
        part_id = source_id if source_id.upper().startswith("BBA_") else f"BBa_{source_id}"
    else:
        safe_pkg = package.replace(" ", "_")
        part_id = f"igem-dist-{safe_pkg}-{name}".replace(" ", "_")

    # Sequence resolution: CSV cell wins, otherwise ask the iGEM registry.
    seq = (row.get("Sequence", "") or "").strip()
    if not seq and is_igem:
        bba = part_id if part_id.upper().startswith("BBA_") else f"BBa_{source_id}"
        seq = _fetch_igem_sequence(bba)
    if not seq:
        # No sequence we can use for Evo 2 / assembly — drop.
        return None

    source_org = (row.get("Source Organism", "") or "").strip() or "unknown"
    target_org = (row.get("Target Organism", "") or "").strip() or source_org
    desc_user = (row.get("Part Description", "") or "").strip()
    description = f"iGEM distribution '{package}' package — {raw_role} '{name}'"
    if desc_user:
        description += f". {desc_user}"
    description += f" (sequence length {len(seq)} bp)."

    return BioPart(
        part_id=part_id,
        name=name,
        type=pt,
        organism=target_org or source_org or "unknown",
        function=f"iGEM-distribution-curated {raw_role.lower()}",
        sequence=seq,
        description=description,
        references=[f"https://github.com/iGEM-Engineering/iGEM-distribution/tree/main/{package}"],
        source_database="igem-distribution",
        tags=["igem-distribution", pt.value, package.replace(" ", "_").lower()],
        metadata={
            "package": package,
            "igem_role": raw_role,
            "source_prefix": source_prefix,
            "source_id": source_id,
            "source_organism": source_org,
            "target_organism": target_org,
        },
    )


def ingest_igem_distribution(
    packages: list[str] | None = None,
) -> Generator[BioPart, None, None]:
    """Yield BioParts from every package in the iGEM distribution repo.

    Deduplicates by part_id — if the same BBa_ ID appears in two packages
    (rare), the first one wins.
    """
    pkgs = packages if packages is not None else _list_packages()
    if not pkgs:
        logger.warning("No iGEM-distribution packages found")
        return
    import time
    seen: set[str] = set()
    total = 0
    for pkg in pkgs:
        logger.info("iGEM-distribution: fetching '%s'", pkg)
        text = _fetch_package_csv(pkg)
        if not text:
            continue
        rows = _find_data_table(text)
        kept = 0
        for row in rows:
            part = _to_biopart(pkg, row)
            # Tiny throttle so iGEM's rate limiter (5 req / 5 s) doesn't blow
            # us up when most CSV rows lack a sequence and need API lookup.
            if row.get("Sequence", "").strip() == "" and (row.get("Data Source Prefix", "") or "").lower() in {"igem registry", "igem", "bba"}:
                time.sleep(0.25)
            if part is None or part.part_id in seen:
                continue
            seen.add(part.part_id)
            kept += 1
            yield part
        logger.info("  %s: %d parts kept (of %d rows)", pkg, kept, len(rows))
        total += kept
    logger.info("iGEM distribution total: %d unique parts from %d packages", total, len(pkgs))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = 0
    by_type: dict[str, int] = {}
    for p in ingest_igem_distribution():
        by_type[p.type.value] = by_type.get(p.type.value, 0) + 1
        n += 1
    print(f"Total: {n}")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
