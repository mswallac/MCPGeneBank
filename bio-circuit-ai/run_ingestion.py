"""
Standalone ingestion runner — populates the vector store from all databases.

Usage:
    python run_ingestion.py                          # ingest from all sources
    python run_ingestion.py --sources igem genbank   # specific sources only
    python run_ingestion.py --queries arsenic GFP    # custom search queries
    python run_ingestion.py --in-memory              # use in-memory Qdrant (dev mode)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bio-Circuit AI — Data Ingestion")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["igem", "genbank", "uniprot", "addgene"],
        help="Databases to ingest from",
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        default=["promoter", "GFP", "biosensor", "arsenic", "metal sensing", "reporter"],
        help="Search queries for ingestion",
    )
    parser.add_argument("--limit", type=int, default=20, help="Max results per query per source")
    parser.add_argument("--in-memory", action="store_true", help="Use in-memory Qdrant")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from database.vector_store import get_vector_store

    store = get_vector_store(in_memory=args.in_memory)

    from ingestion.ingest_addgene import ingest_addgene
    from ingestion.ingest_genbank import ingest_genbank
    from ingestion.ingest_igem import ingest_igem
    from ingestion.ingest_uniprot import ingest_uniprot

    source_map = {
        "igem": ingest_igem,
        "genbank": ingest_genbank,
        "uniprot": ingest_uniprot,
        "addgene": ingest_addgene,
    }

    table = Table(title="Ingestion Summary")
    table.add_column("Source", style="cyan")
    table.add_column("Parts", justify="right", style="green")
    table.add_column("Time (s)", justify="right", style="yellow")
    table.add_column("Status", style="bold")

    grand_total = 0

    for src in args.sources:
        fn = source_map.get(src)
        if fn is None:
            console.print(f"[red]Unknown source: {src}[/red]")
            table.add_row(src, "0", "-", "[red]SKIP[/red]")
            continue

        console.print(f"\n[bold blue]Ingesting from {src}...[/bold blue]")
        t0 = time.time()
        try:
            parts = list(fn(queries=args.queries, limit=args.limit))
            count = store.upsert_parts(parts)
            elapsed = time.time() - t0
            grand_total += count
            table.add_row(src, str(count), f"{elapsed:.1f}", "[green]OK[/green]")
        except Exception as e:
            elapsed = time.time() - t0
            logger.exception("Ingestion failed for %s", src)
            table.add_row(src, "0", f"{elapsed:.1f}", f"[red]FAIL: {e}[/red]")

    console.print()
    console.print(table)
    console.print(f"\n[bold green]Total parts in vector store: {store.count()}[/bold green]")


if __name__ == "__main__":
    main()
