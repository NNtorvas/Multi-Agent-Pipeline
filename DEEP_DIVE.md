# Multi-Agent Pipeline — Deep Dive Study Guide

This document walks through every architectural decision in the project, explains the
reasoning behind each technology choice, and presents the alternatives that were
considered and rejected. It is written for an engineer who wants to understand *why*
the system is built this way, not just *what* it does.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Technology Stack Decisions](#2-technology-stack-decisions)
3. [LangGraph State Machine — Deep Dive](#3-langgraph-state-machine--deep-dive)
4. [Agent Design — Each Node Explained](#4-agent-design--each-node-explained)
5. [The Claude Wrapper Layer](#5-the-claude-wrapper-layer)
6. [ChromaDB and Sentence-Transformers](#6-chromadb-and-sentence-transformers)
7. [PostgreSQL Persistence Layer](#7-postgresql-persistence-layer)
8. [Airflow Orchestration](#8-airflow-orchestration)
9. [Streamlit UI](#9-streamlit-ui)
10. [Docker Architecture](#10-docker-architecture)
11. [Error Handling Strategy](#11-error-handling-strategy)
12. [End-to-End Data Flow Walkthrough](#12-end-to-end-data-flow-walkthrough)
13. [What Would Change in a Production System](#13-what-would-change-in-a-production-system)

---

## 1. System Architecture Overview

### What is this system?

It is a **multi-agent data analysis pipeline**. "Multi-agent" means the work is split
across four specialised software agents, each responsible for one concern. An
orchestrator (LangGraph) routes state between them in a defined order.

The pipeline:
1. Fetches live weather forecast data from a free public API
2. Asks an LLM to analyse that data for trends and anomalies
3. Searches a vector database for semantically similar historical events
4. Asks an LLM to synthesise all of this into a markdown report
5. Persists the report in PostgreSQL
6. Exposes the reports through a web UI

### Why split into agents instead of one big function?

A single monolithic function `run_full_pipeline(...)` would work. But you lose:

- **Replaceability.** If you want to swap weather source from Open-Meteo to NOAA,
  you edit `data_agent.py` only. The other three agents are not touched.
- **Testability.** You can unit-test `run_analysis_agent` by passing a fake state with
  pre-baked weather data, completely bypassing the HTTP call.
- **Observability.** Each agent logs its own status. In Airflow you see which exact
  stage failed.
- **Composability.** Adding a 5th agent (e.g., a "send email" agent) means adding one
  node and one edge — zero changes to existing agents.

The cost is a small amount of boilerplate (each agent file, the state TypedDict). For a
portfolio project of this size that cost is worth paying to demonstrate good practices.

---

## 2. Technology Stack Decisions

### LangGraph — why not LangChain agents or CrewAI?

**LangChain agents** (ReAct, OpenAI functions, etc.) are designed for *autonomous*
tool-calling loops — the model decides what to call next. That adds unpredictability.
For a *deterministic* pipeline where the order is always the same, you don't want the
LLM to decide "should I call the weather API or the vector DB first?" The order is
business logic, not a model decision.

**CrewAI** is a higher-level framework that hides the state machine. It's good for rapid
prototyping but you have less control over exactly how state flows between agents, and
it has more magic. For a portfolio project, showing you understand the underlying graph
abstraction is more impressive than using a framework that wraps it.

**LangGraph** sits in the sweet spot: it is an explicit state machine (you control every
edge) built on top of LangChain's typed primitives. The graph is inspectable, testable,
and debuggable.

### Anthropic SDK directly — why not ChatAnthropic from LangChain?

`langchain-anthropic` provides a `ChatAnthropic` class that wraps the Anthropic SDK in
LangChain's `BaseMessage` interface. That abstraction is useful when you want to swap
providers (`ChatOpenAI` ↔ `ChatAnthropic`) or use LangChain's chain/pipe syntax.

We don't need any of that here. Our agents call Claude for specific structured tasks,
not as part of a LangChain chain. Using the Anthropic SDK directly:

- Fewer abstraction layers → easier to debug
- Direct access to `response.usage` for token logging
- No LangChain message format conversion
- Simpler code that a hiring manager can read quickly

The constraint "all Claude calls go through a single wrapper" replaces the need for
the LangChain abstraction — the wrapper IS the abstraction.

### Sentence-Transformers — why not OpenAI embeddings?

OpenAI's `text-embedding-3-small` is excellent but requires an API key and costs money
per call. `all-MiniLM-L6-v2` from sentence-transformers:

- Runs **locally** — no external API call for embeddings
- Free
- 384-dimensional vectors — small and fast
- Perfectly adequate for semantic search over a small corpus (5–50 docs)
- Demonstrates knowledge of open-source ML tooling

The trade-off: OpenAI embeddings are higher quality on complex text. For weather
documents the difference is negligible. The local model is the right choice here.

### ChromaDB — why not Pinecone, Weaviate, or pgvector?

**Pinecone/Weaviate** are managed cloud vector databases. They require accounts, API
keys, and network access. For a local dev project they add unnecessary complexity.

**pgvector** (vector extension for PostgreSQL) is a legitimate alternative and would
reduce the number of services (no separate ChromaDB process). The reason to prefer
ChromaDB here:

- ChromaDB is purpose-built for this use case — zero-config, embedded, no server
- The project brief says it already has a ChromaDB instance from a prior RAG project
- `chromadb.PersistentClient` stores data in a local directory (`chroma_db/`) that can
  be shared between local dev and Docker via a volume mount

In production you'd likely migrate to pgvector or a managed service to reduce
operational overhead.

### Airflow — why not Prefect, Dagster, or a simple cron job?

A **cron job** (`0 8 * * * python main.py`) is the simplest scheduler but gives you no
UI, no retry logic, no task-level logs, and no way to manually trigger from a web
interface.

**Prefect and Dagster** are excellent modern alternatives to Airflow. They have better
developer experience and first-class Python support. Airflow was chosen here because:
- It is the industry standard at most companies with data teams
- Portfolio projects that show Airflow knowledge signal readiness for enterprise roles
- The Airflow REST API (used by the Streamlit "Run Now" button) is well-documented and
  stable

The practical trade-off: Airflow is heavyweight (webserver + scheduler + database). For
a pipeline this simple, Prefect would be a lighter fit. But the portfolio signal matters.

### Streamlit — why not FastAPI + React?

A **FastAPI + React** stack would be more production-realistic but would add hundreds of
lines of TypeScript, a node.js build step, and a separate frontend container. Streamlit
delivers the same user-facing functionality (table of reports, markdown viewer, trigger
button) in ~80 lines of Python.

For a data engineering portfolio project, Streamlit is the accepted shorthand for
"I can build a data UI quickly." It signals Python fluency without suggesting you don't
know about proper frontends.

### PostgreSQL — why not SQLite?

SQLite is file-based and perfect for single-process use. The problem:

- Airflow (webserver) and Streamlit are two separate processes/containers
- Both need concurrent read/write access to the `reports` table
- SQLite has a write-lock that makes concurrent access unreliable

PostgreSQL is the standard choice when multiple services share a database.

---

## 3. LangGraph State Machine — Deep Dive

### The TypedDict State

```python
# pipeline/state.py
class PipelineState(TypedDict):
    weather_data: Optional[dict]
    analysis: Optional[dict]
    context_docs: Optional[list]
    report: Optional[str]
    errors: list
    status: str
```

`TypedDict` was chosen over a plain `dict` or a Pydantic model for these reasons:

**vs plain dict:**
- IDEs provide autocomplete and type-checking on state fields
- Mypy catches `state["wether_data"]` (typo) at analysis time, not runtime
- The schema serves as documentation — any engineer can read `state.py` and understand
  what travels through the pipeline

**vs Pydantic BaseModel:**
- LangGraph's `StateGraph` natively supports `TypedDict` — it uses the type hints to
  understand the state schema
- Pydantic models add validation overhead that we don't need inside the pipeline
- Pydantic is better for external API boundaries (FastAPI request/response), not internal
  state

**vs dataclass:**
- `TypedDict` is structurally typed — you can create it with a plain dict literal, which
  LangGraph does internally when merging partial updates from nodes

### How LangGraph merges state

This is the most important thing to understand about LangGraph:

```python
# A node returns ONLY the keys it changes
def run_data_agent(state: PipelineState) -> dict:
    data = _fetch_weather()
    return {"weather_data": data, "status": "data_complete"}
    # Does NOT return analysis, context_docs, report, errors
```

LangGraph takes this partial dict and **merges** it into the current state. The next
node receives a `PipelineState` with `weather_data` filled in but `analysis` still
`None` (its initial value). This is the reducer pattern.

The alternative (returning `{**state, "weather_data": data}`) would also work but
produces unnecessary data in the return value and hides which keys the node actually
modifies.

**The merge is shallow by default.** For the `errors` list, we must build the new list
explicitly:

```python
# This REPLACES the list (correct — we compute the new value ourselves)
return {"errors": state["errors"] + [f"data_agent: {exc}"]}

# This would also replace (LangGraph doesn't know to append)
return {"errors": ["new error"]}  # drops previous errors!
```

LangGraph does support custom reducers via `Annotated[list, operator.add]` in the
`TypedDict`, but for a pipeline this simple, explicit list concatenation is clearer.

### The Graph Definition

```python
# pipeline/graph.py
graph = StateGraph(PipelineState)

graph.add_node("data",     run_data_agent)
graph.add_node("analysis", run_analysis_agent)
graph.add_node("context",  run_context_agent)
graph.add_node("report",   run_report_agent)

graph.set_entry_point("data")
graph.add_edge("data",     "analysis")
graph.add_edge("analysis", "context")
graph.add_edge("context",  "report")
graph.add_edge("report",   END)
```

**Why `set_entry_point` instead of `add_edge(START, "data")`?**

Both work in LangGraph 0.2.x. `set_entry_point` is slightly more readable when there is
exactly one starting node. `START` is preferred in newer versions when you want to
explicitly show the graph starts at the `START` sentinel node, especially if you have
multiple potential entry points (via conditional edges from `START`).

**What `graph.compile()` does:**

`compile()` validates the graph (no dangling nodes, all edges valid), builds the
execution plan, and returns a `CompiledGraph` object with an `.invoke()` method. The
compiled graph is a Pregel-style actor system under the hood — each node is an "actor"
that processes state and emits an update.

### Conditional edges — what they look like and when to use them

This project uses only unconditional edges. Here is what a conditional edge would look
like, for reference:

```python
def route_after_data(state: PipelineState) -> str:
    if state["weather_data"] and state["weather_data"].get("days"):
        return "analysis"   # normal path
    return "report"         # skip to report with fallback data

graph.add_conditional_edges(
    "data",
    route_after_data,
    {"analysis": "analysis", "report": "report"},
)
```

This pattern is appropriate when a node's failure should change the graph's execution
path. We chose NOT to use it because:

1. Each agent already handles its own failure with a fallback value
2. Skipping analysis also skips context retrieval — the report would have less
   information, not more reliability
3. Unconditional edges produce the same report quality (fallback analysis is still
   usable) with simpler graph logic

---

## 4. Agent Design — Each Node Explained

### data_agent.py

**Responsibility:** Fetch 7-day weather forecast from Open-Meteo and return a
structured JSON summary.

**Why Open-Meteo?** Free, no API key, no rate limit for reasonable usage, returns clean
JSON. The alternative (OpenWeatherMap) requires registration. The goal is zero setup
friction.

**What the API returns:**

```json
{
  "daily": {
    "time": ["2025-06-03", "2025-06-04", ...],
    "temperature_2m_max": [22.1, 24.3, ...],
    "temperature_2m_min": [14.2, 15.1, ...],
    "precipitation_sum": [0.0, 2.3, ...],
    "windspeed_10m_max": [18.4, 22.1, ...]
  }
}
```

The agent transforms this into a list of day-objects so downstream agents don't need to
know the Open-Meteo response schema:

```python
days = [
    {
        "date": "2025-06-03",
        "temp_max": 22.1,
        "temp_min": 14.2,
        "precipitation": 0.0,
        "windspeed_max": 18.4,
    },
    ...
]
```

**Retry placement:** The `@retry` decorator is on `_fetch_weather()` (the private
function that makes the HTTP call), not on `run_data_agent()` (the LangGraph node). This
means retries happen inside the try/except block — if all 3 retries fail, the exception
is caught and a fallback value is returned. If the decorator were on the node function
itself, exceptions would propagate to LangGraph.

### analysis_agent.py

**Responsibility:** Send the weather JSON to Claude and get back a structured analysis
with at least 3 observations and 1 anomaly assessment.

**Why ask Claude for structured JSON output?**

Claude is better at detecting nuanced patterns (e.g., "temperatures drop 8°C on day 4
while precipitation spikes — consistent with a frontal passage") than a rule-based
system. The analysis is qualitative intelligence, not just threshold checks.

**The system prompt strategy:**

```
You are a meteorological data analyst. Given a 7-day weather forecast as JSON,
respond with ONLY valid JSON matching this exact schema — no markdown fences, no prose:
{
  "observations": [...],
  "anomaly_flag": <boolean>,
  ...
}
```

Key decisions in this prompt:
- "ONLY valid JSON" + "no markdown fences" prevents Claude from wrapping its response
  in ```json ... ``` which would break `json.loads()`
- Specifying the exact schema (with types) reduces hallucinated fields
- "at least 3 distinct items" in observations forces the model to think beyond one
  obvious pattern

**Why `json.loads()` instead of a structured output library?**

The Anthropic SDK supports tool use / structured output via `tools` parameter. That
approach is more robust but more verbose. For this project, instructing Claude to return
raw JSON and parsing it is simpler and works reliably with a well-crafted system prompt.

In production you would use the SDK's structured output feature:

```python
# Production approach (not used here for simplicity)
response = client.messages.create(
    model=MODEL,
    tools=[{"name": "record_analysis", "input_schema": AnalysisSchema.model_json_schema()}],
    tool_choice={"type": "tool", "name": "record_analysis"},
    ...
)
analysis = response.content[0].input  # guaranteed to match schema
```

### context_agent.py

**Responsibility:** Convert the analysis into a semantic query and retrieve the 3 most
relevant historical weather events from ChromaDB.

**The retrieval query:**

```python
query_text = (
    analysis.get("trend_summary")
    or (analysis.get("observations") or ["weather patterns"])[0]
)
```

This priority order matters:
1. `trend_summary` is a single coherent sentence — the best query
2. `observations[0]` is a fallback if trend_summary is empty
3. `"weather patterns"` is a last-resort default if the analysis is completely empty

Using `trend_summary` as the query is a form of **query reformulation** — instead of
querying with raw weather numbers, we query with the semantic interpretation of those
numbers. This produces much better retrieval results.

**Example:**

- Raw query: `"temp_max 28.5, temp_min 18.2, precipitation 12.3"`
- Semantic query: `"Warm temperatures with significant rainfall in the forecast period"`

The semantic query matches historical documents about summer storms much better.

**ChromaDB query mechanics:**

```python
query_embedding = embedder.encode([query_text]).tolist()  # shape: (1, 384)
results = collection.query(query_embeddings=query_embedding, n_results=3)
# results["documents"] = [["doc1 text", "doc2 text", "doc3 text"]]
```

ChromaDB computes cosine similarity between the query embedding and all stored document
embeddings, returning the top-k closest documents. The double-list structure
(`results["documents"][0]`) is because `query` supports batching — `[0]` is the result
for the first (and only) query.

### report_agent.py

**Responsibility:** Take all three previous outputs and synthesise a coherent markdown
report.

**Prompt structure:**

```
**7-Day Forecast (Paris):**
[raw day-by-day JSON]

**Automated Analysis:**
[observations, anomaly_flag, trend_summary, risk_level]

**Relevant Historical Events from Knowledge Base:**
- [retrieved doc 1]
- [retrieved doc 2]
- [retrieved doc 3]
```

This structure feeds Claude all the information it needs without redundancy. The system
prompt constrains the output to exactly four sections so the markdown is always
predictable for rendering in Streamlit.

**Why include the raw forecast data in the report prompt?**

The analysis agent already interpreted the data, so why pass the raw data again? Because
Claude can make connections the analysis agent might have missed. For example, the
analysis might note "high precipitation on day 3" but Claude generating the report
might connect that to the historical context document about agricultural frost damage
and add a recommendation that wasn't in the analysis output.

---

## 5. The Claude Wrapper Layer

### Why a wrapper at all?

Three agents call Claude. Without a wrapper, each would:
1. Create its own `Anthropic()` client
2. Implement its own retry logic (or not)
3. Log tokens (or not) with varying formats

A single `call_claude()` function in `utils/claude_wrapper.py` enforces:
- One client instance (lazy singleton via `_client` global)
- Consistent retry behaviour (same max_retries, same backoff formula)
- Complete token audit trail in one file

### The retry decorator

```python
def retry(max_retries: int = 3, base_delay: float = 1.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_retries - 1:
                        raise              # propagate on final attempt
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
        return wrapper
    return decorator
```

**Backoff schedule (base_delay=1.0):**

| Attempt | Delay before retry |
|---|---|
| 1 (first failure) | 1s |
| 2 | 2s |
| 3 | raises |

Total worst-case wait: 3 seconds before re-raising.

**Why exponential backoff?** API rate limits and transient server errors tend to resolve
within a few seconds. Exponential backoff reduces thundering-herd pressure — if 10 DAG
runs are retrying simultaneously, staggering delays prevents all of them hitting the API
at the same moment.

**Why `functools.wraps`?** Without it, the wrapped function loses its `__name__` and
`__doc__`. This matters for logging (the warning message uses `func.__name__`) and for
introspection tools that read function metadata.

### Token logging

```python
def _log_tokens(usage) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(_TOKEN_LOG, "a") as f:
        f.write(f"{ts} | input={usage.input_tokens} | output={usage.output_tokens}\n")
```

This appends to `logs/token_usage.log`. A typical session produces entries like:

```
2025-06-03T14:22:01Z | input=423 | output=187
2025-06-03T14:22:04Z | input=612 | output=341
```

**Why file-based logging instead of a database?**

Token logs are write-heavy, append-only, and rarely queried. A flat file is the right
data structure. In production you'd ship these to a time-series database (Prometheus,
InfluxDB) or a cost-tracking service.

---

## 6. ChromaDB and Sentence-Transformers

### How the embedding pipeline works

`sentence-transformers` converts text into dense vectors:

```python
model = SentenceTransformer("all-MiniLM-L6-v2")
text = "Record high temperatures expected in Paris this week"
vector = model.encode(text)  # numpy array of shape (384,)
```

The vector encodes semantic meaning — texts with similar meaning produce vectors with
high cosine similarity, regardless of exact word overlap. So:

- "unseasonably warm temperatures" ↔ "heat above seasonal norms" → high similarity
- "warm weather" ↔ "fiscal year deficit" → low similarity

**Why `all-MiniLM-L6-v2`?**

- "all" prefix: trained on a broad dataset (not domain-specific)
- "MiniLM": distilled architecture — 6 layers, much smaller than BERT
- "L6": 6 transformer layers
- "v2": second version of the model

It produces 384-dimensional vectors (vs 768 for full BERT). Smaller vectors mean:
- Faster encoding
- Smaller storage in ChromaDB
- Faster similarity search

Quality trade-off is minimal for this use case.

### ChromaDB persistence

```python
client = chromadb.PersistentClient(path=CHROMA_PATH)
```

`PersistentClient` stores all vectors and documents in a directory (`chroma_db/`).
Compare to `chromadb.Client()` (in-memory, lost on restart).

The `chroma_db/` directory is:
- Bind-mounted into both the Airflow and Streamlit containers via Docker volumes
- Checked into `.gitignore` (large binary files)
- Reused from an existing RAG project if present

**The mock document seeding:**

```python
if collection.count() == 0:
    embeddings = embedder.encode(MOCK_DOCUMENTS).tolist()
    collection.add(documents=MOCK_DOCUMENTS, embeddings=embeddings, ids=[...])
```

`collection.count() == 0` is an idempotency guard — seeds only on first run. This
pattern is standard for bootstrapping vector databases.

**Why pass pre-computed embeddings instead of using ChromaDB's built-in embedding function?**

ChromaDB supports custom `EmbeddingFunction` classes, but the interface changed between
versions 0.4.x and 0.5.x, creating compatibility fragility. Passing pre-computed
embeddings via `embeddings=` parameter is stable across all versions. The trade-off:
you must compute embeddings yourself before calling `collection.add()`, which is one
extra line of code.

---

## 7. PostgreSQL Persistence Layer

### Schema design

```sql
CREATE TABLE IF NOT EXISTS reports (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    report_markdown TEXT NOT NULL,
    status          VARCHAR(50) NOT NULL
);
```

**`SERIAL PRIMARY KEY`:** Auto-incrementing integer. Simple, sufficient, no UUID
overhead for an internal table.

**`TIMESTAMP WITH TIME ZONE`:** Stores UTC offset. When the Airflow scheduler runs in a
container with `TZ=UTC` and Streamlit displays the timestamp, there is no ambiguity
about which timezone the timestamp is in.

**`TEXT` for report_markdown:** PostgreSQL `TEXT` has no length limit. `VARCHAR(n)` with
a fixed limit would risk truncating long reports. `TEXT` is the right type for
arbitrary-length string data.

### The context manager pattern

```python
@contextmanager
def _conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

**Why `contextmanager` instead of just calling `conn.close()` explicitly?**

`contextmanager` guarantees cleanup even if the caller raises an exception. The pattern:
- `commit()` on success
- `rollback()` + re-raise on failure
- `close()` always (even if rollback raised)

This prevents connection leaks and partial writes.

**Alternative: connection pooling (SQLAlchemy, psycopg2 pool)**

Each call to `_conn()` opens a new TCP connection to PostgreSQL. For high-frequency
workloads this is expensive. For a once-per-day pipeline it is completely fine. A
connection pool (e.g., `psycopg2.pool.SimpleConnectionPool`) would be warranted if
the Streamlit UI was serving hundreds of concurrent users.

---

## 8. Airflow Orchestration

### DAG structure

```python
with DAG(
    dag_id="weather_analysis_pipeline",
    schedule_interval="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as dag:
    run_task = PythonOperator(
        task_id="run_pipeline",
        python_callable=_run_analysis_pipeline,
    )
```

**Single task DAG:** The entire LangGraph pipeline runs inside one `PythonOperator`.
An alternative design would map each LangGraph agent to its own Airflow task:

```
open_meteo_task >> analysis_task >> context_task >> report_task >> save_task
```

**Why not do that?** Because LangGraph is already the orchestrator. Having Airflow also
orchestrate the individual steps creates dual-orchestration — two systems both trying
to handle retries and state. The rule is: **pick one orchestrator per level of
granularity**.

- Airflow orchestrates: when to run, DAG-level retries, monitoring
- LangGraph orchestrates: agent sequencing, state sharing, agent-level error handling

**`catchup=False`:** With `start_date=2025-01-01`, if Airflow starts today it would try
to backfill every daily run from January 2025. `catchup=False` prevents this — only
future scheduled runs execute. Always set this unless backfilling is intentional.

**`sys.path` injection:**

```python
sys.path.insert(0, str(Path(__file__).parent.parent))
```

This adds `/opt/airflow` (the project root inside the container) to the Python path,
making `from pipeline.graph import run_pipeline` work. This is a common pattern in
Airflow DAG files when the DAGs folder is not the project root.

### Airflow REST API trigger

The Streamlit "Run Now" button calls:

```
POST http://airflow-webserver:8080/api/v1/dags/weather_analysis_pipeline/dagRuns
Authorization: Basic admin:admin
Content-Type: application/json
{"conf": {}, "dag_run_id": "manual_20250603T142201"}
```

This is the Airflow stable REST API (v1, available since Airflow 2.0). The response
includes the `dag_run_id` which Streamlit shows in a toast notification.

**Security note:** Basic auth over HTTP is fine for local development but must be
replaced with token auth or OAuth over HTTPS in production.

---

## 9. Streamlit UI

### State management with `st.session_state`

```python
if c_btn.button("View", key=f"view_{report_id}"):
    st.session_state["selected"] = report_id
```

Streamlit re-runs the entire script on every user interaction. `session_state` is a
server-side dict that persists between reruns for the same user session. Without it,
clicking "View" would select the report but the selection would be lost when the script
re-runs.

**Why `key=f"view_{report_id}"` on buttons?** Streamlit requires unique keys for
interactive elements. Without unique keys, all "View" buttons would be the same
widget and only the first one would respond.

### The `init_db()` call in app.py

```python
try:
    init_db()
except Exception:
    pass
```

The `try/except` is intentional. If the database is not yet available (e.g., Streamlit
starts before PostgreSQL is healthy), the app should still load — it will show an empty
reports table rather than crashing. The actual error is handled when `get_all_reports()`
is called.

### Why not cache the database queries with `@st.cache_data`?

`@st.cache_data` would cache query results across reruns, preventing seeing new reports
until the cache expires. For a reporting dashboard where users expect to see the latest
data, caching query results is the wrong default. The database calls are fast (simple
`SELECT`) so caching provides little benefit.

---

## 10. Docker Architecture

### Service dependency graph

```
postgres (healthcheck: pg_isready)
    └── airflow-webserver (waits: postgres healthy)
            └── airflow-scheduler (waits: webserver healthy)
    └── streamlit (waits: postgres healthy)
```

**Why does the scheduler wait for the webserver?** The webserver runs `airflow db
migrate` (creates Airflow's metadata tables) before starting. If the scheduler starts
before migration completes, it will fail trying to read from non-existent tables.

**Health checks:**

```yaml
postgres:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U pipeline"]
```

`pg_isready` checks that PostgreSQL is accepting TCP connections, not just that the
container is running. The container starts fast but PostgreSQL takes a few seconds to
initialize. `service_healthy` in `depends_on` waits for the health check to pass.

### Shared volumes

```yaml
x-airflow-volumes: &airflow-volumes
  - ./airflow_dags:/opt/airflow/dags
  - ./agents:/opt/airflow/agents
  - ./pipeline:/opt/airflow/pipeline
  - ./utils:/opt/airflow/utils
  - ./chroma_db:/opt/airflow/chroma_db
```

The YAML anchor `&airflow-volumes` with alias `*airflow-volumes` avoids duplicating
the volume list between webserver and scheduler. Both containers need the same mounts.

**Why bind mounts instead of `COPY` in the Dockerfile?**

Bind mounts (host path → container path) mean code changes on the host are immediately
visible inside the container without rebuilding the image. This is the standard dev
workflow. In production, you'd `COPY` the code into the image for immutability.

### The two-database setup

```sql
-- docker/init.sql (runs on first postgres start)
CREATE DATABASE airflow;
GRANT ALL PRIVILEGES ON DATABASE airflow TO pipeline;
```

One PostgreSQL instance, two databases:
- `pipeline`: stores `reports` table (our application data)
- `airflow`: stores Airflow's metadata (DAG runs, task states, logs)

`docker-entrypoint-initdb.d/` scripts run automatically when the container first starts
(when the data volume is empty). On subsequent starts they are skipped because the
volume already has data.

---

## 11. Error Handling Strategy

### The fail-soft philosophy

Every agent wraps its core logic in a try/except:

```python
def run_data_agent(state: PipelineState) -> dict:
    try:
        data = _fetch_weather()
        return {"weather_data": data, "status": "data_complete"}
    except Exception as exc:
        return {
            "weather_data": {"location": "Paris, France", "days": [], "error": str(exc)},
            "errors": state["errors"] + [f"data_agent: {exc}"],
            "status": "data_failed",
        }
```

**Three things happen on failure:**
1. A usable fallback value is written to the state key (`"days": []` instead of `None`)
2. The error message is appended to `state["errors"]` (accumulated, not overwritten)
3. `status` is set to a failure code — operators can alert on this

**Why not raise and let LangGraph handle it?**

If a node raises an unhandled exception, LangGraph (in its default configuration)
propagates the exception to the caller (`.invoke()`), which would cause the Airflow task
to fail with no output. You'd have no report, no error context in the database, and no
information about which stage failed.

The fail-soft pattern always produces a report. A "partial failure" report that says
"weather data unavailable" is more useful to an operator than a stack trace in a log
file.

**Accumulated errors:**

```python
"errors": state["errors"] + [f"analysis_agent: {exc}"]
```

If both data_agent and analysis_agent fail, the final state contains:

```python
{
    "errors": ["data_agent: Connection timeout", "analysis_agent: Invalid JSON"],
    "status": "analysis_failed"
}
```

The Airflow task logs both errors. The saved report reflects both failures.

---

## 12. End-to-End Data Flow Walkthrough

Here is what happens on a single pipeline invocation, traced step by step:

**T+0: Airflow scheduler fires `weather_analysis_pipeline`**

The `_run_analysis_pipeline` Python callable is invoked.

**T+0.1: `init_db()` called**

```sql
CREATE TABLE IF NOT EXISTS reports (...);
```

Idempotent — does nothing if the table exists.

**T+0.2: `run_pipeline()` called**

LangGraph creates the initial state:
```python
{
    "weather_data": None, "analysis": None,
    "context_docs": None, "report": None,
    "errors": [], "status": "started"
}
```

**T+0.3: `data` node executes**

`_fetch_weather()` makes an HTTP GET to:
```
https://api.open-meteo.com/v1/forecast?latitude=48.8566&longitude=2.3522&daily=...
```

Response arrives in ~200ms. State is updated:
```python
{
    "weather_data": {
        "location": "Paris, France",
        "retrieved_at": "2025-06-03T07:00:00",
        "days": [{"date": "2025-06-03", "temp_max": 23.1, ...}, ...]
    },
    "status": "data_complete"
}
```

**T+0.5: `analysis` node executes**

The 7-day JSON is sent to Claude with the analysis system prompt.
Claude returns:
```json
{
  "observations": [
    "Temperatures rise progressively from 23°C to 29°C across the week.",
    "Significant precipitation event on day 4 with 18mm, linked to temperature drop.",
    "Wind speeds remain moderate (15–22 km/h) throughout the period."
  ],
  "anomaly_flag": true,
  "anomaly_description": "Day 4 temperature drops 7°C within 24 hours — consistent with a cold front passage.",
  "trend_summary": "Warm early week with a cold frontal system passing midweek.",
  "risk_level": "medium"
}
```

State is updated with this analysis. Token usage is logged.

**T+3: `context` node executes**

`trend_summary` = `"Warm early week with a cold frontal system passing midweek."`
is encoded into a 384-dimensional vector and queried against ChromaDB.

Top 3 retrieved documents:
1. "Spring 2024 featured extreme 48-hour temperature swings..."
2. "The summer 2023 Mediterranean heatwave pushed temperatures to 47°C..."
3. "January 2024 recorded unusually high temperatures across Europe..."

State updated with `context_docs`.

**T+3.5: `report` node executes**

All three outputs are assembled into the prompt. Claude generates:

```markdown
## Summary
A warm early-week period for Paris transitions into cooler, wetter conditions
mid-week due to an approaching cold front. Risk is assessed as medium.

## Key Findings
- Temperatures peak at 29°C on day 3 before dropping 7°C on day 4
- 18mm precipitation event on day 4 represents a significant frontal passage
- Wind speeds escalate ahead of the frontal boundary (day 3–4)

## Historical Context
- Spring 2024 saw similar rapid temperature swings in central Europe causing
  agricultural frost damage — comparable frontal dynamics observed
- The 2023–2024 El Niño period increased frequency of such frontal passages

## Recommended Actions
- Issue agricultural advisory for frost risk following cold front
- Monitor flood risk in low-lying Seine areas given 18mm precipitation forecast
- Advise commuters of wind disruption on day 3–4
```

**T+6: `save_report()` called**

```sql
INSERT INTO reports (report_markdown, status) VALUES ($1, $2) RETURNING id;
-- returns id=1
```

**T+6.1: XCom push**

`ti.xcom_push(key="report_id", value=1)` — the report ID is stored in Airflow's XCom
system, making it available to downstream tasks if any were added later.

**Total wall time:** ~6–8 seconds (dominated by two Claude API calls of ~1–3s each).

---

## 13. What Would Change in a Production System

Understanding the gaps between a portfolio project and production is valuable for
interviews. Here is an honest list:

### Secrets management
`.env` file → **HashiCorp Vault** or **AWS Secrets Manager**. Never store API keys in
environment variables that land in container logs.

### Structured logging
`logging.info(...)` → **structured JSON logs** shipped to Datadog/Splunk:
```json
{"ts": "2025-06-03T14:22Z", "agent": "analysis", "status": "complete", "tokens": 510}
```

### Async execution
LangGraph supports async node functions. For I/O-bound agents (HTTP, DB, API calls),
async execution would reduce wall time from ~7s to ~3s by parallelising the Claude
calls.

### Vector database scaling
ChromaDB local → **pgvector** (if already on Postgres) or **Pinecone/Weaviate** for
millions of documents.

### Airflow production setup
- LocalExecutor (single machine) → **CeleryExecutor** or **KubernetesExecutor**
- SQLite metadata → **PostgreSQL** (already done here)
- Single admin user → **RBAC with LDAP/SSO**

### Report quality evaluation
Add a 5th agent or post-processing step that evaluates report quality with a rubric
(completeness, accuracy, actionability) and flags low-quality reports for human review.

### Monitoring
Track per-run metrics (token cost, latency per agent, anomaly flag rate) in a time-series
database and alert when cost exceeds a threshold or latency degrades.

### Testing
- Unit tests: mock `_fetch_weather` and `call_claude`, test each agent with fixture states
- Integration tests: run the full pipeline against real APIs in a test environment
- Contract tests: validate that Claude's JSON output matches the expected schema

---

*End of Deep Dive — built for study and interview preparation.*
