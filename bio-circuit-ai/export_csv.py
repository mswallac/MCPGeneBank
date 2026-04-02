"""
Export all parts from the local Qdrant vector store to a CSV file.

Reads directly from the on-disk Qdrant store — no network calls, no
re-ingestion.  Finishes in seconds.

Usage:
    python export_csv.py                        # default output: data/parts_export.csv
    python export_csv.py -o my_parts.csv        # custom output path
    python export_csv.py --full-sequence         # include complete sequences (large file)
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
from pathlib import Path

from qdrant_client import QdrantClient
from rich.console import Console

from config import get_settings

console = Console()
logger = logging.getLogger(__name__)

LOCAL_QDRANT_PATH = Path(__file__).resolve().parent / "data" / "qdrant_store"

FIELDS = [
    "part_id", "name", "type", "organism", "function",
    "sequence_length", "sequence_preview", "description",
    "references", "source_database", "tags",
]

FIELDS_FULL = [
    "part_id", "name", "type", "organism", "function",
    "sequence_length", "sequence", "description",
    "references", "source_database", "tags",
]


def _connect() -> QdrantClient:
    cfg = get_settings()
    try:
        client = QdrantClient(url=cfg.qdrant_url, timeout=5)
        client.get_collections()
        console.print(f"[green]Connected to remote Qdrant at {cfg.qdrant_url}[/green]")
        return client
    except Exception:
        pass

    if LOCAL_QDRANT_PATH.exists():
        client = QdrantClient(path=str(LOCAL_QDRANT_PATH))
        console.print(f"[green]Opened local Qdrant store at {LOCAL_QDRANT_PATH}[/green]")
        return client

    console.print("[red]No Qdrant store found. Run ingestion first.[/red]")
    raise SystemExit(1)


def _scroll_all(client: QdrantClient, collection: str) -> list[dict]:
    """Scroll through every point in the collection and return payloads."""
    payloads: list[dict] = []
    offset = None
    while True:
        results, next_offset = client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in results:
            if point.payload:
                payloads.append(point.payload)
        if next_offset is None:
            break
        offset = next_offset
    return payloads


def export(out_path: str, full_sequence: bool = False) -> int:
    cfg = get_settings()
    client = _connect()

    info = client.get_collection(cfg.qdrant_collection)
    total = info.points_count
    console.print(f"Collection [cyan]{cfg.qdrant_collection}[/cyan] has [bold]{total}[/bold] parts")

    if total == 0:
        console.print("[yellow]Nothing to export.[/yellow]")
        return 0

    console.print("Reading all points...")
    payloads = _scroll_all(client, cfg.qdrant_collection)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    fields = FIELDS_FULL if full_sequence else FIELDS
    written = 0

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()

        for p in payloads:
            seq = p.get("sequence", "") or ""
            refs = p.get("references", [])
            tags = p.get("tags", [])

            row = {
                "part_id": p.get("part_id", ""),
                "name": p.get("name", ""),
                "type": p.get("type", ""),
                "organism": p.get("organism", ""),
                "function": (p.get("function", "") or "")[:500],
                "sequence_length": len(seq),
                "description": (p.get("description", "") or "")[:500],
                "references": "; ".join(refs) if isinstance(refs, list) else str(refs),
                "source_database": p.get("source_database", ""),
                "tags": ", ".join(tags) if isinstance(tags, list) else str(tags),
            }

            if full_sequence:
                row["sequence"] = seq
            else:
                row["sequence_preview"] = seq[:100] + ("..." if len(seq) > 100 else "")

            writer.writerow(row)
            written += 1

    console.print(f"\n[bold green]Exported {written} parts to {out_path}[/bold green]")

    sources: dict[str, int] = {}
    for p in payloads:
        src = p.get("source_database", "unknown")
        sources[src] = sources.get(src, 0) + 1
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        console.print(f"  {src}: {count}")

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Export vector store to CSV")
    parser.add_argument(
        "-o", "--output",
        default=os.path.join("data", "parts_export.csv"),
        help="Output CSV path (default: data/parts_export.csv)",
    )
    parser.add_argument(
        "--full-sequence",
        action="store_true",
        help="Include complete sequences instead of 100-char previews",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    export(args.output, full_sequence=args.full_sequence)


if __name__ == "__main__":
    main()
