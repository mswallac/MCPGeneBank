"""
LLM orchestration layer — the "brain" of the circuit design system.

The planner receives a natural language request, uses an LLM to decompose it
into a CircuitSpec (graph of functional nodes + edges), invokes the assembly
engine to fill each node with real biological parts, then asks the LLM to
synthesise a coherent scientific explanation.

Supports *any* genetic circuit: biosensors, toggle switches, repressilators,
logic gates, cascades, kill switches, metabolic pathways, and custom designs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from circuits.circuit_builder import TEMPLATE_REGISTRY, assemble
from config import get_settings
from models.part import (
    CircuitDesign,
    CircuitEdge,
    CircuitPattern,
    CircuitSpec,
    FunctionalNode,
    PartType,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert synthetic biology circuit design assistant.

Given a user's natural-language request, decompose it into a structured genetic
circuit specification.  You can design ANY type of circuit:

KNOWN PATTERNS (use these names in the "pattern" field):
- biosensor          : sensor promoter -> regulator -> reporter
- toggle_switch      : two mutually repressing modules (bistable switch)
- repressilator      : three-gene ring oscillator (TetR -> LacI -> cI -> TetR)
- logic_and          : output ON only when BOTH inputs present
- logic_or           : output ON when EITHER input present
- logic_not          : inverter — output ON when input ABSENT
- logic_nand         : output OFF only when both inputs present
- cascade            : multi-stage signal amplification chain
- feedback_positive  : positive autoregulatory loop
- feedback_negative  : negative autoregulatory loop
- kill_switch        : conditional cell death (toxin/antitoxin)
- metabolic_pathway  : multi-enzyme pathway converting substrate to product
- band_pass          : output ON only in a range of input concentrations
- pulse_generator    : transient output pulse in response to input step
- memory_circuit     : irreversible genetic memory (recombinase-based)
- custom             : anything else — define the nodes and edges yourself

Return a JSON object with this schema:
{
  "circuit_name": "descriptive name",
  "pattern": "one of the pattern names above",
  "description": "1-2 sentence description of what the circuit does",
  "organism": "host organism (default: Escherichia coli)",
  "constraints": ["any constraints mentioned by the user"],
  "add_rbs": true,
  "add_terminators": true,
  "nodes": [
    {
      "node_id": "unique_id (e.g. sensor_1, repressor_a, enzyme_2)",
      "role": "promoter | repressor | activator | regulator | reporter | enzyme | toxin | antitoxin | recombinase | output | sensor",
      "description": "what this node does in the circuit",
      "required_type": "promoter | reporter | regulator | enzyme | terminator | rbs | coding | null",
      "search_hint": "keywords to find the right biological part in the database"
    }
  ],
  "edges": [
    {
      "source": "node_id of upstream element",
      "target": "node_id of downstream element",
      "interaction": "activates | represses | produces_substrate_for | phosphorylates | degrades | induces | inhibits"
    }
  ]
}

RULES:
- Every promoter node should have required_type = "promoter"
- Every reporter/output node should have required_type = "reporter"
- Regulator/repressor/activator nodes should have required_type = "regulator"
- Enzyme nodes should have required_type = "enzyme"
- search_hint should contain specific biological keywords for database retrieval
- For biosensors, include the target molecule in search_hint (e.g. "arsenic sensing promoter")
- For reporters, include the output signal (e.g. "GFP green fluorescent protein")
- Return ONLY valid JSON. No markdown fences, no explanation outside the JSON.
"""

EXPLAIN_PROMPT = """\
You are a synthetic biology expert. Given the following assembled genetic
circuit, write a clear and detailed explanation suitable for a molecular
biology researcher.

Circuit specification:
{circuit_json}

Cover:
1. Overall circuit architecture and design pattern
2. The molecular mechanism of each functional module
3. Expected dynamic behaviour (steady states, oscillations, thresholds, etc.)
4. Potential failure modes and suggested improvements
5. Relevant literature references if applicable

Be scientifically rigorous but accessible.
"""


def _call_llm(messages: list[dict[str, str]], temperature: float = 0.2) -> str:
    cfg = get_settings()
    client = OpenAI(api_key=cfg.openai_api_key)
    resp = client.chat.completions.create(
        model=cfg.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=3000,
    )
    return resp.choices[0].message.content.strip()


def _strip_markdown_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return raw


def parse_to_circuit_spec(user_prompt: str) -> CircuitSpec:
    """Use the LLM to decompose any natural-language request into a CircuitSpec."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw = _call_llm(messages, temperature=0.1)
    raw = _strip_markdown_fences(raw)
    data = json.loads(raw)

    nodes = []
    for nd in data.get("nodes", []):
        req_type = nd.get("required_type")
        if req_type and req_type != "null":
            try:
                req_type = PartType(req_type)
            except ValueError:
                req_type = None
        else:
            req_type = None
        nodes.append(FunctionalNode(
            node_id=nd["node_id"],
            role=nd.get("role", "other"),
            description=nd.get("description", ""),
            required_type=req_type,
            search_hint=nd.get("search_hint", ""),
        ))

    edges = [
        CircuitEdge(source=e["source"], target=e["target"], interaction=e.get("interaction", "activates"))
        for e in data.get("edges", [])
    ]

    pattern_str = data.get("pattern", "custom")
    try:
        pattern = CircuitPattern(pattern_str)
    except ValueError:
        pattern = CircuitPattern.CUSTOM

    return CircuitSpec(
        circuit_name=data.get("circuit_name", "Custom Circuit"),
        pattern=pattern,
        description=data.get("description", ""),
        nodes=nodes,
        edges=edges,
        organism=data.get("organism", "Escherichia coli"),
        constraints=data.get("constraints", []),
        add_rbs=data.get("add_rbs", True),
        add_terminators=data.get("add_terminators", True),
    )


def enhance_explanation(circuit: CircuitDesign) -> str:
    """Ask the LLM to produce a richer scientific explanation of the circuit."""
    circuit_json = json.dumps(circuit.to_summary(), indent=2)
    messages = [
        {"role": "system", "content": "You are a synthetic biology expert."},
        {"role": "user", "content": EXPLAIN_PROMPT.format(circuit_json=circuit_json)},
    ]
    try:
        return _call_llm(messages, temperature=0.3)
    except Exception:
        logger.exception("LLM explanation enhancement failed, using built-in explanation")
        return circuit.explanation


def design_circuit(user_prompt: str) -> dict[str, Any]:
    """
    End-to-end pipeline: natural language -> any genetic circuit.

    1. LLM decomposes the prompt into a CircuitSpec (nodes + edges)
    2. Assembly engine fills each node with real biological parts
    3. LLM generates a detailed scientific explanation
    4. Returns structured JSON
    """
    logger.info("Design request: %s", user_prompt)

    try:
        spec = parse_to_circuit_spec(user_prompt)
    except Exception:
        logger.exception("LLM parsing failed, attempting rule-based fallback")
        spec = _fallback_parse(user_prompt)

    circuit = assemble(spec)

    try:
        enhanced = enhance_explanation(circuit)
        circuit.explanation = enhanced
    except Exception:
        logger.warning("Could not enhance explanation with LLM")

    return _format_response(spec, circuit)


def design_from_spec(spec: CircuitSpec) -> dict[str, Any]:
    """Assembly from an already-built CircuitSpec (templates, API, etc.)."""
    circuit = assemble(spec)
    return _format_response(spec, circuit)


def _format_response(spec: CircuitSpec, circuit: CircuitDesign) -> dict[str, Any]:
    return {
        "circuit_name": circuit.circuit_name,
        "pattern": circuit.pattern.value,
        "design_spec": {
            "description": spec.description,
            "organism": spec.organism,
            "constraints": spec.constraints,
            "node_count": len(spec.nodes),
            "edge_count": len(spec.edges),
        },
        "transcription_units": [
            {
                "unit_id": tu.unit_id,
                "parts": [
                    {"role": c.role, "part_name": c.part.name, "part_id": c.part.part_id, "type": c.part.type.value}
                    for c in tu.components
                ],
                "sequence_length": len(tu.sequence),
            }
            for tu in circuit.transcription_units
        ],
        "edges": [
            {"source": e.source, "target": e.target, "interaction": e.interaction}
            for e in circuit.edges
        ],
        "components": [
            {
                "role": c.role,
                "node_id": c.node_id,
                "part_id": c.part.part_id,
                "part_name": c.part.name,
                "type": c.part.type.value,
                "function": c.part.function,
                "sequence_length": len(c.part.sequence),
            }
            for c in circuit.components
        ],
        "total_sequence_length": len(circuit.sequence),
        "sequence_preview": circuit.sequence[:500] + ("..." if len(circuit.sequence) > 500 else ""),
        "explanation": circuit.explanation,
        "references": circuit.references,
    }


# ── Rule-based fallback ──────────────────────────────────────────────


def _fallback_parse(prompt: str) -> CircuitSpec:
    """Rule-based fallback when the LLM is unavailable — handles common patterns."""
    lower = prompt.lower()

    if "toggle" in lower or "switch" in lower or "bistable" in lower:
        return _fallback_toggle(lower)
    if "oscillat" in lower or "repressilator" in lower:
        from circuits.circuit_builder import template_repressilator
        return template_repressilator()
    if "and gate" in lower or "and logic" in lower:
        return _fallback_logic_and(lower)
    if "not gate" in lower or "inverter" in lower:
        return _fallback_logic_not(lower)
    if "kill switch" in lower or "kill" in lower and "safety" in lower:
        return _fallback_kill_switch(lower)
    if "cascade" in lower or "amplif" in lower:
        return _fallback_cascade(lower)
    if "pathway" in lower or "metaboli" in lower or "enzyme" in lower:
        return _fallback_metabolic(lower)

    return _fallback_biosensor(lower)


def _fallback_biosensor(lower: str) -> CircuitSpec:
    from circuits.circuit_builder import template_biosensor

    molecules = ["arsenic", "mercury", "lead", "copper", "zinc", "cadmium",
                 "iptg", "arabinose", "tetracycline", "light"]
    target = "unknown"
    for mol in molecules:
        if mol in lower:
            target = mol
            break

    signals = {"green": "green fluorescence", "red": "red fluorescence",
               "blue": "blue fluorescence", "glow": "green fluorescence",
               "fluorescen": "green fluorescence", "luminesce": "luminescence"}
    output = "green fluorescence"
    for key, val in signals.items():
        if key in lower:
            output = val
            break

    spec = template_biosensor(target, output)
    spec.constraints.append("Parsed via rule-based fallback (LLM unavailable)")
    return spec


def _fallback_toggle(lower: str) -> CircuitSpec:
    from circuits.circuit_builder import template_toggle_switch
    spec = template_toggle_switch("IPTG", "tetracycline")
    spec.constraints.append("Parsed via rule-based fallback (LLM unavailable)")
    return spec


def _fallback_logic_and(lower: str) -> CircuitSpec:
    from circuits.circuit_builder import template_logic_and
    spec = template_logic_and("arabinose", "IPTG")
    spec.constraints.append("Parsed via rule-based fallback (LLM unavailable)")
    return spec


def _fallback_logic_not(lower: str) -> CircuitSpec:
    from circuits.circuit_builder import template_logic_not
    spec = template_logic_not("IPTG")
    spec.constraints.append("Parsed via rule-based fallback (LLM unavailable)")
    return spec


def _fallback_kill_switch(lower: str) -> CircuitSpec:
    from circuits.circuit_builder import template_kill_switch
    spec = template_kill_switch("arabinose")
    spec.constraints.append("Parsed via rule-based fallback (LLM unavailable)")
    return spec


def _fallback_cascade(lower: str) -> CircuitSpec:
    from circuits.circuit_builder import template_cascade
    spec = template_cascade(stages=3, input_signal="IPTG")
    spec.constraints.append("Parsed via rule-based fallback (LLM unavailable)")
    return spec


def _fallback_metabolic(lower: str) -> CircuitSpec:
    from circuits.circuit_builder import template_metabolic_pathway
    spec = template_metabolic_pathway(["enzyme_1", "enzyme_2"], "substrate", "product")
    spec.constraints.append("Parsed via rule-based fallback (LLM unavailable)")
    return spec
