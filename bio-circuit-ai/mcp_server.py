"""
Bio-Circuit AI — MCP Server

Exposes genetic circuit design tools via the Model Context Protocol so any
MCP-compatible LLM client (Claude Desktop, Cursor, etc.) can:

  1. Search 1,200+ biological parts by natural language
  2. Look up individual parts with full sequences
  3. Design genetic circuits from descriptions
  4. Assemble circuits from predefined templates
  5. Get raw sequences for constructed circuits

Run:
    python mcp_server.py            # stdio transport (for Claude Desktop / Cursor)
    python mcp_server.py --sse      # SSE transport on port 8080

Requires data to be ingested first (run scrape_300.py).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("bio-circuit-mcp")

mcp = FastMCP(
    "Bio-Circuit AI",
    instructions=(
        "You are a synthetic biology circuit design assistant. "
        "You have access to a database of 1,200+ biological parts from iGEM, GenBank, UniProt, and Addgene. "
        "Use the tools below to search for parts, design genetic circuits, and assemble DNA constructs. "
        "When a user asks you to design a circuit, first search for relevant parts, then use the "
        "design or assembly tools to put them together. Always explain the biology behind your choices."
    ),
)


def _get_store():
    from database.vector_store import get_vector_store
    return get_vector_store()


def _format_part(p: dict, include_sequence: bool = False) -> dict:
    """Format a part dict for clean LLM consumption."""
    result = {
        "part_id": p.get("part_id", ""),
        "name": p.get("name", ""),
        "type": p.get("type", ""),
        "organism": p.get("organism", ""),
        "function": p.get("function", ""),
        "description": p.get("description", ""),
        "source": p.get("source_database", ""),
        "tags": p.get("tags", []),
        "references": p.get("references", []),
    }
    seq = p.get("sequence", "")
    result["sequence_length"] = len(seq)
    if include_sequence:
        result["sequence"] = seq
    else:
        result["sequence_preview"] = seq[:80] + ("..." if len(seq) > 80 else "")
    if "score" in p:
        result["relevance_score"] = round(p["score"], 4)
    return result


# ── Tools ─────────────────────────────────────────────────────────────


@mcp.tool()
def search_parts(
    query: str,
    part_type: str = "",
    limit: int = 10,
) -> str:
    """Search the biological parts database using natural language.

    Performs semantic search across 1,200+ parts from iGEM, GenBank, UniProt,
    and Addgene. Returns matching parts ranked by relevance.

    Args:
        query: Natural language description of what you're looking for.
               Examples: "arsenic sensing promoter", "GFP reporter",
               "tetracycline repressor", "strong constitutive promoter"
        part_type: Optional filter by part type. One of: promoter, reporter,
                   regulator, enzyme, terminator, rbs, coding, plasmid, or empty for all.
        limit: Maximum number of results (1-20, default 10).
    """
    limit = max(1, min(20, limit))
    store = _get_store()
    results = store.search(
        query=query,
        limit=limit,
        part_type=part_type if part_type else None,
    )
    parts = [_format_part(r) for r in results]
    return json.dumps({
        "query": query,
        "type_filter": part_type or "all",
        "count": len(parts),
        "parts": parts,
    }, indent=2)


@mcp.tool()
def search_parts_batch(
    queries: list[dict],
    limit: int = 5,
) -> str:
    """Run several semantic part-searches in a single MCP call.

    Designed to replace multiple sequential `search_parts` invocations when
    the caller knows all the slots it needs up-front (e.g. "I need top-K
    candidates for promoter / RBS / CDS / terminator all at once"). Each
    sub-query is executed with its own `part_type` filter and the same
    `limit`. Typical savings: one LLM->server round-trip instead of N.

    Args:
        queries: list of dicts; each dict must contain `query` (str) and
                 `part_type` (str, one of: promoter, reporter, regulator,
                 enzyme, terminator, rbs, coding, plasmid, or empty for all).
                 Optional `label` field is echoed back verbatim so the
                 caller can correlate each result set with its slot purpose
                 (e.g. "constitutive_promoter", "arsenic_sensor").
        limit: Max parts per sub-query (1-20, default 5).

    Returns:
        JSON with a `results` list — one entry per input query, each with
        the original `query`, `part_type`, `label`, and a `parts` list.
    """
    limit = max(1, min(20, limit))
    store = _get_store()
    out = []
    for q in queries:
        query = (q or {}).get("query", "") or ""
        pt = (q or {}).get("part_type", "") or ""
        label = (q or {}).get("label", "") or ""
        if not query:
            out.append({"query": query, "part_type": pt, "label": label, "count": 0, "parts": []})
            continue
        hits = store.search(query=query, limit=limit, part_type=pt if pt else None)
        out.append({
            "query": query,
            "part_type": pt or "all",
            "label": label,
            "count": len(hits),
            "parts": [_format_part(r) for r in hits],
        })
    return json.dumps({"results": out}, indent=2)


@mcp.tool()
def get_part(part_id: str) -> str:
    """Get full details for a specific biological part, including its complete DNA/protein sequence.

    Args:
        part_id: The part identifier, e.g. "BBa_E0040", "BBa_J23100", or a GenBank/UniProt accession.
    """
    store = _get_store()
    results = store.search(query=part_id, limit=20)
    for r in results:
        if r.get("part_id", "") == part_id:
            return json.dumps(_format_part(r, include_sequence=True), indent=2)
    for r in results:
        if part_id.lower() in r.get("part_id", "").lower():
            return json.dumps(_format_part(r, include_sequence=True), indent=2)
    if results:
        return json.dumps({
            "note": f"Exact match for '{part_id}' not found. Closest matches:",
            "parts": [_format_part(r, include_sequence=True) for r in results[:3]],
        }, indent=2)
    return json.dumps({"error": f"Part '{part_id}' not found in the database."})


@mcp.tool()
def list_part_types() -> str:
    """List all available part types and how many of each are in the database.

    Useful for understanding what's available before searching.
    """
    store = _get_store()
    from collections import Counter
    all_results = store.search("biological part", limit=1200, score_threshold=0.0)
    counts = Counter(r.get("type", "unknown") for r in all_results)
    return json.dumps({
        "total_parts": len(all_results),
        "types": dict(counts.most_common()),
    }, indent=2)


@mcp.tool()
def list_circuit_templates() -> str:
    """List all available pre-built genetic circuit templates.

    Each template is a well-characterized circuit architecture that can be
    customized with specific parts. Use build_from_template() to instantiate one.
    """
    from circuits.circuit_builder import TEMPLATE_REGISTRY
    import inspect

    templates = {}
    for name, fn in TEMPLATE_REGISTRY.items():
        sig = inspect.signature(fn)
        params = {
            k: str(v.default) if v.default is not inspect.Parameter.empty else "required"
            for k, v in sig.parameters.items()
        }
        doc = fn.__doc__ or ""
        spec = fn.__wrapped__() if hasattr(fn, "__wrapped__") else None
        templates[name] = {
            "parameters": params,
            "description": doc.strip() if doc else f"Template for {name.replace('_', ' ')} circuit",
        }

    descriptions = {
        "biosensor": "Detects a target molecule and produces a visible output (e.g., arsenic -> GFP)",
        "toggle_switch": "Bistable switch between two states controlled by two inducers",
        "repressilator": "Three-gene oscillator that produces periodic pulses",
        "logic_not": "Inverter gate — output is ON when input is absent",
        "logic_and": "AND gate — output only ON when BOTH inputs are present",
        "kill_switch": "Safety circuit — triggers cell death under specific conditions",
        "metabolic_pathway": "Multi-enzyme pathway converting a substrate to a product",
        "cascade": "Multi-stage signal amplification cascade",
    }
    for name, desc in descriptions.items():
        if name in templates:
            templates[name]["description"] = desc

    return json.dumps({"templates": templates}, indent=2)


@mcp.tool()
def build_from_template(
    template_name: str,
    parameters: dict[str, Any] | None = None,
) -> str:
    """Build a genetic circuit from a predefined template.

    Uses the circuit template library and fills each slot with the best matching
    biological part from the database.

    Args:
        template_name: Name of the template (see list_circuit_templates).
                       One of: biosensor, toggle_switch, repressilator, logic_not,
                       logic_and, kill_switch, metabolic_pathway, cascade.
        parameters: Template-specific parameters as a dict. Examples:
                    biosensor: {"target": "arsenic", "output": "GFP"}
                    toggle_switch: {"inducer_a": "IPTG", "inducer_b": "tetracycline"}
                    logic_not: {"input_signal": "IPTG", "output": "GFP"}
                    cascade: {"stages": 3, "input_signal": "IPTG"}
    """
    from circuits.circuit_builder import TEMPLATE_REGISTRY, assemble

    if template_name not in TEMPLATE_REGISTRY:
        return json.dumps({
            "error": f"Unknown template '{template_name}'",
            "available": list(TEMPLATE_REGISTRY.keys()),
        })

    params = parameters or {}
    try:
        spec = TEMPLATE_REGISTRY[template_name](**params)
    except TypeError as e:
        return json.dumps({"error": f"Invalid parameters for '{template_name}': {e}"})

    design = assemble(spec)
    return _format_circuit_design(design)


@mcp.tool()
def design_circuit(description: str, organism: str = "Escherichia coli") -> str:
    """Design a genetic circuit from a natural language description.

    This is the most powerful tool — describe what you want the circuit to do
    and it will figure out the architecture, find real biological parts, and
    assemble the full design with DNA sequences.

    Args:
        description: Natural language description of the desired circuit.
                     Examples:
                     - "Design a biosensor that detects arsenic and produces green fluorescence"
                     - "Build a toggle switch controlled by IPTG and tetracycline"
                     - "Create a kill switch that activates when arabinose is present"
                     - "Design a 3-enzyme pathway to convert glucose to ethanol"
        organism: Target organism (default: E. coli).
    """
    from circuits.circuit_builder import TEMPLATE_REGISTRY, assemble
    from models.part import CircuitSpec, CircuitPattern, FunctionalNode, CircuitEdge, PartType

    desc_lower = description.lower()

    if "biosensor" in desc_lower or ("detect" in desc_lower and ("fluoresc" in desc_lower or "glow" in desc_lower or "gfp" in desc_lower or "report" in desc_lower)):
        target, output = _extract_biosensor_params(desc_lower)
        spec = TEMPLATE_REGISTRY["biosensor"](target=target, output=output, organism=organism)
    elif "toggle" in desc_lower or "bistable" in desc_lower:
        a, b = _extract_toggle_params(desc_lower)
        spec = TEMPLATE_REGISTRY["toggle_switch"](inducer_a=a, inducer_b=b, organism=organism)
    elif "repressilat" in desc_lower or "oscillat" in desc_lower:
        spec = TEMPLATE_REGISTRY["repressilator"](organism=organism)
    elif "not gate" in desc_lower or "inverter" in desc_lower:
        signal = _extract_signal(desc_lower)
        spec = TEMPLATE_REGISTRY["logic_not"](input_signal=signal, organism=organism)
    elif "and gate" in desc_lower:
        a, b = _extract_two_inputs(desc_lower)
        spec = TEMPLATE_REGISTRY["logic_and"](input_a=a, input_b=b, organism=organism)
    elif "kill switch" in desc_lower or "cell death" in desc_lower or "safety" in desc_lower:
        trigger = _extract_signal(desc_lower)
        spec = TEMPLATE_REGISTRY["kill_switch"](trigger=trigger, organism=organism)
    elif "cascade" in desc_lower or "amplif" in desc_lower:
        signal = _extract_signal(desc_lower)
        stages = 3
        for word in desc_lower.split():
            if word.isdigit():
                stages = int(word)
                break
        spec = TEMPLATE_REGISTRY["cascade"](stages=stages, input_signal=signal, organism=organism)
    elif "pathway" in desc_lower or "metaboli" in desc_lower or "convert" in desc_lower:
        spec = _build_pathway_spec(desc_lower, organism)
    else:
        spec = _build_custom_spec(description, organism)

    design = assemble(spec)
    return _format_circuit_design(design)


@mcp.tool()
def get_circuit_sequence(
    description: str,
    organism: str = "Escherichia coli",
) -> str:
    """Design a circuit and return the full concatenated DNA sequence.

    Like design_circuit but focused on giving you the raw sequence output
    ready for synthesis ordering.

    Args:
        description: Natural language description of the desired circuit.
        organism: Target organism (default: E. coli).
    """
    from circuits.circuit_builder import TEMPLATE_REGISTRY, assemble

    result = json.loads(design_circuit(description, organism))
    if "error" in result:
        return json.dumps(result)

    return json.dumps({
        "circuit_name": result.get("circuit_name", ""),
        "total_length_bp": result.get("total_sequence_length", 0),
        "sequence": result.get("full_sequence", ""),
        "components": [
            {
                "unit": tu.get("unit_id", ""),
                "parts": [p["part_id"] for p in tu.get("parts", [])],
                "length_bp": tu.get("sequence_length", 0),
            }
            for tu in result.get("transcription_units", [])
        ],
    }, indent=2)


# ── Helpers ───────────────────────────────────────────────────────────


def _format_circuit_design(design) -> str:
    summary = design.to_summary()
    summary["full_sequence"] = design.sequence
    summary["full_sequence_length_bp"] = len(design.sequence)

    for tu in summary.get("transcription_units", []):
        for comp in tu.get("parts", []):
            comp_id = comp.get("part_id", "")
            for orig_tu in design.transcription_units:
                for orig_c in orig_tu.components:
                    if orig_c.part.part_id == comp_id:
                        comp["sequence_length"] = len(orig_c.part.sequence)
                        comp["organism"] = orig_c.part.organism
                        comp["source"] = orig_c.part.source_database

    summary["explanation"] = design.explanation
    return json.dumps(summary, indent=2)


_KNOWN_MOLECULES = [
    "arsenic", "mercury", "copper", "lead", "zinc", "cadmium",
    "IPTG", "tetracycline", "arabinose", "AHL", "lactose",
    "glucose", "ethanol", "light", "temperature", "pH",
]

_KNOWN_OUTPUTS = ["GFP", "RFP", "YFP", "CFP", "luciferase", "mCherry", "fluorescence"]


def _extract_biosensor_params(desc: str) -> tuple[str, str]:
    target = "arsenic"
    output = "GFP"
    for mol in _KNOWN_MOLECULES:
        if mol.lower() in desc:
            target = mol
            break
    for word in desc.split():
        clean = word.strip(".,!?")
        if clean.lower() in [o.lower() for o in _KNOWN_OUTPUTS]:
            output = clean
            break
    if "green" in desc:
        output = "GFP"
    elif "red" in desc:
        output = "RFP"
    elif "blue" in desc:
        output = "CFP"
    elif "yellow" in desc:
        output = "YFP"
    return target, output


def _extract_toggle_params(desc: str) -> tuple[str, str]:
    inducers = [m for m in _KNOWN_MOLECULES if m.lower() in desc]
    if len(inducers) >= 2:
        return inducers[0], inducers[1]
    elif len(inducers) == 1:
        return inducers[0], "tetracycline" if inducers[0] != "tetracycline" else "IPTG"
    return "IPTG", "tetracycline"


def _extract_signal(desc: str) -> str:
    for mol in _KNOWN_MOLECULES:
        if mol.lower() in desc:
            return mol
    return "IPTG"


def _extract_two_inputs(desc: str) -> tuple[str, str]:
    return _extract_toggle_params(desc)


def _build_pathway_spec(desc: str, organism: str):
    from circuits.circuit_builder import template_metabolic_pathway
    enzymes = ["enzyme_1", "enzyme_2", "enzyme_3"]
    substrate = "substrate"
    product = "product"

    words = desc.split()
    for i, w in enumerate(words):
        if w in ("convert", "converting") and i + 1 < len(words):
            substrate = words[i + 1].strip(".,")
        if w == "to" and i + 1 < len(words) and substrate != "substrate":
            product = words[i + 1].strip(".,")

    return template_metabolic_pathway(enzymes=enzymes, substrate=substrate,
                                      product=product, organism=organism)


def _build_custom_spec(description: str, organism: str):
    from models.part import CircuitSpec, CircuitPattern, FunctionalNode, CircuitEdge, PartType

    nodes = [
        FunctionalNode(
            node_id="promoter", role="promoter",
            description="Promoter for the circuit",
            required_type=PartType.PROMOTER,
            search_hint=description,
        ),
        FunctionalNode(
            node_id="main_gene", role="coding",
            description=f"Main coding sequence: {description}",
            required_type=PartType.CODING,
            search_hint=description,
        ),
        FunctionalNode(
            node_id="reporter", role="reporter",
            description="Reporter to monitor circuit activity",
            required_type=PartType.REPORTER,
            search_hint="GFP fluorescent reporter",
        ),
    ]
    edges = [
        CircuitEdge(source="promoter", target="main_gene", interaction="activates"),
        CircuitEdge(source="promoter", target="reporter", interaction="activates"),
    ]

    return CircuitSpec(
        circuit_name=f"Custom: {description[:60]}",
        pattern=CircuitPattern.CUSTOM,
        description=description,
        nodes=nodes, edges=edges,
        organism=organism,
    )


# ── Resources ─────────────────────────────────────────────────────────


@mcp.resource("bio://parts/stats")
def parts_stats() -> str:
    """Summary statistics about the parts database."""
    store = _get_store()
    count = store.count()
    return json.dumps({
        "total_parts": count,
        "sources": ["iGEM Registry", "NCBI GenBank", "UniProt", "Addgene"],
        "capabilities": [
            "Semantic search across all parts",
            "8 circuit templates (biosensor, toggle switch, repressilator, logic gates, etc.)",
            "Natural language circuit design",
            "Full DNA sequence assembly",
        ],
    }, indent=2)


# ── Entry point ───────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sse", action="store_true", help="Use SSE transport instead of stdio")
    parser.add_argument("--port", type=int, default=8080, help="Port for SSE transport")
    args = parser.parse_args()

    logger.info("Starting Bio-Circuit AI MCP server...")
    logger.info("Loading parts database...")
    store = _get_store()
    logger.info("Parts in database: %d", store.count())

    if args.sse:
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
