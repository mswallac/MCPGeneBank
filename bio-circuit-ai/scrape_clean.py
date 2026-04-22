"""
Curated ingestion — build a small, trustworthy parts DB from vetted sources only.

Sources (in ingest order):
  1. Cello UCF                — ~85 gold-standard E. coli atomic parts from
                                CIDARLAB/Cello-UCF (promoters, RBSs,
                                terminators, CDSs, ribozymes). Every entry
                                has measured dynamic range.
  2. iGEM canonical classics — the ~50-part curated whitelist pulled by slug
                                (Anderson J23 library, B0034, B0015, E0040,
                                Pars, Pmer, PcopA, ArsR, MerR, LacI/PLacI,
                                TetR/PTet, etc.).
  3. UniProt reviewed E. coli — Swiss-Prot entries for organism_id 562
                                (~700 CDS candidates) plus fluorescent
                                proteins across organisms.

Explicitly NOT included: keyword-based iGEM scrape (source of most junk),
SynBioHub (duplicates iGEM), Addgene (whole plasmids, not atomic parts),
broad GenBank (whole records, not atomic parts).

Usage:
    python scrape_clean.py                 # default targets (see below)
    python scrape_clean.py --uniprot 500   # cap Swiss-Prot pull
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Generator

from rich.console import Console
from rich.table import Table

from models.part import BioPart

console = Console()
logger = logging.getLogger(__name__)


# ── Source runners ────────────────────────────────────────────────────


def _run_cello() -> Generator[BioPart, None, None]:
    from ingestion.ingest_cello import ingest_cello
    yield from ingest_cello()


def _run_igem_classics() -> Generator[BioPart, None, None]:
    from ingestion.ingest_igem import ingest_igem_canonical
    yield from ingest_igem_canonical()


def _run_igem_distribution() -> Generator[BioPart, None, None]:
    from ingestion.ingest_igem_distribution import ingest_igem_distribution
    yield from ingest_igem_distribution()


# E. coli-biased UniProt queries. Each is (query, cap).
UNIPROT_QUERIES: list[tuple[str, int]] = [
    # Reviewed Swiss-Prot entries for E. coli (organism_id 562)
    ("reviewed:true AND organism_id:562", 400),
    # Fluorescent proteins across all organisms (reporters)
    ("fluorescent protein AND reviewed:true", 150),
    # Biosensor-relevant regulators (E. coli specific)
    ("transcription factor AND reviewed:true AND organism_id:562", 60),
    ("repressor AND reviewed:true AND organism_id:562", 40),
    # Metal-sensing regulators across bacteria (CDS is host-agnostic)
    ("arsenic repressor AND reviewed:true", 20),
    ("mercury resistance AND reviewed:true", 20),
    ("copper binding transcription AND reviewed:true", 20),
]


def _run_uniprot(uniprot_cap: int) -> Generator[BioPart, None, None]:
    from ingestion.ingest_uniprot import search_uniprot, _parse_entry

    seen: set[str] = set()
    total = 0
    for query, per_cap in UNIPROT_QUERIES:
        if total >= uniprot_cap:
            break
        effective = min(per_cap, uniprot_cap - total)
        logger.info("UniProt: %s  (cap=%d, have=%d/%d)", query, effective, total, uniprot_cap)
        try:
            entries = search_uniprot(query, limit=effective)
        except Exception:
            logger.exception("UniProt query failed: %s", query)
            continue
        for entry in entries:
            if total >= uniprot_cap:
                break
            acc = entry.get("primaryAccession", "")
            if not acc or acc in seen:
                continue
            seen.add(acc)
            try:
                part = _parse_entry(entry)
            except Exception:
                logger.exception("UniProt parse failed for %s", acc)
                continue
            total += 1
            yield part


# ── Main ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean curated ingestion (Cello + iGEM classics + UniProt)")
    parser.add_argument("--uniprot", type=int, default=500, help="Max UniProt parts (default 500)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from database.vector_store import get_vector_store
    store = get_vector_store()
    console.print(f"[bold]Starting clean ingestion into Qdrant (currently {store.count()} parts)[/bold]")

    sources: list[tuple[str, callable]] = [
        ("Cello UCF",          _run_cello),
        ("iGEM classics",      _run_igem_classics),
        ("iGEM distribution",  _run_igem_distribution),
        ("UniProt reviewed",   lambda: _run_uniprot(args.uniprot)),
    ]

    summary = Table(title="Ingestion Summary")
    summary.add_column("Source", style="cyan")
    summary.add_column("Parts", justify="right", style="green")
    summary.add_column("Time",  justify="right", style="yellow")
    summary.add_column("Status", style="bold")

    grand_total = 0
    for name, runner in sources:
        console.print(f"\n[bold blue]--- {name} ---[/bold blue]")
        t0 = time.time()
        try:
            parts = list(runner())
            added = store.upsert_parts(parts)
            elapsed = time.time() - t0
            grand_total += added
            summary.add_row(name, str(added), f"{elapsed:.0f}s", "[green]OK[/green]")
            console.print(f"[green]{name}: {added} parts in {elapsed:.0f}s[/green]")
        except Exception as e:
            elapsed = time.time() - t0
            logger.exception("Source failed: %s", name)
            summary.add_row(name, "0", f"{elapsed:.0f}s", f"[red]FAIL: {e}[/red]")

    console.print()
    console.print(summary)
    console.print(f"\n[bold green]Grand total in vector store: {store.count()}[/bold green]")


if __name__ == "__main__":
    main()
