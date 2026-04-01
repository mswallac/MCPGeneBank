"""
Interactive demo of the Bio-Circuit AI system.

Seeds an in-memory vector store with biological parts spanning multiple
circuit types, then runs example designs:
  1. Arsenic biosensor (green fluorescence)
  2. IPTG/Tetracycline toggle switch
  3. Repressilator oscillator
  4. NOT gate (inverter)
  5. AND logic gate
  6. Kill switch
  7. 3-stage signal cascade

Usage:
    python demo.py
"""

from __future__ import annotations

import json
import logging

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from circuits.circuit_builder import (
    assemble,
    template_biosensor,
    template_cascade,
    template_kill_switch,
    template_logic_and,
    template_logic_not,
    template_repressilator,
    template_toggle_switch,
)
from database.vector_store import get_vector_store
from models.part import BioPart, CircuitDesign, CircuitSpec

console = Console()
logger = logging.getLogger(__name__)

# -- Seed data (broad catalog for many circuit types) ─────────────────

SEED_PARTS: list[dict] = [
    # --- Promoters ---
    {
        "part_id": "BBa_J23100", "name": "Constitutive Promoter J23100", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Strong constitutive promoter from the Anderson library",
        "sequence": "TTGACGGCTAGCTCAGTCCTAGGTACAGTGCTAGC",
        "description": "Constitutive promoter, strongest in the Anderson collection",
        "references": ["https://parts.igem.org/Part:BBa_J23100"],
        "source_database": "igem", "tags": ["constitutive", "strong", "promoter"],
    },
    {
        "part_id": "BBa_K1031907", "name": "Pars Arsenic Sensing Promoter", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Promoter responsive to arsenite ions, repressed by ArsR in the absence of arsenic",
        "sequence": "TTGACAAAAAATGGCATCCATTGTCATAAATTTCTTTAATCTTGTTCAACAAAATCGATTTTTCCCCTAACACTTGATACTGTATTACAGAA",
        "description": "Arsenic-responsive promoter from the ars operon.",
        "references": ["https://parts.igem.org/Part:BBa_K1031907"],
        "source_database": "igem", "tags": ["arsenic", "metal sensing", "biosensor", "promoter"],
    },
    {
        "part_id": "BBa_R0010", "name": "PLlac/ara Promoter", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "IPTG-inducible promoter from the lac operon. Repressed by LacI, induced by IPTG.",
        "sequence": "CAATACGCAAACCGCCTCTCCCCGCGCGTTGGCCGATTCATTAATGCAGCTGGCACGACAGGTTTCCCGACTGGAAAGCGGGCAGTGAGCGCAACGCAATTAATGTGAGTTAGCTCACTCATTAGGCACCCCAGGCTTTACACTTTATGCTTCCGGCTCGTATGTTGTGTGG",
        "description": "Lac promoter. LacI repressor binds in absence of IPTG; IPTG releases LacI.",
        "references": ["https://parts.igem.org/Part:BBa_R0010"],
        "source_database": "igem", "tags": ["IPTG", "lac", "inducible", "promoter"],
    },
    {
        "part_id": "BBa_R0040", "name": "PLtet Promoter", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Tetracycline-inducible promoter. Repressed by TetR; tetracycline or aTc releases TetR.",
        "sequence": "TCCCTATCAGTGATAGAGATTGACATCCCTATCAGTGATAGAGATACTGAGCAC",
        "description": "Tet-responsive promoter from Tn10.",
        "references": ["https://parts.igem.org/Part:BBa_R0040"],
        "source_database": "igem", "tags": ["tetracycline", "aTc", "inducible", "promoter"],
    },
    {
        "part_id": "BBa_R0011", "name": "PLlacIq Promoter", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Hybrid lac/tet promoter. Repressed by LacI, induced by IPTG.",
        "sequence": "AATTGTGAGCGGATAACAATTGACATTGTGAGCGGATAACAAGATACTGAGCACATCAGCAGGACGCACTGACC",
        "description": "Regulated by LacI. Strong output when IPTG is present.",
        "references": ["https://parts.igem.org/Part:BBa_R0011"],
        "source_database": "igem", "tags": ["IPTG", "lac", "regulated", "promoter"],
    },
    {
        "part_id": "BBa_K346001", "name": "Pmer Mercury Sensing Promoter", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Mercury-inducible promoter from the mer operon. Activated by MerR in the presence of Hg(II).",
        "sequence": "TCCGTACAATCTGCTAGCTTAACTCAATAAAACTTTGTTCCTGATAGAGT",
        "description": "Promoter activated by MerR regulator when mercury ions are present.",
        "references": ["https://parts.igem.org/Part:BBa_K346001"],
        "source_database": "igem", "tags": ["mercury", "metal sensing", "biosensor", "promoter"],
    },
    {
        "part_id": "BBa_J45992", "name": "PcopA Copper Responsive Promoter", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Copper-inducible promoter activated by CueR regulator.",
        "sequence": "TTGACCTTGCCGAATCTTGCCCGGATCGGCTTAAAAATCAGTCTGACTCTATCATTGATAGAGTTATTTTACCACTCCCTATCAGTGATAGAGAAAAGTGA",
        "description": "Promoter responsive to copper ions via CueR activation.",
        "references": ["https://parts.igem.org/Part:BBa_J45992"],
        "source_database": "igem", "tags": ["copper", "metal sensing", "biosensor", "promoter"],
    },
    {
        "part_id": "BBa_I14032", "name": "PBAD Arabinose Promoter", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Arabinose-inducible promoter. Activated by AraC in the presence of arabinose.",
        "sequence": "AAGAAACCAATTGTCCATATTGCATCAGACATTGCCGTCACTGCGTCTTTTACTGGCTCTTCTCGCTAACCAAACCGGTAACCCCGCTTATTAAAAGCATTCTGTAACAAAGCGGGACCAAAGCCATGACAAAAACGCGTAACAAAAGTGTCTATAATCACGGCAGAAAAGTCCACATTGATTATTTGCACGGCGTCACACTTTGCTATGCCATAGCATTTTTATCCATAAGATTAGCGGATCCTACCTGACGCTTTTTATCGCAACTCTCTACTGTTTCTCCATA",
        "description": "AraC/PBAD system for arabinose-inducible gene expression.",
        "references": ["https://parts.igem.org/Part:BBa_I14032"],
        "source_database": "igem", "tags": ["arabinose", "inducible", "promoter", "AraC"],
    },
    {
        "part_id": "BBa_R0062", "name": "PLux Promoter (Quorum Sensing)", "type": "promoter",
        "organism": "Escherichia coli",
        "function": "Promoter activated by LuxR-AHL complex. Quorum sensing responsive.",
        "sequence": "ACCTGTAGGATCGTACAGGTTTACGCAAGAAAATGGTTTGTTATAGTCGAATAAA",
        "description": "LuxR/AHL-activated promoter from V. fischeri quorum sensing system.",
        "references": ["https://parts.igem.org/Part:BBa_R0062"],
        "source_database": "igem", "tags": ["quorum sensing", "AHL", "LuxR", "promoter"],
    },
    # --- Regulators ---
    {
        "part_id": "BBa_C0012", "name": "LacI Repressor", "type": "regulator",
        "organism": "Escherichia coli",
        "function": "Lac repressor protein. Binds lac operator and represses transcription. IPTG releases LacI.",
        "sequence": "ATGGTGAATGTGAAACCAGTAACGTTATACGATGTCGCAGAGTATGCCGGTGTCTCTTATCAGACCGTTTCCCGCGTGGTGAACCAGGCCAGCCACGTTTCTGCGAAAACGCGGGAAAAAGTGGAAGCGGCGATGGCGGAGCTGAATTACATTCCCAACCGCGTGGCACAACAACTGGCGGGCAAACAGTCGTTGCTGATTGGCGTTGCCACCTCCAGTCTGGCCCTGCACGCGCCGTCGCAAATTGTCGCGGCGATTAAATCTCGCGCCGATCAACTGGGTGCCAGCGTGGTGGTGTCGATGGTAGAACGAAGCGGCGTCGAAGCCTGTAAAGCGGCGGTGCACAATCTTCTCGCGCAACGCGTCAGTGGGCTGATCATTAACTATCCGCTGGATGACCAGGATGCCATTGCTGTGGAAGCTGCCTGCACTAATGTTCCGGCGTTATTTCTTGATGTCTCTGACCAGACACCCATCAACAGTATTATTTTCTCCCATGAAGACGGTACGCGACTGGGCGTGGAGCATCTGGTCGCATTGGGTCACCAGCAAATCGCGCTGTTAGCGGGCCCATTAAGTTCTGTCTCGGCGCGTCTGCGTCTGGCTGGCTGGCATAAATATCTCACTCGCAATCAAATTCAGCCGATAGCGGAACGGGAAGGCGACTGGAGTGCCATGTCCGGTTTTCAACAAACCATGCAAATGCTGAATGAGGGCATCGTTCCCACTGCGATGCTGGTTGCCAACGATCAGATGGCGCTGGGCGCAATGCGCGCCATTACCGAGTCCGGGCTGCGCGTTGGTGCGGATATCTCGGTAGTGGGATACGACGATACCGAAGACAGCTCATGTTATATCCCGCCGTCAACCACCATCAAACAGGATTTTCGCCTGCTGGGGCAAACCAGCGTGGACCGCTTGCTGCAACTCTCTCAGGGCCAGGCGGTGAAGGGCAATCAGCTGTTGCCCGTCTCACTGGTGAAAAGAAAAACCACCCTGGCGCCCAATACGCAAACCGCCTCTCCCCGCGCGTTGGCCGATTCATTAATGCAGCTGGCACGACAGGTTTCCCGACTGGAAAGCGGGCAGTGA",
        "description": "LacI repressor. Core component of the lac regulatory system and toggle switches.",
        "references": ["https://parts.igem.org/Part:BBa_C0012"],
        "source_database": "igem", "tags": ["LacI", "repressor", "IPTG", "toggle switch"],
    },
    {
        "part_id": "BBa_C0040", "name": "TetR Repressor", "type": "regulator",
        "organism": "Escherichia coli",
        "function": "Tet repressor. Binds tet operator and represses PLtet. Released by tetracycline/aTc.",
        "sequence": "ATGTCTAGATTAGATAAAAGTAAAGTGATTAACAGCGCATTAGAGCTGCTTAATGAGGTCGGAATCGAAGGTTTAACAACCCGTAAACTCGCCCAGAAGCTAGGTGTAGAGCAGCCTACATTGTATTGGCATGTAAAAAATAAGCGGGCTTTGCTCGACGCCTTAGCCATTGAGATGTTAGATAGGCACCATACTCACTTTTGCCCTTTAGAAGGGGAAAGCTGGCAAGATTTTTTACGTAATAACGCTAAAAGTTTTAGATGTGCTTTACTAAGTCATCGCGATGGAGCAAAAGTACATTTAGGTACACGGCCTACAGAAAAACAGTATGAAACTCTCGAAAATCAATTAGCCTTTTTATGCCAACAAGGTTTTTCACTAGAGAATGCATTATATGCACTCAGCGCTGTGGGGCATTTTACTTTAGGTTGCGTATTGGAAGATCAAGAGCATCAAGTCGCTAAAGAAGAAAGGGAAACACCTACTACTGATAGTATGCCGCCATTATTACGACAAGCTATCGAATTATTTGATCACCAAGGTGCAGAGCCAGCCTTCTTATTCGGCCTTGAATTGATCATATGCGGATTAGAAAAACAACTTAAATGTGAAAGTGGGTCTTAA",
        "description": "TetR repressor. Paired with PLtet for tetracycline-inducible systems and toggle switches.",
        "references": ["https://parts.igem.org/Part:BBa_C0040"],
        "source_database": "igem", "tags": ["TetR", "repressor", "tetracycline", "toggle switch"],
    },
    {
        "part_id": "BBa_C0062", "name": "LuxR Activator (Quorum Sensing)", "type": "regulator",
        "organism": "Vibrio fischeri",
        "function": "LuxR transcription factor. Binds AHL and activates PLux promoter. Quorum sensing activator.",
        "sequence": "ATGAAAAACATAAATGCCGACGACACATACAGAATAATTAATAAAATTAAAGCTTGTAGAAGCAATAATGATATTAATCAATGCTTATCTGATATGACTAAAATGGTACATTGTGAATATTATTTACTCGCGATCATTTATCCTCATTCTATGGTTAAATCTGATATTTCAATCCTAGATAATTACCCTAAAAAATGGAGGCAATATTATGATGACGCTAATTTAATAAAATATGATCCTATAGTAGATTATTCTAACTCCAATCATTCACCAATTAATTGGAATATATTTGAAAACAATGCTGTAAATAAAAAATCTCCAAATGTAATTAAAGAAGCGAAAACATCAGGTCTTATCACTGGGTTTAGTTTCCCTATTCATACGGCTAACAATGGCTTCGGAATGCTTAGTTTTGCACATTCAGAAAAAGACAACTATATAGATAGTTTATTTTTACATGCGTGTATGAACATACCATTAATTGTTCCTTCTCTAGTTGATAATTATCGAAAAATAAATATAGCAAATAATAAATCAAACAACGATTTAACCAAAAGAGAAAAAGAATGTTTAGCGTGGGCATGCGAAGGAAAAAGCTCTTGGGATATTTCAAAAATATTAGGTTGCAGTGAGCGTACTGTCACTTTCCATTTAACCAATGCGCAAATGAAACTCAATACAACAAACCGCTGCCAAAGTATTTCTAAAGCAATTTTAACAGGAGCAATTGATTGCCCATACTTTAAAAATTAATAACACTGATAGTGCTATAGT",
        "description": "LuxR. Quorum sensing TF used in cell-cell communication circuits.",
        "references": ["https://parts.igem.org/Part:BBa_C0062"],
        "source_database": "igem", "tags": ["LuxR", "quorum sensing", "AHL", "activator"],
    },
    {
        "part_id": "BBa_K1031311", "name": "ArsR Transcription Factor", "type": "regulator",
        "organism": "Escherichia coli",
        "function": "Arsenic-responsive transcriptional repressor. Dissociates from Pars in the presence of arsenite.",
        "sequence": "ATGAATATCAACATTTCCGTGAATTTAGCCGCCGAAATCAGCCTGTTCTCCCCGGAACAGGTAATGGGCCTCGGCAGTGTGCTTGCCGCAATCAAAGAGTTTGGCATCACCCACTGGAGCAGCGACTACACCCACATGCTGAGATCTTCCCGCAGACTGGCGTGCCGCCAGCTTCGCTGTCACGTTTCGTCTGTGAAGTGCACCATAACCCGCAACTGA",
        "description": "ArsR repressor from E. coli ars operon. Senses arsenic.",
        "references": ["https://parts.igem.org/Part:BBa_K1031311"],
        "source_database": "igem", "tags": ["arsenic", "metal sensing", "repressor", "transcription factor"],
    },
    {
        "part_id": "BBa_K346002", "name": "MerR Mercury Sensing Regulator", "type": "regulator",
        "organism": "Escherichia coli",
        "function": "Mercury-responsive transcriptional regulator. Activates Pmer upon binding Hg(II).",
        "sequence": "", "description": "MerR from the mer operon.",
        "references": ["https://parts.igem.org/Part:BBa_K346002"],
        "source_database": "igem", "tags": ["mercury", "metal sensing", "transcription factor"],
    },
    {
        "part_id": "P15905", "name": "CueR Copper Sensing Regulator", "type": "regulator",
        "organism": "Escherichia coli",
        "function": "Copper-responsive transcriptional activator. Activates copA promoter.",
        "sequence": "", "description": "MerR-family regulator that senses copper.",
        "references": ["https://www.uniprot.org/uniprot/P15905"],
        "source_database": "uniprot", "tags": ["copper", "metal sensing", "transcription factor"],
    },
    {
        "part_id": "BBa_C0051", "name": "Lambda cI Repressor", "type": "regulator",
        "organism": "Enterobacteria phage lambda",
        "function": "Lambda phage cI repressor. Represses PR and PL promoters. Key component of repressilators.",
        "sequence": "ATGAGCACAAAAAAGAAACCATTAACACAAGAGCAGCTTGAGGACGCACGTCGCCTTAAAGCAATTTATGAAAAAAAGAAAAATGAACTTGGCTTATCCCAGGAATCTGTCGCAGACAAGATGGGGATGGGGCAGTCAGGCGTTGGTGCTTTATTTAATGGCATCAATGCATTAAATGCTTATAACGCCGCATTGCTTGCAAAAATTCTCAAAGTTAGCGTTGAAGAATTTAGCCCTTCAATCGCCAGAGAAATCTACGAGATGTATGAAGCGGTTAGTATGCAGCCGTCACTTAGAAGTGAGTATGAGTACCCTGTTTTTTCTCATGTTCAGGCAGGGATGTTCTCACCTGAGCTTAGAACCTTTACCAAAGGTGATGCGGAGAGATGGGTAAGCACAACCAAAAAAGCCAGTGATTCTGCATTCTGGCTTGAGGTTGAAGGTAATTCCATGACCGCACCAACAGGCTCCAAGCCAAGCTTTCCTGACGGAATGTTAATTCTCGTTGACCCTGAGCAGGCTGTTGAGCCAGGTGATTTCTGCATAGCCAGACTTGGGGGTGATGAGTTTACCTTCAAGAAACTGATCAGGGATAGCGGTCAGGTGTTTTTACAACCACTAAACCCACAGTACCCAATGATCCCATGCAATGAGAGTTGTTCCGTTGTGGGGAAAGTTATCGCTAGTCAGTGGCCTGAAGAGACGTTTGGCTAA",
        "description": "Lambda cI. Used in repressilators and genetic switches.",
        "references": ["https://parts.igem.org/Part:BBa_C0051"],
        "source_database": "igem", "tags": ["lambda", "cI", "repressor", "repressilator", "phage"],
    },
    # --- Reporters ---
    {
        "part_id": "BBa_E0040", "name": "GFP (Green Fluorescent Protein)", "type": "reporter",
        "organism": "Aequorea victoria",
        "function": "Green fluorescent protein. Emits at 509 nm.",
        "sequence": "ATGCGTAAAGGAGAAGAACTTTTCACTGGAGTTGTCCCAATTCTTGTTGAATTAGATGGTGATGTTAATGGGCACAAATTTTCTGTCAGTGGAGAGGGTGAAGGTGATGCAACATACGGAAAACTTACCCTTAAATTTATTTGCACTACTGGAAAACTACCTGTTCCATGGCCAACACTTGTCACTACTTTCGGTTATGGTGTTCAATGCTTTGCGAGATACCCAGATCATATGAAACAGCATGACTTTTTCAAGAGTGCCATGCCCGAAGGTTATGTACAGGAAAGAACTATATTTTTCAAAGATGACGGGAACTACAAGACACGTGCTGAAGTCAAGTTTGAAGGTGATACCCTTGTTAATAGAATCGAGTTAAAAGGTATTGATTTTAAAGAAGATGGAAACATTCTTGGACACAAATTGGAATACAACTATAACTCACACAATGTATACATCATGGCAGACAAACAAAAGAATGGAATCAAAGTTAACTTCAAAATTAGACACAACATTGAAGATGGAAGCGTTCAACTAGCAGACCATTATCAACAAAATACTCCAATTGGCGATGGCCCTGTCCTTTTACCAGACAACCATTACCTGTCCACACAATCTGCCCTTTCGAAAGATCCCAACGAAAAGAGAGACCACATGGTCCTTCTTGAGTTTGTAACAGCTGCTGGGATTACACATGGCATGGATGAACTATACAAATAA",
        "description": "GFP reporter for gene expression visualization.",
        "references": ["https://parts.igem.org/Part:BBa_E0040"],
        "source_database": "igem", "tags": ["GFP", "fluorescence", "green", "reporter"],
    },
    {
        "part_id": "BBa_E1010", "name": "mRFP1 (Red Fluorescent Protein)", "type": "reporter",
        "organism": "Discosoma sp.",
        "function": "Monomeric red fluorescent protein. Emits at 607 nm.",
        "sequence": "ATGGCTTCCTCCGAAGATGTTATCAAAGAGTTCATGCGTTTCAAAGTTCGTATGGAAGGTTCCGTTAACGGTCACGAGTTCGAAATCGAAGGTGAAGGTGAAGGTCGTCCGTACGAAGGTACCCAGACCGCTAAACTGAAAGTTACCAAAGGTGGTCCGCTGCCGTTCGCTTGGGACATCCTGTCCCCGCAGTTCCAGTACGGTTCCAAAGCTTACGTTAAACACCCGGCTGACATCCCGGACTACCTGAAACTGTCCTTCCCGGAAGGTTTCAAATGGGAACGTGTTATGAACTTCGAAGATGGTGGTGTTGTTACCGTTACCCAGGACTCCTCCCTGCAAGACGGTGAGTTCATCTACAAAGTTAAACTGCGTGGTACCAACTTCCCGTCCGACGGTCCGGTTATGCAGAAAAAAACCATGGGTTGGGAAGCTTCCACCGAACGTATGTACCCGGAAGATGGTGCTCTGAAAGGTGAAATCAAAATGCGTCTGAAACTGAAAGACGGTGGTCACTACGACGCTGAAGTTAAAACCACCTACATGGCTAAAAAACCGGTTCAGCTGCCGGGTGCTTACAAAACCGACATCAAACTGGACATCACCTCCCACAACGAAGACTACACCATCGTTGAACAGTACGAACGTGCTGAAGGTCGTCACTCCACCGGTGCTTAA",
        "description": "Monomeric RFP1 red fluorescent reporter.",
        "references": ["https://parts.igem.org/Part:BBa_E1010"],
        "source_database": "igem", "tags": ["RFP", "fluorescence", "red", "reporter"],
    },
    {
        "part_id": "BBa_K525998", "name": "Firefly Luciferase Reporter", "type": "reporter",
        "organism": "Photinus pyralis",
        "function": "Bioluminescent reporter producing light via luciferin oxidation.",
        "sequence": "", "description": "Firefly luciferase for bioluminescence-based reporting.",
        "references": ["https://parts.igem.org/Part:BBa_K525998"],
        "source_database": "igem", "tags": ["luciferase", "luminescence", "reporter"],
    },
    # --- RBS + Terminators ---
    {
        "part_id": "BBa_B0034", "name": "RBS B0034", "type": "rbs",
        "organism": "Escherichia coli",
        "function": "Medium-strength ribosome binding site.",
        "sequence": "AAAGAGGAGAAA", "description": "Standard medium-strength RBS.",
        "references": ["https://parts.igem.org/Part:BBa_B0034"],
        "source_database": "igem", "tags": ["RBS", "translation"],
    },
    {
        "part_id": "BBa_B0015", "name": "Double Terminator B0015", "type": "terminator",
        "organism": "Escherichia coli",
        "function": "Double transcription terminator (BBa_B0010 + BBa_B0012).",
        "sequence": "CCAGGCATCAAATAAAACGAAAGGCTCAGTCGAAAGACTGGGCCTTTCGTTTTATCTGTTGTTTGTCGGTGAACGCTCTCTACTAGAGTCACACTGGCTCACCTTCGGGTGGGCCTTTCTGCGTTTATA",
        "description": "High-efficiency double transcription terminator.",
        "references": ["https://parts.igem.org/Part:BBa_B0015"],
        "source_database": "igem", "tags": ["terminator", "transcription"],
    },
    # --- Coding / Toxin-Antitoxin ---
    {
        "part_id": "BBa_K1060002", "name": "CcdB Toxin", "type": "coding",
        "organism": "Escherichia coli",
        "function": "CcdB toxin protein. Inhibits DNA gyrase causing cell death. Used in kill switches.",
        "sequence": "ATGCAGTTTAAGGTTTACACCTATAAAAGAGAGAGCCGTTATCGTCTGTTTGTGGATGTACAGAGTGATATTATTGACACGCCCGGGCGACGGATGGTGATCCCCCTGGCCAGTGCACGTCTGCTGTCAGATAAAGTCTCCCGTGAACTTTACCCGGTGGTGCATATCGGGGATGAAAGCTGGCGCATGATGACCACCGATATGGCCAGTGTGCCGGTCTCCGTTATCGGGGAAGAAGTGGCTGATCTCAGCCACCGCGAAAATGACATCAAAAACGCCATTAACCTGATGTTCTGGGGAATATAA",
        "description": "CcdB toxin. Part of the CcdA/CcdB toxin-antitoxin system for kill switches.",
        "references": ["https://parts.igem.org/Part:BBa_K1060002"],
        "source_database": "igem", "tags": ["toxin", "CcdB", "kill switch", "cell death"],
    },
    {
        "part_id": "BBa_K1060001", "name": "CcdA Antitoxin", "type": "coding",
        "organism": "Escherichia coli",
        "function": "CcdA antitoxin protein. Neutralizes CcdB toxin to prevent cell death under normal conditions.",
        "sequence": "ATGAAGCAGCGTATTACAGTGACAGTTGACAGCGACAGCTATCAGTTGCTCAAGGCATATATGATGTCAATATCTCCGGTCTGGTAAGCACAACCATGCAGAATGAAGCCCGTCGTCTGCGTGCCGAACGCTGGAAAGCGGAAAATCAGGAAGGGATGGCTGAGGTCGCCCGGTTTATTGAAATGAACGGCTCTTTTGCTGACGAGAACAGGGACTGGTGAAATGCAGTTTAAGGTTTACACCTATAAAAGAGAG",
        "description": "CcdA antitoxin. Paired with CcdB for controllable cell death.",
        "references": ["https://parts.igem.org/Part:BBa_K1060001"],
        "source_database": "igem", "tags": ["antitoxin", "CcdA", "kill switch", "safety"],
    },
]


def seed_vector_store() -> int:
    store = get_vector_store(in_memory=True)
    parts = [BioPart(**d) for d in SEED_PARTS]
    count = store.upsert_parts(parts)
    return count


def run_demo(title: str, spec: CircuitSpec) -> None:
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]"))
    console.print(f"  Pattern  : [yellow]{spec.pattern.value}[/yellow]")
    console.print(f"  Organism : [yellow]{spec.organism}[/yellow]")
    console.print(f"  Nodes    : [yellow]{len(spec.nodes)}[/yellow]   Edges: [yellow]{len(spec.edges)}[/yellow]")
    console.print(f"  {spec.description}")
    console.print()

    circuit = assemble(spec)

    console.print(f"[bold green]Circuit: {circuit.circuit_name}[/bold green]")
    console.print(f"Pattern: {circuit.pattern.value}\n")

    for tu in circuit.transcription_units:
        parts_str = " -> ".join(f"{c.part.name}" for c in tu.components)
        console.print(f"  [bold]TU [{tu.unit_id}][/bold]:  {parts_str}")

    console.print()
    if circuit.edges:
        console.print("  [bold]Regulatory wiring:[/bold]")
        for e in circuit.edges:
            console.print(f"    {e.source} --[{e.interaction}]--> {e.target}")
        console.print()

    console.print(f"  Total sequence: {len(circuit.sequence)} bp")
    if circuit.sequence:
        preview = circuit.sequence[:60] + "..." if len(circuit.sequence) > 60 else circuit.sequence
        console.print(f"  Preview: [dim]{preview}[/dim]")

    console.print()
    console.print(Markdown(circuit.explanation))

    console.print("\n[dim]" + "-" * 70 + "[/dim]\n")

    summary = circuit.to_summary()
    console.print("[bold]JSON output:[/bold]")
    console.print(json.dumps(summary, indent=2))
    console.print("\n" + "=" * 70 + "\n")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    console.print(Panel("[bold magenta]Bio-Circuit AI -- General-Purpose Circuit Designer[/bold magenta]", expand=False))
    console.print()

    count = seed_vector_store()
    console.print(f"Seeded vector store with [bold]{count}[/bold] biological parts.\n")
    console.print(f"Supported patterns: biosensor, toggle_switch, repressilator, logic_and,")
    console.print(f"  logic_not, kill_switch, cascade, metabolic_pathway, and fully custom.\n")
    console.print("=" * 70 + "\n")

    # 1. Classic biosensor
    run_demo(
        "1. Arsenic Biosensor (green fluorescence)",
        template_biosensor("arsenic", "green fluorescence"),
    )

    # 2. Toggle switch
    run_demo(
        "2. IPTG / Tetracycline Toggle Switch",
        template_toggle_switch("IPTG", "tetracycline", "GFP", "RFP"),
    )

    # 3. Repressilator
    run_demo(
        "3. Repressilator Oscillator",
        template_repressilator(),
    )

    # 4. NOT gate
    run_demo(
        "4. NOT Gate (IPTG inverter)",
        template_logic_not("IPTG", "GFP"),
    )

    # 5. AND gate
    run_demo(
        "5. AND Gate (arabinose + IPTG -> GFP)",
        template_logic_and("arabinose", "IPTG", "GFP"),
    )

    # 6. Kill switch
    run_demo(
        "6. Arabinose-Activated Kill Switch",
        template_kill_switch("arabinose"),
    )

    # 7. Signal cascade
    run_demo(
        "7. 3-Stage IPTG Signal Cascade",
        template_cascade(stages=3, input_signal="IPTG", output="GFP"),
    )

    console.print("[bold green]Demo complete! 7 circuit types assembled.[/bold green]")
    console.print(
        "\nTo design any circuit via natural language:\n"
        "  [cyan]curl -X POST http://localhost:8000/design "
        '-d \'{"prompt": "Build a toggle switch with IPTG and arabinose"}\'[/cyan]\n'
    )
    console.print(
        "To use templates programmatically:\n"
        "  [cyan]curl -X POST http://localhost:8000/design/template "
        '-d \'{"template": "repressilator"}\'[/cyan]\n'
    )


if __name__ == "__main__":
    main()
