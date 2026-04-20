"""
Generate three genetic circuit designs for BE552 HW2.

Each circuit uses real iGEM parts from the seed vector store. Output includes:
- Full part lists with sequences and iGEM registry links
- Transcription unit organization
- Suggested DAMP Lab Canvas operations (assembly method, transformation, assay)
- JSON export for each design

Three circuits (distinct patterns for three DAMP Lab Canvas workflow variations):
  1. Arsenic Biosensor      — simple sensor → reporter (Gibson Assembly)
  2. IPTG/Tet Toggle Switch — bistable two-module circuit (Golden Gate / MoClo)
  3. NOT Gate (inverter)     — IPTG-inverting logic gate (Gibson Assembly, different assay)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from demo import SEED_PARTS, seed_vector_store
from circuits.circuit_builder import (
    assemble,
    template_biosensor,
    template_toggle_switch,
    template_logic_not,
)
from models.part import BioPart, CircuitDesign


# ── Helpers ────────────────────────────────────────────────────────────


def circuit_to_full_report(design: CircuitDesign, workflow_info: dict) -> dict:
    """Build a comprehensive report dict for one circuit."""
    parts_table = []
    for tu in design.transcription_units:
        for comp in tu.components:
            p = comp.part
            parts_table.append({
                "transcription_unit": tu.unit_id,
                "role": comp.role,
                "part_id": p.part_id,
                "part_name": p.name,
                "type": p.type.value,
                "organism": p.organism,
                "function": p.function,
                "sequence_length_bp": len(p.sequence),
                "sequence_preview": (p.sequence[:40] + "...") if len(p.sequence) > 40 else p.sequence,
                "full_sequence": p.sequence,
                "source": p.source_database,
                "registry_url": p.references[0] if p.references else "",
            })

    tu_summaries = []
    for tu in design.transcription_units:
        tu_summaries.append({
            "unit_id": tu.unit_id,
            "architecture": " → ".join(
                f"{c.part.name} ({c.role})" for c in tu.components
            ),
            "total_bp": len(tu.sequence),
            "sequence": tu.sequence,
        })

    return {
        "circuit_name": design.circuit_name,
        "pattern": design.pattern.value,
        "total_sequence_bp": len(design.sequence),
        "num_transcription_units": len(design.transcription_units),
        "num_parts": len(parts_table),
        "parts": parts_table,
        "transcription_units": tu_summaries,
        "regulatory_edges": [
            {"source": e.source, "target": e.target, "interaction": e.interaction}
            for e in design.edges
        ],
        "full_sequence": design.sequence,
        "explanation": design.explanation,
        "references": design.references,
        "damp_lab_workflow": workflow_info,
    }


def print_circuit_summary(report: dict, idx: int) -> None:
    """Pretty-print a circuit summary to stdout."""
    wf = report["damp_lab_workflow"]
    print(f"\n{'='*72}")
    print(f"  CIRCUIT {idx}: {report['circuit_name']}")
    print(f"  Pattern: {report['pattern']}   |   Total: {report['total_sequence_bp']} bp")
    print(f"  TUs: {report['num_transcription_units']}   |   Parts: {report['num_parts']}")
    print(f"{'='*72}")

    print(f"\n  Parts List:")
    print(f"  {'Role':<14} {'Part ID':<16} {'Name':<40} {'bp':>6}")
    print(f"  {'-'*14} {'-'*16} {'-'*40} {'-'*6}")
    for p in report["parts"]:
        print(f"  {p['role']:<14} {p['part_id']:<16} {p['part_name']:<40} {p['sequence_length_bp']:>6}")

    print(f"\n  Transcription Units:")
    for tu in report["transcription_units"]:
        print(f"    [{tu['unit_id']}] ({tu['total_bp']} bp)")
        print(f"      {tu['architecture']}")

    print(f"\n  Regulatory Wiring:")
    for e in report["regulatory_edges"]:
        print(f"    {e['source']} --[{e['interaction']}]--> {e['target']}")

    print(f"\n  DAMP Lab Canvas Workflow:")
    print(f"    Assembly method : {wf['assembly_method']}")
    print(f"    Host organism   : {wf['host_organism']}")
    print(f"    Backbone vector : {wf['backbone_vector']}")
    print(f"    Operations:")
    for i, op in enumerate(wf["operations"], 1):
        print(f"      {i}. {op['operation']}")
        for k, v in op.items():
            if k != "operation":
                print(f"           {k}: {v}")
    print()


# ── Main ──────────────────────────────────────────────────────────────


def main() -> None:
    print("Seeding vector store with iGEM parts...")
    count = seed_vector_store()
    print(f"  -> {count} parts loaded\n")

    output_dir = Path("hw2_output")
    output_dir.mkdir(exist_ok=True)

    # ── Circuit 1: Arsenic Biosensor ──────────────────────────────────
    spec1 = template_biosensor("arsenic", "green fluorescence")
    design1 = assemble(spec1)
    workflow1 = {
        "assembly_method": "Gibson Assembly",
        "host_organism": "Escherichia coli DH5α",
        "backbone_vector": "pSB1C3 (high-copy, chloramphenicol resistance)",
        "variation_notes": "Simple 2-TU biosensor; Gibson Assembly chosen for seamless joining of 2 fragments",
        "operations": [
            {
                "operation": "PCR Amplification",
                "details": "Amplify each transcription unit with Gibson-overlap primers (20-40 bp overlaps)",
                "template_DNA": "iGEM DNA Distribution Kit plates or IDT gBlock synthesis",
                "primers": "Design 20 bp binding + 20 bp overlap per junction",
                "polymerase": "Q5 High-Fidelity DNA Polymerase (NEB)",
                "cycles": "98°C 30s → 30x(98°C 10s, 60°C 30s, 72°C 30s/kb) → 72°C 5min",
            },
            {
                "operation": "Gel Electrophoresis (QC)",
                "details": "Run PCR products on 1% agarose gel to verify correct band sizes",
                "expected_bands": "TU1 (sensor module) and TU2 (reporter module)",
            },
            {
                "operation": "PCR Cleanup / Gel Extraction",
                "details": "Monarch PCR & DNA Cleanup Kit (NEB) or gel extract if non-specific bands",
            },
            {
                "operation": "Gibson Assembly",
                "details": "Combine linearized pSB1C3 backbone + 2 TU inserts in Gibson Assembly Master Mix",
                "reagent": "NEBuilder HiFi DNA Assembly Master Mix (NEB E2621)",
                "incubation": "50°C for 60 minutes",
                "molar_ratio": "1:2 vector:insert",
            },
            {
                "operation": "Transformation",
                "details": "Heat-shock transform Gibson product into chemically competent E. coli DH5α",
                "competent_cells": "NEB 5-alpha Competent E. coli (NEB C2987)",
                "protocol": "Thaw on ice 10 min → add 2 µL assembly → ice 30 min → 42°C 30s → ice 5 min → 950 µL SOC → 37°C 1h → plate",
                "selection": "LB + chloramphenicol (25 µg/mL)",
            },
            {
                "operation": "Colony PCR Screening",
                "details": "Screen 8-12 colonies with VF2/VR primers to verify insert",
                "expected_size": f"~{design1.sequence.__len__()} bp",
            },
            {
                "operation": "Plasmid Miniprep",
                "details": "Isolate plasmid DNA from positive colonies",
                "kit": "Monarch Plasmid Miniprep Kit (NEB T1010)",
            },
            {
                "operation": "Functional Assay — Fluorescence Plate Reader",
                "details": "Induce with 0, 1, 5, 10, 50 µM sodium arsenite; measure GFP (ex485/em528) at 0, 2, 4, 6h",
                "controls": "Empty pSB1C3 (negative), constitutive GFP (positive)",
                "instrument": "BioTek Synergy plate reader",
            },
        ],
    }
    report1 = circuit_to_full_report(design1, workflow1)

    # ── Circuit 2: Toggle Switch (manually corrected part assignments) ─
    # The vector search doesn't always pair LacI with PLlac and TetR with
    # PLtet, so we build the spec with pre-assigned parts for correctness.
    from copy import deepcopy

    # Look up parts by ID from seed data
    seed_by_id = {d["part_id"]: BioPart(**d) for d in SEED_PARTS}
    lacI  = seed_by_id["BBa_C0012"]   # LacI repressor
    tetR  = seed_by_id["BBa_C0040"]   # TetR repressor
    plac  = seed_by_id["BBa_R0010"]   # PLlac promoter (IPTG-inducible)
    ptet  = seed_by_id["BBa_R0040"]   # PLtet promoter (aTc-inducible)
    gfp   = seed_by_id["BBa_E0040"]   # GFP reporter
    rfp   = seed_by_id["BBa_E1010"]   # mRFP1 reporter

    spec2 = template_toggle_switch("IPTG", "tetracycline", "GFP", "RFP")
    # Pre-assign the correct parts to each node
    node_map2 = {n.node_id: n for n in spec2.nodes}
    node_map2["promoter_a"].part = plac     # PLlac (IPTG-inducible)
    node_map2["repressor_a"].part = lacI    # LacI (represses PLlac of module B... actually)
    # Correct toggle: PLlac → TetR (blocks PLtet), PLtet → LacI (blocks PLlac)
    # Module A: PLlac drives TetR + GFP
    # Module B: PLtet drives LacI + RFP
    node_map2["promoter_a"].part = plac
    node_map2["repressor_a"].part = tetR    # TetR represses PLtet (promoter_b)
    node_map2["reporter_a"].part = gfp
    node_map2["promoter_b"].part = ptet
    node_map2["repressor_b"].part = lacI    # LacI represses PLlac (promoter_a)
    node_map2["reporter_b"].part = rfp
    design2 = assemble(spec2)
    workflow2 = {
        "assembly_method": "Golden Gate (BsaI) / MoClo",
        "host_organism": "Escherichia coli DH5α",
        "backbone_vector": "pSB1C3 or DVA level-1 destination vector",
        "variation_notes": "Multi-module toggle switch; Golden Gate chosen for scarless, ordered multi-part assembly of 6+ parts",
        "operations": [
            {
                "operation": "Part Domestication (BsaI site removal)",
                "details": "Check all parts for internal BsaI sites; remove by silent mutagenesis if found",
                "tool": "Benchling or SnapGene for in-silico BsaI scan",
            },
            {
                "operation": "PCR Amplification with BsaI-flanked Primers",
                "details": "Add BsaI recognition sites + 4-nt fusion sites to each part",
                "fusion_standard": "MoClo / PhytoBrick standard overhangs (GGAG, AATG, GCTT, etc.)",
                "polymerase": "Q5 High-Fidelity (NEB)",
            },
            {
                "operation": "Golden Gate Assembly (Level 1 — TU assembly)",
                "details": "One-pot restriction-ligation with BsaI + T4 ligase for each TU",
                "enzyme": "BsaI-HFv2 (NEB R3733)",
                "ligase": "T4 DNA Ligase (NEB M0202)",
                "protocol": "30x(37°C 2min, 16°C 5min) → 55°C 10min → 80°C 10min",
            },
            {
                "operation": "Transformation (TU plasmids)",
                "details": "Transform each TU-level assembly separately into DH5α",
                "selection": "Appropriate antibiotic for destination vector",
            },
            {
                "operation": "Level 2 Assembly (Multi-TU into single backbone)",
                "details": "Combine TU-bearing plasmids via BsmBI Golden Gate into final backbone",
                "enzyme": "BsmBI-v2 (NEB R0739)",
            },
            {
                "operation": "Transformation (Final construct)",
                "details": "Transform level-2 assembly into DH5α",
                "selection": "LB + chloramphenicol (25 µg/mL)",
            },
            {
                "operation": "Colony PCR + Sanger Sequencing",
                "details": "Screen colonies; send positives for sequencing to confirm full construct",
            },
            {
                "operation": "Plasmid Miniprep",
                "details": "Isolate verified plasmid",
                "kit": "Monarch Plasmid Miniprep Kit (NEB T1010)",
            },
            {
                "operation": "Functional Assay — Toggle Switch Bistability",
                "details": "Grow in LB; induce state A with 1 mM IPTG (expect GFP), wash, induce state B with 200 ng/mL aTc (expect RFP). Measure GFP (ex485/em528) and RFP (ex555/em607) over 8h",
                "controls": "Uninduced (both off), single-inducer controls",
                "instrument": "BioTek Synergy plate reader or flow cytometer",
            },
        ],
    }
    report2 = circuit_to_full_report(design2, workflow2)

    # ── Circuit 3: NOT Gate ───────────────────────────────────────────
    spec3 = template_logic_not("IPTG", "GFP")
    # Pre-assign correct parts for the NOT gate:
    # PLlac (IPTG-inducible) → LacI repressor → blocks constitutive J23100 → GFP
    # When IPTG present: PLlac ON → lots of LacI → represses output → GFP OFF
    # When IPTG absent: PLlac OFF → no LacI → constitutive output → GFP ON
    node_map3 = {n.node_id: n for n in spec3.nodes}
    node_map3["input_promoter"].part = plac                    # PLlac
    node_map3["inverter_repressor"].part = lacI                # LacI
    node_map3["output_promoter"].part = seed_by_id["BBa_R0011"]  # PLlacIq (repressible by LacI)
    node_map3["output_reporter"].part = gfp                    # GFP
    design3 = assemble(spec3)
    workflow3 = {
        "assembly_method": "Gibson Assembly",
        "host_organism": "Escherichia coli DH5α",
        "backbone_vector": "pSB1C3 (high-copy, chloramphenicol resistance)",
        "variation_notes": "Logic inverter; same Gibson method as Circuit 1 but different circuit topology and different assay (dose-response transfer function)",
        "operations": [
            {
                "operation": "PCR Amplification",
                "details": "Amplify TUs with Gibson-overlap primers",
                "template_DNA": "iGEM Distribution Kit or IDT gBlocks",
                "polymerase": "Q5 High-Fidelity (NEB)",
            },
            {
                "operation": "Gel Electrophoresis (QC)",
                "details": "1% agarose gel; verify PCR product sizes",
            },
            {
                "operation": "DpnI Digestion",
                "details": "Digest template DNA with DpnI (NEB R0176) 1h @ 37°C to remove original plasmid",
            },
            {
                "operation": "PCR Cleanup",
                "details": "Monarch PCR & DNA Cleanup Kit (NEB T1030)",
            },
            {
                "operation": "Gibson Assembly",
                "details": "Assemble linearized backbone + inserts",
                "reagent": "NEBuilder HiFi DNA Assembly Master Mix (NEB E2621)",
                "incubation": "50°C for 60 minutes",
            },
            {
                "operation": "Transformation",
                "details": "Heat-shock into DH5α competent cells",
                "selection": "LB + chloramphenicol (25 µg/mL)",
            },
            {
                "operation": "Colony PCR + Sequencing Verification",
                "details": "Screen colonies with VF2/VR; send positives for Sanger sequencing",
            },
            {
                "operation": "Plasmid Miniprep",
                "details": "Isolate plasmid from sequence-verified colony",
            },
            {
                "operation": "Functional Assay — Transfer Function (Dose-Response)",
                "details": "Measure GFP output across IPTG gradient: 0, 0.01, 0.1, 0.5, 1, 5, 10 mM IPTG. Expect HIGH GFP at 0 IPTG (inverter ON) and LOW GFP at high IPTG (inverter OFF). Plot transfer function curve.",
                "timepoints": "0, 2, 4, 6, 8 hours post-induction",
                "controls": "Constitutive GFP (positive max), empty vector (negative)",
                "instrument": "BioTek Synergy plate reader",
            },
        ],
    }
    report3 = circuit_to_full_report(design3, workflow3)

    # ── Print summaries ───────────────────────────────────────────────
    for idx, report in enumerate([report1, report2, report3], 1):
        print_circuit_summary(report, idx)

    # ── Save JSON outputs ─────────────────────────────────────────────
    all_reports = {
        "generated": datetime.now().isoformat(),
        "project": "BE552 HW2 — Genetic Circuit Workflow Design",
        "circuits": [report1, report2, report3],
    }

    out_file = output_dir / "hw2_circuit_designs.json"
    with open(out_file, "w") as f:
        json.dump(all_reports, f, indent=2)
    print(f"\n[OK] Full JSON saved to: {out_file}")

    # Save individual circuit files
    for idx, report in enumerate([report1, report2, report3], 1):
        fname = output_dir / f"circuit_{idx}_{report['pattern']}.json"
        with open(fname, "w") as f:
            json.dump(report, f, indent=2)
        print(f"[OK] Circuit {idx} saved to: {fname}")

    # ── Print DAMP Lab Canvas cheat sheet ─────────────────────────────
    print(f"\n{'='*72}")
    print("  DAMP LAB CANVAS CHEAT SHEET")
    print(f"{'='*72}")
    print("""
  For each circuit, create a workflow on https://canvas.damplab.org/ :

  Variation 1 (Arsenic Biosensor — Gibson Assembly):
    Operations: PCR → Gel QC → Cleanup → Gibson Assembly → Transform → Colony PCR → Miniprep → Fluorescence Assay
    Key params: pSB1C3 backbone, Cm selection, arsenite induction, GFP readout

  Variation 2 (Toggle Switch — Golden Gate / MoClo):
    Operations: Part Domestication → PCR w/ BsaI sites → Golden Gate L1 → Transform → Golden Gate L2 → Transform → Sequencing → Miniprep → Bistability Assay
    Key params: BsaI/BsmBI enzymes, IPTG + aTc inducers, GFP + RFP readout

  Variation 3 (NOT Gate — Gibson Assembly, different assay):
    Operations: PCR → Gel QC → DpnI Digest → Cleanup → Gibson Assembly → Transform → Colony PCR + Sanger → Miniprep → Dose-Response Assay
    Key params: pSB1C3 backbone, IPTG gradient, transfer function curve

  All three use different: circuit topology, assembly strategy OR assay type.
""")


if __name__ == "__main__":
    main()
