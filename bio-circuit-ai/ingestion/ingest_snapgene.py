"""
Ingest biological parts from SnapGene's annotated plasmid library.

SnapGene distributes 2,700+ annotated plasmid files (.dna format) covering
cloning vectors, CRISPR plasmids, expression vectors, fluorescent proteins,
and more.  This is the same dataset that GenoCAD/GenoLIB was built from,
but actively maintained and expanded.

Setup:
    1. Visit https://snapgene.com/resources/plasmid-files
    2. Click "Download Plasmid Set" on each category you want
    3. Extract the zip files into  data/snapgene/
       (the script also handles nested folders and unextracted zips)
    4. Run:  python run_ingestion.py --sources snapgene --csv

The script parses each .dna file with Biopython, extracts the plasmid
as one BioPart plus every annotated feature (promoters, CDSs, terminators,
resistance markers, etc.) as individual parts.
"""

from __future__ import annotations

import logging
import os
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Generator

from Bio import SeqIO
from Bio.SeqFeature import SeqFeature
from Bio.SeqRecord import SeqRecord

from models.part import BioPart, PartType

logger = logging.getLogger(__name__)

SNAPGENE_DIR = Path(__file__).resolve().parent.parent / "data" / "snapgene"

GENBANK_KEY_TO_PART_TYPE: dict[str, PartType] = {
    "promoter": PartType.PROMOTER,
    "terminator": PartType.TERMINATOR,
    "CDS": PartType.CODING,
    "gene": PartType.CODING,
    "rep_origin": PartType.OTHER,
    "misc_feature": PartType.OTHER,
    "misc_recomb": PartType.OTHER,
    "regulatory": PartType.REGULATOR,
    "protein_bind": PartType.REGULATOR,
    "RBS": PartType.RBS,
    "enhancer": PartType.PROMOTER,
    "primer_bind": PartType.OTHER,
    "sig_peptide": PartType.SIGNAL_PEPTIDE,
    "mat_peptide": PartType.CODING,
}

_TEXT_TYPE_HINTS: dict[str, PartType] = {
    "promoter": PartType.PROMOTER,
    "terminator": PartType.TERMINATOR,
    "reporter": PartType.REPORTER,
    "gfp": PartType.REPORTER,
    "rfp": PartType.REPORTER,
    "yfp": PartType.REPORTER,
    "cfp": PartType.REPORTER,
    "fluorescent": PartType.REPORTER,
    "luciferase": PartType.REPORTER,
    "lacz": PartType.REPORTER,
    "repressor": PartType.REGULATOR,
    "activator": PartType.REGULATOR,
    "resistance": PartType.CODING,
    "enzyme": PartType.ENZYME,
    "toxin": PartType.TOXIN,
    "antitoxin": PartType.ANTITOXIN,
    "ribosome binding": PartType.RBS,
    "origin of replication": PartType.OTHER,
}

_TAG_KEYWORDS = [
    "antibiotic", "resistance", "promoter", "terminator", "GFP", "RFP",
    "fluorescent", "CRISPR", "Cas9", "reporter", "origin", "MCS",
    "expression", "cloning", "selection", "tagging", "luciferase",
]

SKIP_FEATURE_TYPES = {"source", "primer_bind", "misc_binding", "polyA_signal"}


def _auto_tag(text: str) -> list[str]:
    lower = text.lower()
    return [kw for kw in _TAG_KEYWORDS if kw.lower() in lower]


def _classify_feature(feat: SeqFeature, label: str) -> PartType:
    pt = GENBANK_KEY_TO_PART_TYPE.get(feat.type)
    if pt and pt != PartType.OTHER:
        return pt
    lower = label.lower()
    for hint, hpt in _TEXT_TYPE_HINTS.items():
        if hint in lower:
            return hpt
    return pt or PartType.OTHER


def _feature_label(feat: SeqFeature) -> str:
    for key in ("label", "gene", "product", "note", "standard_name"):
        vals = feat.qualifiers.get(key, [])
        if vals:
            return vals[0]
    return feat.type


def _extract_organism(record: SeqRecord) -> str:
    for feat in record.features:
        if feat.type == "source":
            orgs = feat.qualifiers.get("organism", [])
            if orgs:
                return orgs[0]
    return "unknown"


def _parse_dna_file(path: Path | str, category: str = "") -> list[BioPart]:
    """Parse a single SnapGene .dna file and return BioParts."""
    parts: list[BioPart] = []
    path = Path(path)

    try:
        record = SeqIO.read(str(path), "snapgene")
    except Exception:
        try:
            record = SeqIO.read(str(path), "genbank")
        except Exception:
            logger.warning("Could not parse %s", path.name)
            return []

    plasmid_name = record.name or path.stem
    full_seq = str(record.seq) if record.seq else ""
    organism = _extract_organism(record)
    description = record.description if record.description != "<unknown description>" else ""

    plasmid_id = f"sg_{path.stem}"
    full_text = f"{plasmid_name} {description} {category}"
    parts.append(BioPart(
        part_id=plasmid_id,
        name=plasmid_name,
        type=PartType.PLASMID,
        organism=organism,
        function=description[:500] or f"{category} plasmid",
        sequence=full_seq,
        description=description[:1000] or f"SnapGene annotated plasmid from {category}",
        references=[f"https://snapgene.com/resources/plasmid-files"],
        source_database="snapgene",
        tags=_auto_tag(full_text),
        metadata={"category": category, "feature_count": len(record.features)},
    ))

    seen_labels: set[str] = set()
    for feat in record.features:
        if feat.type in SKIP_FEATURE_TYPES:
            continue

        label = _feature_label(feat)
        if not label or len(label) < 2:
            continue

        dedup_key = f"{label}_{feat.type}"
        if dedup_key in seen_labels:
            continue
        seen_labels.add(dedup_key)

        try:
            feat_seq = str(feat.extract(record.seq))
        except Exception:
            feat_seq = ""

        if not feat_seq or len(feat_seq) < 5:
            continue

        part_type = _classify_feature(feat, label)

        product = feat.qualifiers.get("product", [""])[0]
        note = feat.qualifiers.get("note", [""])[0]
        feat_desc = product or note or f"{feat.type}: {label}"

        feat_id = f"sg_{path.stem}_{label.replace(' ', '_')[:30]}"
        feat_text = f"{label} {feat_desc} {feat.type}"

        parts.append(BioPart(
            part_id=feat_id,
            name=label,
            type=part_type,
            organism=organism,
            function=feat_desc[:500],
            sequence=feat_seq,
            description=f"{feat_desc} (from {plasmid_name})"[:1000],
            references=[f"https://snapgene.com/resources/plasmid-files"],
            source_database="snapgene",
            tags=_auto_tag(feat_text),
            metadata={
                "parent_plasmid": plasmid_name,
                "feature_type": feat.type,
                "category": category,
            },
        ))

    return parts


def _find_dna_files(root: Path) -> Generator[tuple[Path, str], None, None]:
    """Walk a directory tree yielding (.dna file path, category name) tuples."""
    for dirpath, _dirnames, filenames in os.walk(root):
        category = Path(dirpath).name
        if category == root.name:
            category = "uncategorized"
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fname.lower().endswith(".dna"):
                yield fpath, category
            elif fname.lower().endswith(".zip"):
                yield from _extract_zip(fpath, category)


def _extract_zip(zip_path: Path, fallback_category: str) -> Generator[tuple[Path, str], None, None]:
    """Yield .dna files from inside a zip without extracting to disk."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.filename.lower().endswith(".dna") and not info.is_dir():
                    category = fallback_category
                    parts = Path(info.filename).parts
                    if len(parts) > 1:
                        category = parts[0]

                    tmp_dir = zip_path.parent / ".tmp_snapgene"
                    tmp_dir.mkdir(exist_ok=True)
                    extracted = Path(zf.extract(info, tmp_dir))
                    yield extracted, category
    except Exception:
        logger.warning("Could not read zip: %s", zip_path.name)


def ingest_snapgene(
    queries: list[str] | None = None,
    limit: int = 50,
) -> Generator[BioPart, None, None]:
    """
    Ingest parts from locally downloaded SnapGene .dna files.

    Args:
        queries: Ignored (included for API compatibility with other ingesters).
                 All .dna files in data/snapgene/ are processed.
        limit: Max parts to yield per .dna file (default 50; 0 = unlimited).
    """
    if not SNAPGENE_DIR.exists():
        SNAPGENE_DIR.mkdir(parents=True, exist_ok=True)
        logger.error(
            "No SnapGene data found. Download plasmid sets from "
            "https://snapgene.com/resources/plasmid-files and "
            "place the zip files or extracted .dna files in %s",
            SNAPGENE_DIR,
        )
        return

    dna_files = list(_find_dna_files(SNAPGENE_DIR))
    if not dna_files:
        logger.error(
            "No .dna or .zip files found in %s. "
            "Download plasmid sets from https://snapgene.com/resources/plasmid-files",
            SNAPGENE_DIR,
        )
        return

    logger.info("Found %d SnapGene files to process", len(dna_files))

    total = 0
    seen_ids: set[str] = set()

    for fpath, category in dna_files:
        try:
            parts = _parse_dna_file(fpath, category)
        except Exception:
            logger.warning("Failed to parse %s", fpath.name)
            continue

        file_count = 0
        for part in parts:
            if part.part_id in seen_ids:
                continue
            seen_ids.add(part.part_id)
            total += 1
            file_count += 1
            yield part
            if limit and file_count >= limit:
                break

    tmp = SNAPGENE_DIR / ".tmp_snapgene"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    logger.info("SnapGene ingestion complete: %d parts from %d files", total, len(dna_files))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = 0
    for p in ingest_snapgene(limit=0):
        count += 1
        print(f"{p.part_id}: {p.type.value} — {p.name} — {len(p.sequence)}bp")
    print(f"\nTotal: {count} parts")
