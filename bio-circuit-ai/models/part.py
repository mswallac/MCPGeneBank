from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Part types ───────────────────────────────────────────────────────


class PartType(str, Enum):
    PROMOTER = "promoter"
    REPORTER = "reporter"
    REGULATOR = "regulator"
    ENZYME = "enzyme"
    TERMINATOR = "terminator"
    RBS = "rbs"
    CODING = "coding"
    PLASMID = "plasmid"
    RECEPTOR = "receptor"
    SIGNAL_PEPTIDE = "signal_peptide"
    TOXIN = "toxin"
    ANTITOXIN = "antitoxin"
    OTHER = "other"


class BioPart(BaseModel):
    """Canonical representation of a biological part across all source databases."""

    part_id: str = Field(..., description="Unique identifier (e.g. BBa_K12345)")
    name: str = Field(..., description="Human-readable name")
    type: PartType = Field(default=PartType.OTHER)
    organism: str = Field(default="unknown")
    function: str = Field(default="", description="Functional annotation")
    sequence: str = Field(default="", description="DNA / protein sequence")
    description: str = Field(default="")
    references: list[str] = Field(default_factory=list)
    source_database: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    def embedding_text(self) -> str:
        """Concatenated text blob used for embedding generation."""
        parts = [self.name, self.type.value, self.function, self.description]
        if self.tags:
            parts.append(" ".join(self.tags))
        return " | ".join(p for p in parts if p)


# ── Circuit topology ─────────────────────────────────────────────────


class CircuitPattern(str, Enum):
    """Well-known genetic circuit architectures."""
    BIOSENSOR = "biosensor"
    TOGGLE_SWITCH = "toggle_switch"
    REPRESSILATOR = "repressilator"
    LOGIC_AND = "logic_and"
    LOGIC_OR = "logic_or"
    LOGIC_NOT = "logic_not"
    LOGIC_NAND = "logic_nand"
    CASCADE = "cascade"
    FEEDBACK_POSITIVE = "feedback_positive"
    FEEDBACK_NEGATIVE = "feedback_negative"
    KILL_SWITCH = "kill_switch"
    METABOLIC_PATHWAY = "metabolic_pathway"
    BAND_PASS = "band_pass"
    PULSE_GENERATOR = "pulse_generator"
    MEMORY_CIRCUIT = "memory_circuit"
    CUSTOM = "custom"


class FunctionalNode(BaseModel):
    """One functional unit in the circuit graph — a slot to fill with a real part."""

    node_id: str = Field(..., description="Unique id within the circuit, e.g. 'sensor_1'")
    role: str = Field(..., description="Functional role: promoter, repressor, reporter, enzyme, etc.")
    description: str = Field(default="", description="What this node should do")
    required_type: PartType | None = Field(default=None, description="Constrain to a specific part type")
    search_hint: str = Field(default="", description="Keywords for vector search")
    part: BioPart | None = Field(default=None, description="Assigned biological part (filled during assembly)")


class CircuitEdge(BaseModel):
    """Directed regulatory or functional relationship between two nodes."""

    source: str = Field(..., description="node_id of upstream element")
    target: str = Field(..., description="node_id of downstream element")
    interaction: str = Field(
        default="activates",
        description="activates | represses | produces_substrate_for | phosphorylates | degrades | induces | inhibits",
    )


class CircuitSpec(BaseModel):
    """
    LLM-generated or template-based specification for *any* genetic circuit.

    Replaces the old DesignRequest. This is the universal input to the assembly
    engine — it can represent a simple biosensor, a toggle switch, a
    repressilator, a multi-enzyme metabolic pathway, or any custom topology.
    """

    circuit_name: str = ""
    pattern: CircuitPattern = CircuitPattern.CUSTOM
    description: str = Field(default="", description="High-level description of the circuit")
    nodes: list[FunctionalNode] = Field(default_factory=list)
    edges: list[CircuitEdge] = Field(default_factory=list)
    organism: str = "Escherichia coli"
    constraints: list[str] = Field(default_factory=list)
    add_rbs: bool = True
    add_terminators: bool = True


# ── Assembly output (backward-compatible) ────────────────────────────


class CircuitComponent(BaseModel):
    role: str = Field(..., description="Functional role within the circuit")
    part: BioPart
    position: int = 0
    node_id: str = ""


class TranscriptionUnit(BaseModel):
    """One promoter → RBS → CDS → terminator block (a single operon unit)."""
    unit_id: str = ""
    components: list[CircuitComponent] = Field(default_factory=list)

    @property
    def sequence(self) -> str:
        return "".join(c.part.sequence for c in self.components if c.part.sequence)


class CircuitDesign(BaseModel):
    circuit_name: str
    pattern: CircuitPattern = CircuitPattern.CUSTOM
    transcription_units: list[TranscriptionUnit] = Field(default_factory=list)
    components: list[CircuitComponent] = Field(default_factory=list)
    edges: list[CircuitEdge] = Field(default_factory=list)
    sequence: str = Field(default="", description="Concatenated full sequence")
    explanation: str = ""
    references: list[str] = Field(default_factory=list)

    def to_summary(self) -> dict:
        return {
            "circuit_name": self.circuit_name,
            "pattern": self.pattern.value,
            "transcription_units": [
                {
                    "unit_id": tu.unit_id,
                    "parts": [
                        {"role": c.role, "part": c.part.name, "part_id": c.part.part_id}
                        for c in tu.components
                    ],
                    "sequence_length": len(tu.sequence),
                }
                for tu in self.transcription_units
            ],
            "edges": [
                {"source": e.source, "target": e.target, "interaction": e.interaction}
                for e in self.edges
            ],
            "total_sequence_length": len(self.sequence),
            "explanation": self.explanation,
        }
