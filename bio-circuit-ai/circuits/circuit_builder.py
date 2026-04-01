"""
General-purpose genetic circuit assembly engine.

Accepts a CircuitSpec (graph of functional nodes + edges) and fills each node
with a real biological part from the vector store.  Supports any topology:
biosensors, toggle switches, repressilators, logic gates, cascades, metabolic
pathways, kill switches, and fully custom circuits.

Also provides a library of circuit *templates* — pre-defined CircuitSpec
objects for common patterns that the LLM planner or users can invoke by name.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from models.part import (
    BioPart,
    CircuitComponent,
    CircuitDesign,
    CircuitEdge,
    CircuitPattern,
    CircuitSpec,
    FunctionalNode,
    PartType,
    TranscriptionUnit,
)
from tools.search_parts import find_accessory_part, find_parts_for_node

logger = logging.getLogger(__name__)


# ── Circuit template library ─────────────────────────────────────────


def template_biosensor(target: str, output: str, organism: str = "Escherichia coli") -> CircuitSpec:
    return CircuitSpec(
        circuit_name=f"{target.title()} {output.title()} Biosensor",
        pattern=CircuitPattern.BIOSENSOR,
        description=f"Biosensor that detects {target} and produces {output}",
        nodes=[
            FunctionalNode(node_id="sensor", role="promoter", description=f"{target}-responsive promoter",
                           required_type=PartType.PROMOTER, search_hint=f"{target} sensing promoter"),
            FunctionalNode(node_id="regulator", role="regulator", description=f"{target}-responsive transcription factor",
                           required_type=PartType.REGULATOR, search_hint=f"{target} transcription factor repressor"),
            FunctionalNode(node_id="reporter", role="reporter", description=f"{output} reporter gene",
                           required_type=PartType.REPORTER, search_hint=f"{output} reporter"),
        ],
        edges=[
            CircuitEdge(source="sensor", target="regulator", interaction="activates"),
            CircuitEdge(source="regulator", target="reporter", interaction="activates"),
        ],
        organism=organism,
    )


def template_toggle_switch(inducer_a: str, inducer_b: str, output_a: str = "GFP",
                           output_b: str = "RFP", organism: str = "Escherichia coli") -> CircuitSpec:
    return CircuitSpec(
        circuit_name=f"{inducer_a.title()}/{inducer_b.title()} Toggle Switch",
        pattern=CircuitPattern.TOGGLE_SWITCH,
        description=f"Bistable toggle switch: {inducer_a} drives state A ({output_a}), {inducer_b} drives state B ({output_b})",
        nodes=[
            FunctionalNode(node_id="promoter_a", role="promoter", description=f"Promoter repressed by repressor B, induced by {inducer_a}",
                           required_type=PartType.PROMOTER, search_hint=f"{inducer_a} inducible promoter"),
            FunctionalNode(node_id="repressor_a", role="repressor", description=f"Repressor protein that blocks promoter B",
                           required_type=PartType.REGULATOR, search_hint=f"{inducer_a} repressor regulator"),
            FunctionalNode(node_id="reporter_a", role="reporter", description=f"{output_a} reporter for state A",
                           required_type=PartType.REPORTER, search_hint=f"{output_a} fluorescent reporter"),
            FunctionalNode(node_id="promoter_b", role="promoter", description=f"Promoter repressed by repressor A, induced by {inducer_b}",
                           required_type=PartType.PROMOTER, search_hint=f"{inducer_b} inducible promoter"),
            FunctionalNode(node_id="repressor_b", role="repressor", description=f"Repressor protein that blocks promoter A",
                           required_type=PartType.REGULATOR, search_hint=f"{inducer_b} repressor regulator"),
            FunctionalNode(node_id="reporter_b", role="reporter", description=f"{output_b} reporter for state B",
                           required_type=PartType.REPORTER, search_hint=f"{output_b} fluorescent reporter"),
        ],
        edges=[
            CircuitEdge(source="promoter_a", target="repressor_a", interaction="activates"),
            CircuitEdge(source="promoter_a", target="reporter_a", interaction="activates"),
            CircuitEdge(source="repressor_a", target="promoter_b", interaction="represses"),
            CircuitEdge(source="promoter_b", target="repressor_b", interaction="activates"),
            CircuitEdge(source="promoter_b", target="reporter_b", interaction="activates"),
            CircuitEdge(source="repressor_b", target="promoter_a", interaction="represses"),
        ],
        organism=organism,
    )


def template_repressilator(organism: str = "Escherichia coli") -> CircuitSpec:
    return CircuitSpec(
        circuit_name="Repressilator Oscillator",
        pattern=CircuitPattern.REPRESSILATOR,
        description="Three-gene ring oscillator: each repressor inhibits the next in a cycle (TetR -> LacI -> cI -> TetR)",
        nodes=[
            FunctionalNode(node_id="promoter_1", role="promoter", description="PLtet promoter repressed by TetR",
                           required_type=PartType.PROMOTER, search_hint="tetracycline inducible promoter PLtet"),
            FunctionalNode(node_id="repressor_1", role="repressor", description="LacI repressor protein",
                           required_type=PartType.REGULATOR, search_hint="LacI repressor lac operon"),
            FunctionalNode(node_id="promoter_2", role="promoter", description="PLlac promoter repressed by LacI",
                           required_type=PartType.PROMOTER, search_hint="lac promoter IPTG inducible"),
            FunctionalNode(node_id="repressor_2", role="repressor", description="cI repressor protein (lambda phage)",
                           required_type=PartType.REGULATOR, search_hint="lambda cI repressor phage"),
            FunctionalNode(node_id="promoter_3", role="promoter", description="PR promoter repressed by cI",
                           required_type=PartType.PROMOTER, search_hint="lambda PR promoter"),
            FunctionalNode(node_id="repressor_3", role="repressor", description="TetR repressor protein",
                           required_type=PartType.REGULATOR, search_hint="TetR tetracycline repressor"),
            FunctionalNode(node_id="reporter", role="reporter", description="GFP reporter to visualize oscillations",
                           required_type=PartType.REPORTER, search_hint="GFP green fluorescent protein"),
        ],
        edges=[
            CircuitEdge(source="promoter_1", target="repressor_1", interaction="activates"),
            CircuitEdge(source="repressor_1", target="promoter_2", interaction="represses"),
            CircuitEdge(source="promoter_2", target="repressor_2", interaction="activates"),
            CircuitEdge(source="repressor_2", target="promoter_3", interaction="represses"),
            CircuitEdge(source="promoter_3", target="repressor_3", interaction="activates"),
            CircuitEdge(source="repressor_3", target="promoter_1", interaction="represses"),
            CircuitEdge(source="promoter_1", target="reporter", interaction="activates"),
        ],
        organism=organism,
    )


def template_logic_not(input_signal: str, output: str = "GFP", organism: str = "Escherichia coli") -> CircuitSpec:
    return CircuitSpec(
        circuit_name=f"NOT Gate ({input_signal})",
        pattern=CircuitPattern.LOGIC_NOT,
        description=f"Inverter: output ({output}) is ON when {input_signal} is absent, OFF when present",
        nodes=[
            FunctionalNode(node_id="input_promoter", role="promoter", description=f"{input_signal}-inducible promoter",
                           required_type=PartType.PROMOTER, search_hint=f"{input_signal} inducible promoter"),
            FunctionalNode(node_id="inverter_repressor", role="repressor", description="Repressor driven by input, blocks output promoter",
                           required_type=PartType.REGULATOR, search_hint="repressor transcription factor"),
            FunctionalNode(node_id="output_promoter", role="promoter", description="Constitutive promoter repressed by inverter",
                           required_type=PartType.PROMOTER, search_hint="constitutive promoter strong"),
            FunctionalNode(node_id="output_reporter", role="reporter", description=f"{output} reporter",
                           required_type=PartType.REPORTER, search_hint=f"{output} fluorescent reporter"),
        ],
        edges=[
            CircuitEdge(source="input_promoter", target="inverter_repressor", interaction="activates"),
            CircuitEdge(source="inverter_repressor", target="output_promoter", interaction="represses"),
            CircuitEdge(source="output_promoter", target="output_reporter", interaction="activates"),
        ],
        organism=organism,
    )


def template_logic_and(input_a: str, input_b: str, output: str = "GFP",
                       organism: str = "Escherichia coli") -> CircuitSpec:
    return CircuitSpec(
        circuit_name=f"AND Gate ({input_a} + {input_b})",
        pattern=CircuitPattern.LOGIC_AND,
        description=f"AND gate: output ({output}) only ON when both {input_a} AND {input_b} are present",
        nodes=[
            FunctionalNode(node_id="promoter_a", role="promoter", description=f"{input_a}-responsive promoter",
                           required_type=PartType.PROMOTER, search_hint=f"{input_a} inducible promoter"),
            FunctionalNode(node_id="activator_a", role="regulator", description=f"Transcription factor activated by {input_a}",
                           required_type=PartType.REGULATOR, search_hint=f"{input_a} activator transcription factor"),
            FunctionalNode(node_id="promoter_b", role="promoter", description=f"{input_b}-responsive promoter",
                           required_type=PartType.PROMOTER, search_hint=f"{input_b} inducible promoter"),
            FunctionalNode(node_id="activator_b", role="regulator", description=f"Transcription factor activated by {input_b}",
                           required_type=PartType.REGULATOR, search_hint=f"{input_b} activator transcription factor"),
            FunctionalNode(node_id="and_promoter", role="promoter", description="Hybrid promoter requiring both activators",
                           required_type=PartType.PROMOTER, search_hint="hybrid dual input promoter AND gate"),
            FunctionalNode(node_id="output_reporter", role="reporter", description=f"{output} reporter gene",
                           required_type=PartType.REPORTER, search_hint=f"{output} fluorescent reporter"),
        ],
        edges=[
            CircuitEdge(source="promoter_a", target="activator_a", interaction="activates"),
            CircuitEdge(source="promoter_b", target="activator_b", interaction="activates"),
            CircuitEdge(source="activator_a", target="and_promoter", interaction="activates"),
            CircuitEdge(source="activator_b", target="and_promoter", interaction="activates"),
            CircuitEdge(source="and_promoter", target="output_reporter", interaction="activates"),
        ],
        organism=organism,
    )


def template_kill_switch(trigger: str, organism: str = "Escherichia coli") -> CircuitSpec:
    return CircuitSpec(
        circuit_name=f"{trigger.title()}-Activated Kill Switch",
        pattern=CircuitPattern.KILL_SWITCH,
        description=f"Safety circuit: cell death is triggered when {trigger} is detected",
        nodes=[
            FunctionalNode(node_id="trigger_promoter", role="promoter", description=f"{trigger}-responsive promoter",
                           required_type=PartType.PROMOTER, search_hint=f"{trigger} inducible promoter"),
            FunctionalNode(node_id="toxin_gene", role="toxin", description="Toxin protein for programmed cell death",
                           required_type=PartType.CODING, search_hint="toxin cell death CcdB MazF"),
            FunctionalNode(node_id="antitoxin_promoter", role="promoter", description="Constitutive promoter for antitoxin (active under normal conditions)",
                           required_type=PartType.PROMOTER, search_hint="constitutive promoter"),
            FunctionalNode(node_id="antitoxin_gene", role="antitoxin", description="Antitoxin protein neutralizing the toxin under normal conditions",
                           required_type=PartType.CODING, search_hint="antitoxin CcdA MazE"),
        ],
        edges=[
            CircuitEdge(source="trigger_promoter", target="toxin_gene", interaction="activates"),
            CircuitEdge(source="antitoxin_promoter", target="antitoxin_gene", interaction="activates"),
            CircuitEdge(source="antitoxin_gene", target="toxin_gene", interaction="inhibits"),
        ],
        organism=organism,
    )


def template_metabolic_pathway(enzymes: list[str], substrate: str, product: str,
                               organism: str = "Escherichia coli") -> CircuitSpec:
    nodes: list[FunctionalNode] = [
        FunctionalNode(node_id="pathway_promoter", role="promoter",
                       description=f"Promoter driving the {substrate} to {product} pathway",
                       required_type=PartType.PROMOTER, search_hint="strong constitutive promoter"),
    ]
    edges: list[CircuitEdge] = []
    for i, enz in enumerate(enzymes):
        nid = f"enzyme_{i}"
        nodes.append(FunctionalNode(
            node_id=nid, role="enzyme", description=f"Enzyme: {enz}",
            required_type=PartType.ENZYME, search_hint=f"{enz} enzyme",
        ))
        if i == 0:
            edges.append(CircuitEdge(source="pathway_promoter", target=nid, interaction="activates"))
        else:
            edges.append(CircuitEdge(source=f"enzyme_{i-1}", target=nid, interaction="produces_substrate_for"))

    return CircuitSpec(
        circuit_name=f"{substrate.title()} -> {product.title()} Pathway",
        pattern=CircuitPattern.METABOLIC_PATHWAY,
        description=f"Metabolic pathway converting {substrate} to {product} via {len(enzymes)} enzymatic steps",
        nodes=nodes,
        edges=edges,
        organism=organism,
    )


def template_cascade(stages: int, input_signal: str, output: str = "GFP",
                     organism: str = "Escherichia coli") -> CircuitSpec:
    nodes: list[FunctionalNode] = []
    edges: list[CircuitEdge] = []

    nodes.append(FunctionalNode(
        node_id="input_promoter", role="promoter",
        description=f"{input_signal}-responsive promoter",
        required_type=PartType.PROMOTER, search_hint=f"{input_signal} inducible promoter",
    ))

    prev_id = "input_promoter"
    for i in range(stages):
        act_id = f"amplifier_{i}"
        prom_id = f"stage_{i}_promoter"
        nodes.append(FunctionalNode(
            node_id=act_id, role="regulator",
            description=f"Stage {i+1} amplifier / activator",
            required_type=PartType.REGULATOR, search_hint="transcriptional activator amplifier",
        ))
        edges.append(CircuitEdge(source=prev_id, target=act_id, interaction="activates"))
        if i < stages - 1:
            nodes.append(FunctionalNode(
                node_id=prom_id, role="promoter",
                description=f"Promoter for stage {i+2}",
                required_type=PartType.PROMOTER, search_hint="regulatable promoter",
            ))
            edges.append(CircuitEdge(source=act_id, target=prom_id, interaction="activates"))
            prev_id = prom_id
        else:
            prev_id = act_id

    nodes.append(FunctionalNode(
        node_id="output_reporter", role="reporter",
        description=f"{output} reporter",
        required_type=PartType.REPORTER, search_hint=f"{output} fluorescent reporter",
    ))
    edges.append(CircuitEdge(source=prev_id, target="output_reporter", interaction="activates"))

    return CircuitSpec(
        circuit_name=f"{stages}-Stage {input_signal.title()} Signal Cascade",
        pattern=CircuitPattern.CASCADE,
        description=f"{stages}-stage signal amplification cascade triggered by {input_signal}, producing {output}",
        nodes=nodes,
        edges=edges,
        organism=organism,
    )


TEMPLATE_REGISTRY: dict[str, callable] = {
    "biosensor": template_biosensor,
    "toggle_switch": template_toggle_switch,
    "repressilator": template_repressilator,
    "logic_not": template_logic_not,
    "logic_and": template_logic_and,
    "kill_switch": template_kill_switch,
    "metabolic_pathway": template_metabolic_pathway,
    "cascade": template_cascade,
}


# ── General assembly engine ──────────────────────────────────────────


def _pick_best(candidates: list[BioPart], organism: str) -> BioPart | None:
    if not candidates:
        return None
    org_lower = organism.lower()
    for c in candidates:
        if org_lower in c.organism.lower():
            return c
    return candidates[0]


def _build_transcription_units(spec: CircuitSpec) -> list[TranscriptionUnit]:
    """
    Group nodes into transcription units based on the circuit edges.

    Strategy: each promoter node starts a new TU. Downstream coding/reporter/
    enzyme nodes driven by that promoter are placed in the same TU.
    """
    promoter_ids = {n.node_id for n in spec.nodes if n.role in ("promoter", "sensor", "inducible_promoter", "constitutive_promoter")}
    downstream: dict[str, list[str]] = {pid: [] for pid in promoter_ids}

    for edge in spec.edges:
        if edge.source in promoter_ids and edge.interaction in ("activates", "induces"):
            downstream[edge.source].append(edge.target)

    node_map = {n.node_id: n for n in spec.nodes}
    assigned: set[str] = set()
    units: list[TranscriptionUnit] = []

    for pid in promoter_ids:
        pnode = node_map.get(pid)
        if not pnode or not pnode.part:
            continue

        components: list[CircuitComponent] = []
        pos = 0

        components.append(CircuitComponent(role=pnode.role, part=pnode.part, position=pos, node_id=pid))
        assigned.add(pid)
        pos += 1

        for child_id in downstream[pid]:
            child = node_map.get(child_id)
            if not child or not child.part or child_id in assigned:
                continue
            if child.role in ("promoter", "sensor"):
                continue

            if spec.add_rbs:
                rbs = find_accessory_part("ribosome binding site", PartType.RBS)
                if rbs:
                    components.append(CircuitComponent(role="rbs", part=rbs, position=pos))
                    pos += 1

            components.append(CircuitComponent(role=child.role, part=child.part, position=pos, node_id=child_id))
            assigned.add(child_id)
            pos += 1

        if spec.add_terminators:
            term = find_accessory_part("transcription terminator", PartType.TERMINATOR)
            if term:
                components.append(CircuitComponent(role="terminator", part=term, position=pos))
                pos += 1

        units.append(TranscriptionUnit(unit_id=pid, components=components))

    for n in spec.nodes:
        if n.node_id not in assigned and n.part:
            units.append(TranscriptionUnit(
                unit_id=n.node_id,
                components=[CircuitComponent(role=n.role, part=n.part, position=0, node_id=n.node_id)],
            ))

    return units


def assemble(spec: CircuitSpec) -> CircuitDesign:
    """
    Universal assembly entry point.

    1. For each FunctionalNode, search the vector store for matching parts
    2. Assign the best-matching part to each node
    3. Group into transcription units
    4. Concatenate sequences and generate explanation
    """
    spec = deepcopy(spec)

    logger.info("Assembling circuit: %s (pattern=%s, %d nodes, %d edges)",
                spec.circuit_name, spec.pattern.value, len(spec.nodes), len(spec.edges))

    for node in spec.nodes:
        if node.part is not None:
            continue
        candidates = find_parts_for_node(node, organism=spec.organism)
        best = _pick_best(candidates, spec.organism)
        if best:
            node.part = best
            logger.info("  %s -> %s (%s)", node.node_id, best.name, best.part_id)
        else:
            logger.warning("  %s -> NO MATCH FOUND", node.node_id)

    tus = _build_transcription_units(spec)

    all_components: list[CircuitComponent] = []
    for tu in tus:
        all_components.extend(tu.components)

    full_sequence = "".join(tu.sequence for tu in tus)

    refs: list[str] = []
    for c in all_components:
        refs.extend(c.part.references)

    explanation = _generate_explanation(spec, tus)

    return CircuitDesign(
        circuit_name=spec.circuit_name,
        pattern=spec.pattern,
        transcription_units=tus,
        components=all_components,
        edges=spec.edges,
        sequence=full_sequence,
        explanation=explanation,
        references=refs,
    )


def _generate_explanation(spec: CircuitSpec, tus: list[TranscriptionUnit]) -> str:
    lines = [
        f"## {spec.circuit_name}",
        f"**Pattern:** {spec.pattern.value.replace('_', ' ').title()}",
        f"**Organism:** {spec.organism}",
        "",
        f"### Description",
        spec.description,
        "",
        "### Transcription Units",
    ]

    for tu in tus:
        part_names = " -> ".join(c.part.name for c in tu.components)
        lines.append(f"- **{tu.unit_id}**: {part_names} ({len(tu.sequence)} bp)")

    lines.append("")
    lines.append("### Regulatory Connections")
    for edge in spec.edges:
        lines.append(f"- {edge.source} --[{edge.interaction}]--> {edge.target}")

    node_map = {n.node_id: n for n in spec.nodes}
    lines.append("")
    lines.append("### Component Details")
    for n in spec.nodes:
        if n.part:
            lines.append(f"- **{n.node_id}** ({n.role}): {n.part.name} -- {n.part.function[:120]}")
        else:
            lines.append(f"- **{n.node_id}** ({n.role}): *no matching part found*")

    total_bp = sum(len(tu.sequence) for tu in tus)
    lines.append(f"\n**Total construct:** ~{total_bp} bp across {len(tus)} transcription unit(s)")

    return "\n".join(lines)


# ── Backward compatibility ───────────────────────────────────────────


def assemble_circuit(target_molecule: str, output_signal: str,
                     organism: str = "Escherichia coli") -> CircuitDesign:
    """Legacy convenience function — creates a biosensor spec and assembles it."""
    spec = template_biosensor(target_molecule, output_signal, organism)
    return assemble(spec)
