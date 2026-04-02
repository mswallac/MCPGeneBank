"""
Standalone ingestion runner — populates the vector store from all databases.

Usage:
    python run_ingestion.py                          # ingest into Qdrant
    python run_ingestion.py --sources igem genbank   # specific sources only
    python run_ingestion.py --queries arsenic GFP    # custom search queries
    python run_ingestion.py --in-memory              # use in-memory Qdrant (dev mode)
    python run_ingestion.py --csv                    # skip Qdrant, write CSV only
    python run_ingestion.py --csv -o parts.csv       # CSV with custom filename
    python run_ingestion.py --csv --full-sequence    # include full DNA sequences in CSV
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import time

from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "part_id", "name", "type", "organism", "function",
    "sequence_length", "sequence_preview", "description",
    "references", "source_database", "tags",
]

CSV_FIELDS_FULL = [
    "part_id", "name", "type", "organism", "function",
    "sequence_length", "sequence", "description",
    "references", "source_database", "tags",
]


def _part_to_row(part, full_sequence: bool) -> dict:
    seq = part.sequence or ""
    row = {
        "part_id": part.part_id,
        "name": part.name,
        "type": part.type.value,
        "organism": part.organism,
        "function": (part.function or "")[:500],
        "sequence_length": len(seq),
        "description": (part.description or "")[:500],
        "references": "; ".join(part.references) if part.references else "",
        "source_database": part.source_database,
        "tags": ", ".join(part.tags) if part.tags else "",
    }
    if full_sequence:
        row["sequence"] = seq
    else:
        row["sequence_preview"] = seq[:100] + ("..." if len(seq) > 100 else "")
    return row


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
    parser.add_argument("--csv", action="store_true", help="Write to CSV instead of Qdrant")
    parser.add_argument(
        "-o", "--output",
        default=os.path.join("data", "parts_export.csv"),
        help="CSV output path (used with --csv, default: data/parts_export.csv)",
    )
    parser.add_argument(
        "--full-sequence", action="store_true",
        help="Include full sequences in CSV instead of 100-char previews",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from ingestion.ingest_addgene import ingest_addgene
    from ingestion.ingest_genbank import ingest_genbank
    from ingestion.ingest_igem import ingest_igem
    from ingestion.ingest_snapgene import ingest_snapgene
    from ingestion.ingest_uniprot import ingest_uniprot

    source_map = {
        "igem": ingest_igem,
        "genbank": ingest_genbank,
        "uniprot": ingest_uniprot,
        "addgene": ingest_addgene,
        "snapgene": ingest_snapgene,
    }

    store = None
    csv_writer = None
    csv_file = None

    if args.csv:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        fields = CSV_FIELDS_FULL if args.full_sequence else CSV_FIELDS
        csv_file = open(args.output, "w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_file, fieldnames=fields, extrasaction="ignore")
        csv_writer.writeheader()
        console.print(f"[bold]Writing to CSV: {args.output}[/bold]")
    else:
        from database.vector_store import get_vector_store
        store = get_vector_store(in_memory=args.in_memory)

    table = Table(title="Ingestion Summary")
    table.add_column("Source", style="cyan")
    table.add_column("Parts", justify="right", style="green")
    table.add_column("Time (s)", justify="right", style="yellow")
    table.add_column("Status", style="bold")

    grand_total = 0

    try:
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
                if args.csv:
                    for part in parts:
                        csv_writer.writerow(_part_to_row(part, args.full_sequence))
                    count = len(parts)
                else:
                    count = store.upsert_parts(parts)
                elapsed = time.time() - t0
                grand_total += count
                table.add_row(src, str(count), f"{elapsed:.1f}", "[green]OK[/green]")
            except Exception as e:
                elapsed = time.time() - t0
                logger.exception("Ingestion failed for %s", src)
                table.add_row(src, "0", f"{elapsed:.1f}", f"[red]FAIL: {e}[/red]")
    finally:
        if csv_file:
            csv_file.close()

    console.print()
    console.print(table)

    if args.csv:
        console.print(f"\n[bold green]Wrote {grand_total} parts to {args.output}[/bold green]")
    else:
        console.print(f"\n[bold green]Total parts in vector store: {store.count()}[/bold green]")


if __name__ == "__main__":
    main()
