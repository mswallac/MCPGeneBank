"""
Export all ingested parts to a CSV file for inspection.

Runs the same ingestion pipeline as scrape_300.py and writes every part
to data/parts_export.csv with all fields.

Usage:
    python export_csv.py                # default 300 per source
    python export_csv.py --target 300   # explicit target
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import time

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ingested parts to CSV")
    parser.add_argument("--target", type=int, default=300, help="Target parts per source")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from scrape_300 import (
        _capped_igem, _capped_genbank, _capped_uniprot, _capped_addgene,
        IGEM_QUERIES, GENBANK_QUERIES, UNIPROT_QUERIES, ADDGENE_QUERIES,
    )

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", "parts_export.csv")

    fields = [
        "part_id", "name", "type", "organism", "function",
        "sequence_length", "sequence_preview", "description",
        "references", "source_database", "tags",
    ]

    sources = {
        "iGEM": _capped_igem,
        "GenBank": _capped_genbank,
        "UniProt": _capped_uniprot,
        "Addgene": _capped_addgene,
    }

    total = 0
    counts: dict[str, int] = {}

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for name, fn in sources.items():
            console.print(f"\n[bold blue]--- {name} ---[/bold blue]")
            t0 = time.time()
            src_count = 0

            try:
                for part in fn(args.target):
                    seq = part.sequence or ""
                    writer.writerow({
                        "part_id": part.part_id,
                        "name": part.name,
                        "type": part.type.value,
                        "organism": part.organism,
                        "function": part.function[:500],
                        "sequence_length": len(seq),
                        "sequence_preview": seq[:100] + ("..." if len(seq) > 100 else ""),
                        "description": part.description[:500],
                        "references": "; ".join(part.references),
                        "source_database": part.source_database,
                        "tags": ", ".join(part.tags),
                    })
                    src_count += 1
                    total += 1
            except Exception:
                logger.exception("Failed: %s", name)

            elapsed = time.time() - t0
            counts[name] = src_count
            console.print(f"[green]{name}: {src_count} parts ({elapsed:.0f}s)[/green]")

    console.print(f"\n[bold green]Wrote {total} parts to {out_path}[/bold green]")
    for name, c in counts.items():
        console.print(f"  {name}: {c}")


if __name__ == "__main__":
    main()
