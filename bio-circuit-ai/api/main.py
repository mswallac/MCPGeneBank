"""
FastAPI application — the public interface for the Bio-Circuit AI system.

Endpoints:
  POST /design              — Natural language -> any genetic circuit (full pipeline)
  POST /design/from-spec    — Build from a structured CircuitSpec
  POST /design/template     — Build from a named template pattern
  GET  /templates           — List available circuit templates
  GET  /search              — Semantic search over biological parts
  GET  /search/sensors      — Find sensor parts for a target molecule
  GET  /search/reporters    — Find reporter parts for an output signal
  GET  /search/regulators   — Find regulators for a target
  GET  /parts/count         — Number of parts in the vector store
  POST /ingest              — Trigger ingestion from external databases
  GET  /health              — Health check
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from circuits.circuit_builder import TEMPLATE_REGISTRY, assemble
from database.vector_store import get_vector_store
from models.part import CircuitEdge, CircuitPattern, CircuitSpec, FunctionalNode, PartType
from orchestration.planner import design_circuit, design_from_spec
from tools.regulators import find_regulator
from tools.reporters import find_reporter
from tools.search_parts import search_parts_raw
from tools.sensors import find_sensor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("Bio-Circuit AI starting up")
    get_vector_store()
    yield
    logger.info("Bio-Circuit AI shutting down")


app = FastAPI(
    title="Bio-Circuit AI",
    description=(
        "Natural language -> any genetic circuit design. "
        "Supports biosensors, toggle switches, repressilators, logic gates, "
        "cascades, kill switches, metabolic pathways, and custom topologies."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


# -- Request / Response models ────────────────────────────────────────


class DesignPrompt(BaseModel):
    prompt: str = Field(..., description="Natural language circuit design request", min_length=5)
    use_llm: bool = Field(default=True, description="Use LLM for parsing and explanation")


class TemplateRequest(BaseModel):
    template: str = Field(..., description="Template name: biosensor, toggle_switch, repressilator, logic_and, logic_not, kill_switch, metabolic_pathway, cascade")
    params: dict[str, Any] = Field(default_factory=dict, description="Template parameters (varies by template)")
    organism: str = Field(default="Escherichia coli")


class IngestRequest(BaseModel):
    sources: list[str] = Field(
        default=["igem"],
        description="Databases to ingest from: igem, genbank, uniprot, addgene",
    )
    queries: list[str] = Field(
        default=["promoter", "GFP", "biosensor"],
        description="Search queries to use for ingestion",
    )
    limit: int = Field(default=20, ge=1, le=200)


# -- Endpoints ────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    store = get_vector_store()
    return {"status": "ok", "parts_count": store.count()}


@app.post("/design")
async def design_endpoint(body: DesignPrompt) -> dict[str, Any]:
    """Full pipeline: natural language prompt -> assembled genetic circuit of any type."""
    try:
        if body.use_llm:
            result = design_circuit(body.prompt)
        else:
            from orchestration.planner import _fallback_parse
            spec = _fallback_parse(body.prompt)
            result = design_from_spec(spec)
        return result
    except Exception as e:
        logger.exception("Design failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/design/from-spec")
async def design_from_spec_endpoint(spec: CircuitSpec) -> dict[str, Any]:
    """Build a circuit from a structured CircuitSpec — for programmatic use."""
    try:
        return design_from_spec(spec)
    except Exception as e:
        logger.exception("Spec-based design failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/design/template")
async def design_from_template(body: TemplateRequest) -> dict[str, Any]:
    """Build a circuit from a named template with parameters."""
    factory = TEMPLATE_REGISTRY.get(body.template)
    if not factory:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template '{body.template}'. Available: {list(TEMPLATE_REGISTRY.keys())}",
        )
    try:
        params = {**body.params, "organism": body.organism}
        spec = factory(**params)
        return design_from_spec(spec)
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters for template '{body.template}': {e}")
    except Exception as e:
        logger.exception("Template design failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/templates")
async def list_templates():
    """List all available circuit templates and their expected parameters."""
    info = {
        "biosensor": {"params": ["target", "output", "organism"], "description": "Sensor -> regulator -> reporter"},
        "toggle_switch": {"params": ["inducer_a", "inducer_b", "output_a", "output_b", "organism"], "description": "Bistable switch with mutual repression"},
        "repressilator": {"params": ["organism"], "description": "Three-gene ring oscillator"},
        "logic_not": {"params": ["input_signal", "output", "organism"], "description": "Inverter gate"},
        "logic_and": {"params": ["input_a", "input_b", "output", "organism"], "description": "AND logic gate"},
        "kill_switch": {"params": ["trigger", "organism"], "description": "Conditional cell death circuit"},
        "metabolic_pathway": {"params": ["enzymes", "substrate", "product", "organism"], "description": "Multi-enzyme metabolic pathway"},
        "cascade": {"params": ["stages", "input_signal", "output", "organism"], "description": "Multi-stage signal amplification"},
    }
    return {"templates": info}


@app.get("/search")
async def search_endpoint(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    part_type: str | None = Query(None, description="Filter by part type"),
) -> list[dict]:
    """Semantic search across all biological parts."""
    return search_parts_raw(q, limit=limit, part_type=part_type)


@app.get("/search/sensors")
async def search_sensors(
    target: str = Query(..., description="Target molecule to detect"),
    limit: int = Query(5, ge=1, le=20),
) -> list[dict]:
    parts = find_sensor(target, limit=limit)
    return [p.model_dump() for p in parts]


@app.get("/search/reporters")
async def search_reporters(
    signal: str = Query(..., description="Desired output signal"),
    limit: int = Query(5, ge=1, le=20),
) -> list[dict]:
    parts = find_reporter(signal, limit=limit)
    return [p.model_dump() for p in parts]


@app.get("/search/regulators")
async def search_regulators(
    target: str = Query(..., description="Target molecule or sensor name"),
    limit: int = Query(5, ge=1, le=20),
) -> list[dict]:
    parts = find_regulator(target, limit=limit)
    return [p.model_dump() for p in parts]


@app.get("/parts/count")
async def parts_count() -> dict:
    store = get_vector_store()
    return {"count": store.count()}


@app.post("/ingest")
async def ingest_endpoint(body: IngestRequest) -> dict:
    """Trigger data ingestion from external biological databases."""
    from ingestion.ingest_addgene import ingest_addgene
    from ingestion.ingest_genbank import ingest_genbank
    from ingestion.ingest_igem import ingest_igem
    from ingestion.ingest_uniprot import ingest_uniprot

    store = get_vector_store()
    source_map = {
        "igem": ingest_igem,
        "genbank": ingest_genbank,
        "uniprot": ingest_uniprot,
        "addgene": ingest_addgene,
    }

    total = 0
    errors: list[str] = []
    for src in body.sources:
        fn = source_map.get(src)
        if not fn:
            errors.append(f"Unknown source: {src}")
            continue
        try:
            parts = list(fn(queries=body.queries, limit=body.limit))
            count = store.upsert_parts(parts)
            total += count
            logger.info("Ingested %d parts from %s", count, src)
        except Exception as e:
            logger.exception("Ingestion failed for %s", src)
            errors.append(f"{src}: {str(e)}")

    return {"ingested": total, "errors": errors}
