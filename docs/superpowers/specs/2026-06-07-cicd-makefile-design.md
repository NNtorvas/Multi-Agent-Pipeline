# CI/CD & Makefile — Design Spec

**Date:** 2026-06-07
**Status:** Approved
**Approach:** B — Faithful adoption of RAG-QA-SYSTEM + ML-Monitoring-Platform gold standard, plus pipeline-specific targets

---

## Goal

Bring Multi-Agent-Pipeline to the same CI/CD and developer-tooling standard as the two reference repos in the portfolio. Every file mirrors the established pattern exactly, adapted only for this project's names and structure.

---

## File Inventory

```
Multi-Agent-Pipeline/
├── Makefile                              NEW
├── __version__.py                        NEW  (root)
├── requirements.txt                      UNCHANGED  (no dev tools present, nothing to strip)
├── requirements-dev.txt                  NEW
├── scripts/
│   └── check_version_bump.py            NEW
├── .pre-commit-config.yaml              NEW
└── .github/
    └── workflows/
        ├── ci.yml                        NEW
        ├── cd.yml                        NEW
        ├── _prep.yml                     NEW
        └── _build-push.yml              NEW
```

No changes to `agents/`, `pipeline/`, `utils/`, `airflow_dags/`, `streamlit_app/`, `docker-compose.yml`, or either Dockerfile.

---

## Makefile

### Variables

| Variable | Value |
|---|---|
| `VENV` | `.venv` |
| `SYSTEM_PYTHON` | auto-detected: python3.11 → python3 → python |
| `PYTHON` | `$(VENV)/bin/python3` |
| `PIP` | `$(PYTHON) -m pip` |
| `BLACK` | `$(PYTHON) -m black` |
| `FLAKE8` | `$(PYTHON) -m flake8` |
| `SRC` | `agents pipeline utils airflow_dags streamlit_app main.py` |

### Targets

| Target | Description |
|---|---|
| `help` | Coloured target list — default goal |
| `install` | Create `.venv` if missing; install runtime + dev deps |
| `hooks` | `pre-commit install --hook-type pre-commit --hook-type pre-push` |
| `pipeline` | Guard `ANTHROPIC_API_KEY`; run `python main.py` |
| `up` | Guard `ANTHROPIC_API_KEY`; `docker compose up --build` |
| `down` | `docker compose down` |
| `build` | `docker compose build` |
| `logs` | `docker compose logs -f` |
| `format` | `black` across all SRC dirs |
| `lint` | `flake8` across all SRC dirs |
| `check` | `black --check` + `flake8` — what CI runs |
| `version` | Print version from `__version__.py` |
| `clean` | Remove `__pycache__`, `.pytest_cache`, `*.pyc`, `.coverage` |

No `test` target — tests are out of scope. Avoids an obviously broken target.

---

## CI Workflow — `.github/workflows/ci.yml`

- **Trigger:** `push` and `pull_request` on any branch
- **Runner:** `ubuntu-latest`
- **Python:** 3.11 with pip cache
- **Steps:**
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` (3.11, pip cache)
  3. `pip install -r requirements.txt -r requirements-dev.txt`
  4. `make check` (black --check + flake8 across SRC)

Single job, no matrix. Fails fast on formatting or lint errors.

---

## CD Workflow — Three Files

### `cd.yml`

- **Trigger:** push to `main`, `workflow_dispatch`
- **Jobs:** `prepare` → `build-push` (sequential, version flows as output)

### `_prep.yml` (reusable)

1. Checkout with full history (`fetch-depth: 0`)
2. Extract `__version__` from `__version__.py` (root)
3. Validate semver strictly greater than latest git tag — fail if not bumped
4. Create annotated git tag `v{version}` on last non-merge commit, push to origin
5. **Output:** `version` string

### `_build-push.yml` (reusable)

- **Input:** `version` from `_prep`
- **Two parallel jobs:**

| Job | Dockerfile | Image name |
|---|---|---|
| `build-airflow` | `Dockerfile.airflow` | `ghcr.io/{owner}/multi-agent-pipeline-airflow:{version}` |
| `build-streamlit` | `Dockerfile.streamlit` | `ghcr.io/{owner}/multi-agent-pipeline-streamlit:{version}` |

Each job:
- Logs in to GHCR via `docker/login-action@v4`
- Sets up Buildx via `docker/setup-buildx-action@v4`
- Extracts metadata (tags: version, short-sha, `latest` on default branch) via `docker/metadata-action@v6`
- Builds and pushes via `docker/build-push-action@v7` with registry cache (read + write, `mode=max`)

---

## Pre-commit — `.pre-commit-config.yaml`

| Hook | Stage | Purpose |
|---|---|---|
| `trailing-whitespace` | pre-commit | Remove trailing spaces |
| `end-of-file-fixer` | pre-commit | Ensure newline at EOF |
| `check-yaml` | pre-commit | Validate YAML syntax |
| `check-added-large-files` (max 500 KB) | pre-commit | Block accidental large file commits |
| `black` 24.4.2 | pre-commit | Auto-format Python |
| `flake8` 7.1.0 + flake8-pyproject | pre-commit | Lint Python |
| `version-bump-check` | **pre-push** | Local guard: `python scripts/check_version_bump.py` |

---

## Supporting Files

### `__version__.py`
```python
__version__ = "0.1.0"
```

### `requirements-dev.txt`
```
black==24.4.2
flake8==7.1.0
flake8-pyproject
pre-commit
pytest
```
`pytest` included for portfolio consistency and future readiness, even though tests are currently out of scope.

### `scripts/check_version_bump.py`

Local pre-push mirror of `_prep.yml`'s semver gate. Reads `__version__.py`, finds the latest git tag, fails with a clear message if the version has not been bumped. Runs only on pre-push so it doesn't slow down every commit.

---

## Constraints

- No commits — user handles all git operations
- No changes to existing source files (`agents/`, `pipeline/`, etc.)
- No test scaffolding — tests are a separate future task
- No scheduled pipeline-trigger workflow — Airflow DAG already handles `@daily` scheduling
