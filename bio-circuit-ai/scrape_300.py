"""
Targeted ingestion: scrape ~300 unique parts from each of the four databases.

For iGEM, uses the new Registry API at api.registry.igem.org (the modern
replacement for the legacy parts.igem.org site).

Usage:
    python scrape_300.py                # 300 per source (default)
    python scrape_300.py --target 500   # custom target per source
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Generator

from rich.console import Console
from rich.table import Table

from models.part import BioPart

console = Console()
logger = logging.getLogger(__name__)

IGEM_QUERIES = [
    "promoter", "GFP", "RFP", "reporter", "fluorescent",
    "biosensor", "arsenic", "mercury", "copper", "lead",
    "regulator", "repressor", "activator", "terminator",
    "toggle switch", "IPTG", "tetracycline", "arabinose",
    "quorum sensing", "kill switch", "luciferase", "enzyme",
    "ribosome binding", "plasmid backbone", "oscillator",
    "inverter", "metal sensing", "zinc", "cadmium",
    "logic gate", "cascade",
]

GENBANK_QUERIES = [
    # Explicitly target E. coli K-12 reference features so GenBank returns
    # authoritative short regulatory sequences, not bulk plasmids from random
    # teams.
    "Escherichia coli K-12 MG1655 promoter",
    "Escherichia coli K-12 sigma70 promoter",
    "Escherichia coli K-12 constitutive promoter",
    "Escherichia coli lacI repressor",
    "Escherichia coli tetR repressor",
    "Escherichia coli araC regulator",
    "Escherichia coli merR regulator mercury",
    "Escherichia coli arsR regulator arsenic",
    "Escherichia coli cueR regulator copper",
    "Escherichia coli pBAD arabinose promoter",
    "Escherichia coli Ptrc Plac Ptet promoter",
    "Escherichia coli rrnB T1 terminator",
    "Escherichia coli rho-independent terminator",
    "Escherichia coli Shine-Dalgarno ribosome binding site",
    "Escherichia coli T7 RNA polymerase promoter",
    "pSB1A3 pSB1C3 pSB1K3 plasmid backbone",
    # Keep a few well-known synthetic/fluorescent terms as a secondary sweep
    "synthetic constitutive promoter J23100",
    "GFP mut3 EGFP fluorescent protein reporter",
    "mCherry TagRFP red fluorescent protein",
    "arabinose inducible expression",
]

SYNBIOHUB_QUERIES = [
    "promoter", "terminator", "rbs",
    "gfp", "mcherry", "rfp",
    "anderson promoter", "sigma70",
    "arsenic biosensor", "mercury biosensor", "copper biosensor",
    "merR", "arsR", "cueR", "tetR", "lacI", "luxR",
    "toggle switch", "repressilator",
]

UNIPROT_QUERIES = [
    "GFP fluorescent protein AND reviewed:true",
    "arsenic repressor AND reviewed:true",
    "transcription factor E. coli AND reviewed:true",
    "fluorescent protein AND reviewed:true",
    "repressor protein synthetic AND reviewed:true",
    "activator protein E. coli AND reviewed:true",
    "metal binding transcription AND reviewed:true",
    "quorum sensing AND reviewed:true",
    "toxin antitoxin AND reviewed:true",
    "luciferase bioluminescence AND reviewed:true",
    "kinase signal transduction AND reviewed:true",
    "protease regulatory AND reviewed:true",
    "copper binding protein AND reviewed:true",
    "zinc finger protein AND reviewed:true",
    "mercury resistance AND reviewed:true",
    "sigma factor AND reviewed:true",
    "recombinase integrase AND reviewed:true",
    "CRISPR associated AND reviewed:true",
    "biosynthetic enzyme pathway AND reviewed:true",
    "membrane transport synthetic AND reviewed:true",
]

ADDGENE_QUERIES = [
    "GFP", "biosensor", "synthetic biology", "promoter",
    "CRISPR", "fluorescent reporter", "toggle switch",
    "gene circuit", "inducible expression", "repressor",
    "RFP mCherry", "luciferase", "transcription factor",
    "kill switch", "quorum sensing", "T7 expression",
    "arabinose pBAD", "tetracycline", "IPTG lac",
    "terminator", "riboswitch", "optogenetics",
    "metabolic engineering", "plasmid backbone",
]


def _capped_igem(target: int) -> Generator[BioPart, None, None]:
    """Fetch up to `target` unique iGEM parts via the new Registry API."""
    from ingestion.ingest_igem import ingest_igem
    yield from ingest_igem(queries=IGEM_QUERIES, limit=target)


def _capped_genbank(target: int) -> Generator[BioPart, None, None]:
    from ingestion.ingest_genbank import search_genbank, fetch_genbank_record

    seen: set[str] = set()
    count = 0
    per_query_limit = min(30, target)

    for q in GENBANK_QUERIES:
        if count >= target:
            break
        logger.info("GenBank query: %s (have %d/%d)", q, count, target)
        try:
            ids = search_genbank(q, limit=per_query_limit)
        except Exception:
            logger.warning("GenBank search failed for '%s'", q)
            continue

        for gid in ids:
            if count >= target:
                break
            if gid in seen:
                continue
            seen.add(gid)
            try:
                part = fetch_genbank_record(gid)
                if part:
                    count += 1
                    yield part
            except Exception:
                logger.warning("GenBank fetch failed for %s", gid)


def _capped_uniprot(target: int) -> Generator[BioPart, None, None]:
    from ingestion.ingest_uniprot import search_uniprot, _parse_entry

    seen: set[str] = set()
    count = 0
    per_query_limit = min(25, target)

    for q in UNIPROT_QUERIES:
        if count >= target:
            break
        logger.info("UniProt query: %s (have %d/%d)", q, count, target)
        try:
            entries = search_uniprot(q, limit=per_query_limit)
        except Exception:
            logger.warning("UniProt search failed for '%s'", q)
            continue

        for entry in entries:
            if count >= target:
                break
            acc = entry.get("primaryAccession", "")
            if acc in seen or not acc:
                continue
            seen.add(acc)
            try:
                part = _parse_entry(entry)
                count += 1
                yield part
            except Exception:
                logger.warning("UniProt parse failed for %s", acc)


def _capped_addgene(target: int) -> Generator[BioPart, None, None]:
    from ingestion.ingest_addgene import search_addgene, _to_biopart

    seen: set[str] = set()
    count = 0
    per_query_limit = min(25, target)

    for q in ADDGENE_QUERIES:
        if count >= target:
            break
        logger.info("Addgene query: %s (have %d/%d)", q, count, target)
        try:
            entries = search_addgene(q, limit=per_query_limit)
        except Exception:
            logger.warning("Addgene search failed for '%s'", q)
            continue

        for entry in entries:
            if count >= target:
                break
            eid = entry.get("id", "")
            if eid in seen or not eid:
                continue
            seen.add(eid)
            try:
                part = _to_biopart(entry)
                count += 1
                yield part
            except Exception:
                logger.warning("Addgene parse failed for %s", eid)


def _capped_synbiohub(target: int) -> Generator[BioPart, None, None]:
    from ingestion.ingest_synbiohub import ingest_synbiohub
    yield from ingest_synbiohub(queries=SYNBIOHUB_QUERIES, limit=target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape ~300 parts from each database")
    parser.add_argument("--target", type=int, default=300, help="Target parts per source")
    args = parser.parse_args()
    target = args.target

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from database.vector_store import get_vector_store
    store = get_vector_store()

    sources = {
        "iGEM": _capped_igem,
        "GenBank": _capped_genbank,
        "UniProt": _capped_uniprot,
        "Addgene": _capped_addgene,
        "SynBioHub": _capped_synbiohub,
    }

    summary = Table(title=f"Ingestion Summary (target: {target} per source)")
    summary.add_column("Source", style="cyan")
    summary.add_column("Parts", justify="right", style="green")
    summary.add_column("Time", justify="right", style="yellow")
    summary.add_column("Status", style="bold")

    grand_total = 0

    for name, fn in sources.items():
        console.print(f"\n[bold blue]--- {name} (target: {target}) ---[/bold blue]")
        t0 = time.time()
        try:
            parts = list(fn(target))
            count = store.upsert_parts(parts)
            elapsed = time.time() - t0
            grand_total += count
            status = "[green]OK[/green]" if count >= target else f"[yellow]{count}/{target}[/yellow]"
            summary.add_row(name, str(count), f"{elapsed:.0f}s", status)
            console.print(f"[green]{name}: {count} parts in {elapsed:.0f}s[/green]")
        except Exception as e:
            elapsed = time.time() - t0
            logger.exception("Failed: %s", name)
            summary.add_row(name, "0", f"{elapsed:.0f}s", f"[red]FAIL: {e}[/red]")

    console.print()
    console.print(summary)
    console.print(f"\n[bold green]Grand total in vector store: {store.count()}[/bold green]")


if __name__ == "__main__":
    main()
