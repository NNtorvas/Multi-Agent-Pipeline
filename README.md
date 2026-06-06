# Multi-Agent Weather Analysis Pipeline

A production-style autonomous data analysis system built with **LangGraph**, **Claude**, **ChromaDB**, **Airflow**, **Streamlit**, and **PostgreSQL**.

---

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │              LangGraph State Machine                 │
                    │                 (PipelineState)                      │
                    │                                                      │
  Open-Meteo API    │  ┌────────────┐        ┌─────────────────┐          │
  ───────────────►  │  │ Data Agent │──────► │ Analysis Agent  │          │
                    │  │            │        │  (Claude API)   │          │
                    │  └────────────┘        └────────┬────────┘          │
                    │                                 │ analysis           │
                    │  ┌─────────────┐               │                    │
  PostgreSQL ◄───── │  │ Report Agent│◄──────────────┘                   │
  (store report)    │  │ (Claude API)│        ┌─────────────────┐         │
                    │  └─────────────┘◄────── │  Context Agent  │         │
                    │                         │ ChromaDB + ST   │         │
                    │                         └─────────────────┘         │
                    └─────────────────────────────────────────────────────┘
                                    ▲
                         ┌──────────┴──────────┐
                         │    Apache Airflow    │  @daily schedule
                         │    (pipeline_dag)    │  + REST API trigger
                         └──────────┬──────────┘
                                    │ triggers / reads DB
                         ┌──────────▼──────────┐
                         │   Streamlit UI       │  :8501
                         │  (reports table +    │
                         │   run-now button)    │
                         └─────────────────────┘
```

**Agent flow (strictly sequential):**
`data_agent` → `analysis_agent` → `context_agent` → `report_agent`

Each agent receives the full `PipelineState`, returns only the keys it mutates, and handles its own errors with a safe fallback value so the pipeline always completes.

---

## Quick Start

### 1. Prerequisites

- Docker Desktop ≥ 4.x
- An [Anthropic API key](https://console.anthropic.com/)
- Git Bash or WSL (required for `make` commands on Windows)

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set your ANTHROPIC_API_KEY
```

### 3. Install dev tools and set up git hooks

```bash
make install   # creates .venv, installs runtime + dev deps
make hooks     # installs pre-commit hooks (run once after clone)
```

### 4. Start all services

```bash
make up        # equivalent to: docker compose up --build
```

| Service | URL |
|---|---|
| Airflow UI | http://localhost:8080 (admin / admin) |
| Streamlit UI | http://localhost:8501 |
| PostgreSQL | localhost:5432 |

### 5. Run the pipeline

**Option A — via Streamlit:** open http://localhost:8501 and click **▶ Run Now**.

**Option B — via Airflow UI:** trigger `weather_analysis_pipeline` manually.

**Option C — locally (no Docker):**

```bash
make pipeline  # guards ANTHROPIC_API_KEY, then runs python main.py
```

Or without Make:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

---

## Project Structure

```
├── agents/
│   ├── data_agent.py       # Open-Meteo fetch with retry
│   ├── analysis_agent.py   # Claude trend/anomaly detection → JSON
│   ├── context_agent.py    # ChromaDB semantic search
│   └── report_agent.py     # Claude markdown synthesis
├── pipeline/
│   ├── state.py            # TypedDict PipelineState
│   └── graph.py            # LangGraph StateGraph + run_pipeline()
├── utils/
│   ├── claude_wrapper.py   # Shared Claude client, retry, token logging
│   ├── db.py               # PostgreSQL helpers
│   └── chroma_setup.py     # ChromaDB client + mock doc seeding
├── airflow_dags/
│   └── pipeline_dag.py     # @daily DAG → run_pipeline() → PostgreSQL
├── streamlit_app/
│   └── app.py              # Reports table, viewer, run-now trigger
├── scripts/
│   └── check_version_bump.py  # Pre-push semver gate (mirrors CD pipeline)
├── .github/
│   └── workflows/
│       ├── ci.yml          # Lint on every push + PR
│       ├── cd.yml          # CD orchestrator (push to main)
│       ├── _prep.yml       # Reusable: semver gate + git tag
│       └── _build-push.yml # Reusable: airflow + streamlit → GHCR
├── docker/
│   └── init.sql            # Creates airflow + pipeline databases
├── docker-compose.yml
├── Dockerfile.airflow
├── Dockerfile.streamlit
├── .dockerignore
├── .pre-commit-config.yaml
├── pyproject.toml          # Flake8 config (max-line-length=88)
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Dev tools: black, flake8, pre-commit, pytest
├── __version__.py          # Single source of truth for semver
├── Makefile                # Developer ergonomics (see make help)
└── main.py                 # Local CLI runner
```

Token usage is logged to `logs/token_usage.log` after every Claude call.

---

## Developer Tooling

All common tasks are wrapped in `make` targets (requires Git Bash or WSL on Windows):

```
make help        # show all targets
make install     # create .venv + install runtime & dev deps
make hooks       # install pre-commit hooks (once after clone)
make pipeline    # run locally (guards ANTHROPIC_API_KEY)
make up          # docker compose up --build
make down        # docker compose down
make logs        # tail all container logs
make format      # auto-format with Black
make check       # black --check + flake8 (same as CI)
make version     # print current version
make clean       # remove __pycache__, .pytest_cache, .pyc
```

### Pre-commit hooks

After `make hooks`, every commit runs: trailing-whitespace, end-of-file-fixer, Black, Flake8.  
Every push runs an additional version-bump gate — `__version__.py` must be bumped beyond the latest git tag before pushing to `main`.

---

## CI / CD

| Workflow | Trigger | What it does |
|---|---|---|
| **CI** | push (any branch) + PR | Lint & format check (`make check`) |
| **CD** | push to `main` | Validates semver bump → creates annotated git tag → builds + pushes Docker images to GHCR |

**Images published to GHCR:**
- `ghcr.io/{owner}/multi-agent-pipeline-airflow:{version}`
- `ghcr.io/{owner}/multi-agent-pipeline-streamlit:{version}`

Each image is tagged with the semver version, a short git SHA, and `latest` (on default branch).

---

## LangGraph State Machine Design — for Technical Interviewers

### Why LangGraph instead of a plain function chain?

A raw Python function chain would work for the happy path, but LangGraph gives us:

- **Typed state as a first-class citizen.** `PipelineState` is a `TypedDict` — every node has a statically-typed contract for what it reads and writes. This prevents the "bag of kwargs" anti-pattern common in ad-hoc agent pipelines and makes the data-flow self-documenting.
- **Explicit, inspectable edges.** Every transition is declared with `add_edge`. There is no implicit fallthrough; the graph can be visualised, tested in isolation, and extended (e.g., add a conditional branch to retry `analysis` if `anomaly_flag` is `True`) without touching any node code.
- **Separation of orchestration from logic.** Each node is a pure function `(state) → dict`. Swapping the LLM, changing the data source, or adding a caching layer requires editing one file, not untangling the orchestrator.

### Why sequential edges instead of conditional branching?

The four agents form a strict producer–consumer chain: each agent's output is the *only* meaningful input to the next. There is no branching logic that would justify `add_conditional_edges`. Keeping the graph linear maximises readability and makes the execution trace deterministic, which is important for debugging agentic systems in production.

### Error handling strategy: fail-soft, not fail-fast

Each node catches all exceptions, logs them with `logging.error`, appends a message to `state["errors"]`, and returns a **fallback value** so the next node always has something to work with. The final report reflects partial failures explicitly. This is intentional:

- A weather API timeout should not block the report — the report just says data was unavailable.
- A ChromaDB failure should not prevent Claude from synthesising the analysis it already has.
- Operators can see exactly which stage failed by inspecting `state["errors"]` or the Airflow task logs.

The alternative (raising exceptions to abort the graph) would produce no output and make root-cause analysis harder.

### Why a single `call_claude` wrapper?

All three Claude-powered agents import `call_claude` from `utils/claude_wrapper.py`. This gives a single place to:
- Enforce the model name (`claude-sonnet-4-20250514`)
- Apply the retry decorator (exponential back-off, max 3 attempts)
- Log every call's token consumption to `logs/token_usage.log`

Centralising this eliminates the risk of one agent silently using a different model or skipping retries.

### Retry decorator design

`retry` in `claude_wrapper.py` is a plain Python decorator (no LangChain dependency) that:
1. Retries up to `max_retries` times
2. Doubles the delay on each attempt (`base_delay * 2^attempt`)
3. Re-raises on the final attempt so the node's `except` block can produce the fallback

The same decorator is imported in `data_agent.py` for the HTTP fetch, so retry behaviour is consistent across the pipeline without duplicating code.
