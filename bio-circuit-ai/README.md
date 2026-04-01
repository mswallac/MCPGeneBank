# Bio-Circuit AI

**Natural Language → Genetic Circuit Design** powered by LLM orchestration, biological database integration, and semantic vector search.

```
"Detect arsenic in water and glow green."

→  Sensor:    Pars arsenic-sensing promoter
   Regulator: ArsR transcription factor
   Reporter:  GFP (green fluorescent protein)

   Circuit:  Pars → ArsR → GFP → Terminator
```

---

## Architecture

```
User Prompt
     │
     ▼
┌──────────────────┐
│   LLM Planner    │  ← Parses NL → structured design parameters
│  (OpenAI GPT-4o) │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Biology Tools   │  ← Semantic retrieval of biological parts
│  Layer           │
└──┬─────┬─────┬───┘
   │     │     │
   ▼     ▼     ▼
Vector  Part  Sequence
Search  DB    DB
   │
   ▼
┌──────────────────┐
│ Circuit Assembler│  ← Rules-based assembly: Sensor → Regulator → Reporter
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Design Output   │  ← Structured JSON + explanation + sequences
└──────────────────┘
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI |
| Vector DB | Qdrant (with in-memory fallback) |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) |
| LLM | OpenAI GPT-4o (API-based) |
| Bio databases | iGEM Registry, NCBI GenBank, UniProt, Addgene |
| Data parsing | Biopython, BeautifulSoup, httpx |

## Project Structure

```
bio-circuit-ai/
│
├── api/
│   └── main.py              # FastAPI application with all endpoints
│
├── circuits/
│   └── circuit_builder.py    # Genetic circuit assembly logic
│
├── database/
│   └── vector_store.py       # Qdrant vector store abstraction
│
├── embeddings/
│   └── embed_parts.py        # Embedding generation pipeline
│
├── ingestion/
│   ├── ingest_igem.py        # iGEM Registry ingestion
│   ├── ingest_genbank.py     # NCBI GenBank ingestion
│   ├── ingest_uniprot.py     # UniProt protein database ingestion
│   └── ingest_addgene.py     # Addgene plasmid repository ingestion
│
├── models/
│   └── part.py               # Data models (BioPart, CircuitDesign, etc.)
│
├── orchestration/
│   └── planner.py            # LLM orchestration and planning layer
│
├── tools/
│   ├── search_parts.py       # General semantic part search
│   ├── sensors.py            # Sensor/detector part retrieval
│   ├── reporters.py          # Reporter gene retrieval
│   └── regulators.py         # Regulator/TF retrieval
│
├── config.py                 # Application configuration (env-based)
├── demo.py                   # Self-contained demo with seed data
├── run_ingestion.py          # Standalone ingestion runner
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
└── README.md
```

## Quick Start

### 1. Install Dependencies

```bash
cd bio-circuit-ai
pip install -r requirements.txt
```

### 2. Run the Demo (no external services needed)

The demo seeds an in-memory vector store with curated biological parts and runs example circuit designs:

```bash
python demo.py
```

Example output:

```
╭─ Bio-Circuit AI — Demo ─╮
│                          │
╰──────────────────────────╯

Seeded vector store with 12 biological parts.

╭─ Query 1: Detect arsenic in water and glow green ─╮
  Target molecule : arsenic
  Output signal   : green fluorescence
  Organism        : Escherichia coli

Circuit: Arsenic Green Fluorescence Biosensor

  [SENSOR      ]  Pars Arsenic Sensing Promoter  (BBa_K1031907)
  [RBS         ]  RBS B0034  (BBa_B0034)
  [REGULATOR   ]  ArsR Transcription Factor  (BBa_K1031311)
  [REPORTER    ]  GFP (Green Fluorescent Protein)  (BBa_E0040)
  [TERMINATOR  ]  Double Terminator B0015  (BBa_B0015)
```

### 3. Full Setup with Live Databases

```bash
# Copy and edit environment variables
cp .env.example .env
# Edit .env with your API keys

# Start Qdrant (Docker)
docker run -p 6333:6333 qdrant/qdrant

# Run data ingestion
python run_ingestion.py

# Start the API server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Use the API

```bash
# Design a circuit via natural language
curl -X POST http://localhost:8000/design \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Detect arsenic in water and glow green"}'

# Search for parts
curl "http://localhost:8000/search?q=arsenic+promoter&limit=5"

# Find sensors for a specific molecule
curl "http://localhost:8000/search/sensors?target=mercury"

# Find reporters for a signal type
curl "http://localhost:8000/search/reporters?signal=green+fluorescence"

# Trigger ingestion
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"sources": ["igem", "uniprot"], "queries": ["arsenic", "GFP"], "limit": 20}'

# Health check
curl http://localhost:8000/health
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/design` | Full NL → circuit design pipeline |
| `GET` | `/search` | Semantic search over all parts |
| `GET` | `/search/sensors` | Find sensor parts for a target molecule |
| `GET` | `/search/reporters` | Find reporter parts for an output signal |
| `GET` | `/search/regulators` | Find regulators for a target |
| `GET` | `/parts/count` | Count of parts in the vector store |
| `POST` | `/ingest` | Trigger data ingestion from bio databases |
| `GET` | `/health` | Health check with part count |

## Data Pipeline

### Ingestion Sources

| Source | Data Type | API |
|--------|----------|-----|
| **iGEM Registry** | Promoters, reporters, regulators, terminators, RBS | MediaWiki XML API |
| **NCBI GenBank** | Nucleotide sequences, gene annotations | Entrez E-utilities |
| **UniProt** | Proteins, transcription factors, enzymes | REST API (JSON) |
| **Addgene** | Plasmids, complete constructs | HTML scraping + API |

### Normalised Schema

Every part from every source is normalised into a common `BioPart` schema:

```json
{
  "part_id": "BBa_K1031907",
  "name": "Pars Arsenic Sensing Promoter",
  "type": "promoter",
  "organism": "Escherichia coli",
  "function": "Promoter responsive to arsenite ions",
  "sequence": "TTGACAAAA...",
  "description": "Arsenic-responsive promoter from the ars operon...",
  "references": ["https://parts.igem.org/Part:BBa_K1031907"],
  "source_database": "igem",
  "tags": ["arsenic", "metal sensing", "biosensor"]
}
```

### Embedding Pipeline

1. Each part's `name`, `type`, `function`, `description`, and `tags` are concatenated
2. The text is embedded using `all-MiniLM-L6-v2` (384-dim dense vectors)
3. Vectors are stored in Qdrant alongside the full part payload
4. Semantic search uses cosine similarity to find relevant parts

## Circuit Assembly Logic

The circuit builder follows standard genetic circuit architecture:

```
[Sensor Promoter] → [RBS] → [Regulator/TF] → [RBS] → [Reporter] → [Terminator]
```

Assembly rules:
1. **Sensor**: Promoter responsive to the target molecule
2. **RBS**: Ribosome binding site for translation initiation
3. **Regulator**: Transcription factor connecting sensor input to output
4. **Reporter**: Gene producing the desired output signal
5. **Terminator**: Transcription termination element

## LLM Orchestration

The planner operates in two phases:

1. **Parse**: LLM extracts structured parameters from the natural language prompt:
   - Target molecule
   - Desired output signal
   - Host organism
   - Constraints

2. **Explain**: After circuit assembly, the LLM generates a detailed scientific explanation covering the molecular mechanism, expected behaviour, and caveats.

A rule-based fallback parser handles requests when the LLM API is unavailable.

## Example Design Output

```json
{
  "circuit_name": "Arsenic Green Fluorescence Biosensor",
  "components": [
    {"role": "sensor", "part": "Pars Arsenic Sensing Promoter", "part_id": "BBa_K1031907"},
    {"role": "rbs", "part": "RBS B0034", "part_id": "BBa_B0034"},
    {"role": "regulator", "part": "ArsR Transcription Factor", "part_id": "BBa_K1031311"},
    {"role": "reporter", "part": "GFP", "part_id": "BBa_E0040"},
    {"role": "terminator", "part": "Double Terminator B0015", "part_id": "BBa_B0015"}
  ],
  "sequence": "TTGACAAAA...TTTATA",
  "explanation": "ArsR represses the Pars promoter. When arsenite binds ArsR, it dissociates from the promoter, enabling transcription of downstream GFP. Green fluorescence indicates arsenic presence."
}
```

## Configuration

All settings are loaded from environment variables (or a `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key for LLM |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `QDRANT_COLLECTION` | `bio_parts` | Qdrant collection name |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformer model |
| `LLM_MODEL` | `gpt-4o` | OpenAI model for planning |
| `NCBI_EMAIL` | — | Email for NCBI Entrez API |
| `NCBI_API_KEY` | — | Optional NCBI API key |

## Development

```bash
# Run API in development mode
uvicorn api.main:app --reload

# Run ingestion with specific sources
python run_ingestion.py --sources igem uniprot --queries "arsenic" "GFP" --limit 10

# Run in-memory mode (no Qdrant needed)
python run_ingestion.py --in-memory
```
