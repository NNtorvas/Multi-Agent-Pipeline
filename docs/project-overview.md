# Multi-Agent Weather Analysis Pipeline — Technical Overview

## What It Does

An autonomous data analysis pipeline that runs on a daily schedule. It fetches live weather forecast data, passes it through four specialised AI agents, retrieves semantically similar historical events from a vector store, and produces a structured markdown report persisted in PostgreSQL. Reports are viewable — and new runs triggerable — through a Streamlit web UI.

---

## Architecture at a Glance

```
Open-Meteo API
      │
      ▼
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Data Agent │────►│ Analysis Agent   │────►│  Context Agent   │────►│ Report Agent │
│  (HTTP fetch│     │ (Claude: trends  │     │ (ChromaDB cosine │     │ (Claude: MD  │
│   + parse)  │     │  + anomalies)    │     │  similarity)     │     │  synthesis)  │
└─────────────┘     └──────────────────┘     └──────────────────┘     └──────┬───────┘
                                                        ▲                     │
                                             sentence-transformers            │
                                             all-MiniLM-L6-v2                │
                                                                    PostgreSQL│(reports table)
                                                                              │
                                                              ┌───────────────┘
                                                              │
                                                    ┌─────────▼──────────┐
                                                    │   Streamlit UI      │  :8501
                                                    │  (list + viewer +   │
                                                    │   ▶ Run Now button) │
                                                    └─────────────────────┘
                                                              │ REST API POST
                                                    ┌─────────▼──────────┐
                                                    │   Apache Airflow    │  :8080
                                                    │  @daily + manual    │
                                                    │  trigger via API    │
                                                    └─────────────────────┘
```

**State machine:** LangGraph `StateGraph` — four nodes, four unconditional edges, one shared `PipelineState` TypedDict.

---

## Tech Stack

| Layer | Technology | Key reason chosen |
|---|---|---|
| Agent orchestration | LangGraph 0.2+ | Explicit typed state machine; not an autonomous loop like LangChain agents |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) | Single wrapper enforces model, retry, token logging |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` | Local, free, 384-dim, no external API key |
| Vector store | ChromaDB (persistent) | Zero-config embedded DB; stable `PersistentClient` API |
| Pipeline database | PostgreSQL 15 | Multi-service concurrent access (Airflow + Streamlit); SQLite has write-lock issues |
| Scheduler | Apache Airflow 2.9 | Industry-standard; REST API allows Streamlit trigger; web UI for observability |
| UI | Streamlit | ~80 lines of Python for reports table + markdown viewer + trigger button |
| Containerisation | Docker Compose | 4-service stack (postgres, airflow-webserver, airflow-scheduler, streamlit) |
| CI/CD | GitHub Actions | Lint on every push; semver gate + GHCR image push on merge to main |

---

## Agent Responsibilities

| Agent | Input (from state) | Output (to state) | External call |
|---|---|---|---|
| `data_agent` | — | `weather_data` (7-day JSON) | Open-Meteo REST API |
| `analysis_agent` | `weather_data` | `analysis` (observations, anomaly flag, risk level) | Anthropic API |
| `context_agent` | `analysis.trend_summary` | `context_docs` (top-3 historical matches) | ChromaDB query |
| `report_agent` | all three above | `report` (markdown string) | Anthropic API |

Each agent writes **only the keys it modifies** back to state. LangGraph merges the partial dict — no agent spreads the full state.

---

## Component Connections

```
Airflow scheduler ──── triggers ──────────────────────► pipeline_dag.py
                                                              │
                                                     run_pipeline() [LangGraph]
                                                              │
                                             ┌────────────────┴────────────────┐
                                             │                                 │
                                        call_claude()                  chromadb.PersistentClient
                                        (claude_wrapper.py)            (chroma_db/ volume)
                                             │                                 │
                                      Anthropic API                 sentence-transformers
                                      logs → token_usage.log        (local model, no API)
                                             │
                                        save_report()
                                             │
                                        PostgreSQL (pipeline DB)
                                             │
                                        Streamlit ─── reads ──► reports table
                                        Streamlit ─── POST ───► Airflow REST API
                                                                /api/v1/dags/.../dagRuns
```

**Two databases, one Postgres instance:**
- `pipeline` DB → `reports` table (application data)
- `airflow` DB → Airflow metadata (DAG runs, task states)

**Shared volumes (host ↔ containers):**
- `./chroma_db` → Airflow + Streamlit containers (same vector store)
- `./agents`, `./pipeline`, `./utils` → Airflow containers (live code reload)

---

## Key Design Decisions

**Single `call_claude()` entry point** — all Claude calls go through `utils/claude_wrapper.py`. One place for model name, retry logic (exponential backoff, 3 attempts), and token logging.

**Fail-soft error handling** — every agent catches all exceptions, writes a fallback value to state, appends to `state["errors"]`, and continues. The pipeline always produces a report, even partial. This prevents an API timeout from silently killing the run.

**TypedDict state over plain dict** — IDE autocomplete, type-checking, and self-documenting field schema. LangGraph natively supports TypedDict for state merging.

**Pre-computed embeddings** — embeddings are computed with sentence-transformers and passed via `embeddings=` to ChromaDB, bypassing the built-in `embedding_function` parameter whose API changed between ChromaDB 0.4.x and 0.5.x.

**Single Airflow task** — the entire LangGraph graph runs inside one `PythonOperator`. Airflow handles scheduling and observability; LangGraph handles agent sequencing. Dual-orchestration (Airflow tasks per agent) would create conflicting retry and state management.

**`catchup=False`** — prevents Airflow from backfilling all daily runs since `start_date=2025-01-01` when first deployed.

---

## Running Locally

```bash
# One-time setup
make install          # creates .venv, installs deps
make hooks            # installs pre-commit hooks

# Local run (no Docker, no Postgres)
export ANTHROPIC_API_KEY=sk-ant-...
make pipeline

# Full Docker stack
export ANTHROPIC_API_KEY=sk-ant-...
make up               # builds images + starts all 4 services
# Airflow UI → http://localhost:8080  (admin / admin)
# Streamlit  → http://localhost:8501
make down -v          # stop + remove volumes (clean reset)
```

---

## Production Delta

| Area | Current (dev) | Production |
|---|---|---|
| Secrets | Shell env var | Vault / AWS Secrets Manager |
| Executor | LocalExecutor | CeleryExecutor / KubernetesExecutor |
| Vector DB | ChromaDB local | pgvector or Pinecone |
| Auth | Basic auth (admin/admin) | RBAC + SSO / OAuth |
| Logging | `logging.info` to stdout | Structured JSON → Datadog/Splunk |
| Async | Synchronous nodes | Async LangGraph nodes (I/O-bound) |
| Embeddings | Model loaded per run | Cached model server (Triton) |
| Monitoring | Token log file | Per-agent latency + cost in time-series DB |
