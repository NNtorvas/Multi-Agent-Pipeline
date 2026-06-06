# CLAUDE.md — Project Context for Claude Code

This file tells Claude Code about the project structure, conventions, and how to work
here effectively. Read this before making any changes.

---

## Project Summary

A multi-agent autonomous data analysis pipeline. Four LangGraph agents (data →
analysis → context → report) run sequentially, orchestrated by an Airflow DAG,
with results stored in PostgreSQL and displayed via Streamlit.

**Stack:** Python 3.11, LangGraph 0.2+, Anthropic SDK (direct), sentence-transformers,
ChromaDB, Airflow 2.9, Streamlit, PostgreSQL 15, Docker.

---

## Directory Layout

```
agents/          One file per LangGraph agent node
pipeline/        state.py (TypedDict) + graph.py (StateGraph)
utils/           claude_wrapper.py, db.py, chroma_setup.py
airflow_dags/    pipeline_dag.py — the @daily Airflow DAG
streamlit_app/   app.py — Streamlit UI
scripts/         check_version_bump.py — pre-push semver gate
docker/          init.sql — creates airflow + pipeline databases
docs/            design specs and implementation plans (superpowers/)
logs/            token_usage.log (auto-created, gitignored)
chroma_db/       ChromaDB persistence directory (auto-created, gitignored)
```

**Root-level tooling files:**

| File | Purpose |
|---|---|
| `Makefile` | Developer ergonomics — run `make help` |
| `__version__.py` | Single source of truth for semver (`0.1.0`) |
| `requirements.txt` | Runtime dependencies only |
| `requirements-dev.txt` | Dev tools: black, flake8, pre-commit, pytest |
| `pyproject.toml` | Flake8 config (`max-line-length = 88`, `extend-ignore = E203, W503`) |
| `.pre-commit-config.yaml` | Git hooks: hygiene + black + flake8 on commit; semver gate on push |
| `.dockerignore` | Excludes `.env`, `chroma_db/`, `logs/`, `.venv/`, etc. from Docker context |
| `.github/workflows/ci.yml` | CI: lint on every push + PR |
| `.github/workflows/cd.yml` | CD orchestrator: push to main → tag → GHCR |
| `.github/workflows/_prep.yml` | Reusable: semver gate + annotated git tag |
| `.github/workflows/_build-push.yml` | Reusable: builds airflow + streamlit images to GHCR in parallel |

---

## Environment Variables

Always read from environment — never hardcode.

| Variable | Required | Default (Docker) | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API access |
| `DATABASE_URL` | No | `postgresql://pipeline:pipeline@postgres:5432/pipeline` | Postgres connection |
| `AIRFLOW_BASE_URL` | No | `http://airflow-webserver:8080` | For Streamlit trigger |
| `AIRFLOW_USER` | No | `admin` | Airflow REST API auth |
| `AIRFLOW_PASS` | No | `admin` | Airflow REST API auth |

---

## Running the Project

### First-time setup (Git Bash / WSL)
```bash
make install   # creates .venv, installs runtime + dev deps
make hooks     # installs pre-commit hooks
```

### Local (no Docker)
```bash
make pipeline  # guards ANTHROPIC_API_KEY, then runs python main.py
# or manually:
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python main.py
```
Does not require PostgreSQL — skips DB save if `DATABASE_URL` is unset.

### Docker (full stack)
```bash
cp .env.example .env   # fill in ANTHROPIC_API_KEY
make up                # equivalent to: docker compose up --build
make logs              # tail all container logs
make down              # stop and remove all services
```
- Airflow UI: http://localhost:8080 (admin/admin)
- Streamlit: http://localhost:8501

### Code quality
```bash
make format    # auto-format with Black
make check     # black --check + flake8 (same as CI)
make version   # print current version from __version__.py
```

---

## Core Conventions

### All Claude calls go through `utils/claude_wrapper.py`
Never import `Anthropic` directly in agent files. Always use:
```python
from utils.claude_wrapper import call_claude
```
The wrapper handles: model name, retry logic, token logging. Do not duplicate this.

### Agent nodes return partial state dicts
Each agent returns only the keys it modifies:
```python
# Correct
return {"analysis": result, "status": "analysis_complete"}

# Wrong — don't spread the full state
return {**state, "analysis": result}
```

### Error handling: always fail soft
Every agent must catch all exceptions and return a fallback value. Do not let
exceptions propagate to the LangGraph runner. Pattern:
```python
try:
    result = do_work()
    return {"key": result, "status": "complete"}
except Exception as exc:
    logging.error("[agent_name] Failed: %s", exc)
    return {
        "key": FALLBACK_VALUE,
        "errors": state["errors"] + [f"agent_name: {exc}"],
        "status": "agent_name_failed",
    }
```

### Claude model name
Always `claude-sonnet-4-20250514`. It is hardcoded as `MODEL` in
`utils/claude_wrapper.py`. Do not pass a different model string to `call_claude`.

### Logging
Use `logging.info/warning/error` with `[module_name]` prefix:
```python
logging.info("[analysis_agent] Analysis complete")
logging.error("[db] Insert failed: %s", exc)
```
Do not use `print()` in pipeline code.

---

## Adding a New Agent

1. Create `agents/my_agent.py` with a `run_my_agent(state: PipelineState) -> dict` function
2. Add the node to `pipeline/graph.py`:
   ```python
   from agents.my_agent import run_my_agent
   graph.add_node("my_step", run_my_agent)
   graph.add_edge("context", "my_step")   # insert between existing nodes
   graph.add_edge("my_step", "report")
   ```
3. Add any new state fields to `pipeline/state.py`
4. Update the system prompt in `agents/report_agent.py` if the new agent produces
   data that should appear in the final report

---

## Modifying the LangGraph Graph

- All edges must be **explicit** — no implicit fallthrough
- Entry point is set via `graph.set_entry_point("data")`
- The graph terminates with `graph.add_edge("report", END)` from `langgraph.graph`
- After any structural change, `graph.compile()` in `build_pipeline()` will validate
  the graph — a `ValueError` from compile means a node or edge is misconfigured

---

## Database Schema

```sql
-- reports table (pipeline/utils/db.py init_db())
CREATE TABLE reports (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    report_markdown TEXT NOT NULL,
    status          VARCHAR(50) NOT NULL
);
```
`init_db()` is idempotent (`CREATE TABLE IF NOT EXISTS`). Call it before any write.

---

## ChromaDB Notes

- Collection name: `weather_history`
- Persisted to: `./chroma_db/` (bind-mounted in Docker)
- Auto-seeded with 5 mock documents on first run (when collection count == 0)
- Embeddings are pre-computed with `sentence-transformers all-MiniLM-L6-v2` and
  passed directly — do NOT use ChromaDB's built-in embedding_function parameter
  (API changed between 0.4.x and 0.5.x)
- If you have an existing ChromaDB from a RAG project, set `CHROMA_PATH` to point at
  it and change `COLLECTION_NAME` to match your existing collection

---

## Token Usage Log

All Claude API calls write to `logs/token_usage.log`:
```
2025-06-03T14:22:01Z | input=423 | output=187
```
The `logs/` directory is created automatically by `utils/claude_wrapper.py`.
Do not delete this file — it is the cost audit trail.

---

## Docker Notes

- Two databases in one Postgres instance: `pipeline` (reports) and `airflow` (metadata)
- `docker/init.sql` creates the `airflow` database on first container start
- Airflow webserver runs `airflow db migrate` before starting — scheduler waits for it
- Code changes on the host are immediately visible in containers via bind mounts
  (no rebuild needed for Python file changes)
- To rebuild after dependency changes: `docker-compose up --build`

---

## CI / CD Pipeline

### CI (`.github/workflows/ci.yml`)
Runs on every push and every PR. Installs only `requirements-dev.txt` (no heavy runtime deps) and runs `black --check --diff` + `flake8` across all source dirs. Fails fast on formatting or lint errors.

### CD (`.github/workflows/cd.yml` → `_prep.yml` → `_build-push.yml`)
Triggers on push to `main` only. Three-stage pipeline:
1. **`_prep.yml`** — extracts `__version__` via `ast.parse` (safe, no `exec`), validates it is strictly greater than the latest git tag, creates an annotated git tag and pushes it.
2. **`_build-push.yml`** — builds `Dockerfile.airflow` and `Dockerfile.streamlit` in parallel, pushes to GHCR as `multi-agent-pipeline-airflow:{version}` and `multi-agent-pipeline-streamlit:{version}`.

### Pre-commit hooks
Every commit: trailing-whitespace, end-of-file-fixer, Black, Flake8.
Every push: `scripts/check_version_bump.py` — must bump `__version__.py` beyond the latest git tag.

### Releasing a new version
1. Bump `__version__.py` (e.g. `"0.1.0"` → `"0.1.1"`)
2. Commit and push to `main`
3. CD pipeline auto-tags and publishes images

---

## What NOT to Change Without Discussion

- `utils/claude_wrapper.py` — changing the model string or retry parameters affects all agents
- `pipeline/state.py` — adding/removing fields requires updating every agent that reads them
- `docker/init.sql` — only runs on first postgres start; changes require volume teardown
- `graph.set_entry_point` and `add_edge(_, END)` — the graph must have exactly one entry point and one terminus
- `__version__.py` — read by the CD pipeline and pre-push hook; format must stay `__version__ = "X.Y.Z"`
- `pyproject.toml` — flake8 config here must stay in sync with Black's line length (88)
- `.github/workflows/_prep.yml` — semver gate logic; changes affect all releases
