# CI/CD & Makefile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Multi-Agent-Pipeline to the same CI/CD and developer-tooling gold standard as RAG-QA-SYSTEM and ML-Monitoring-Platform.

**Architecture:** Nine new files, nothing in the existing source tree modified. A Makefile provides local dev ergonomics. A CI workflow lints on every push/PR. A three-file CD workflow validates semver, creates a git tag, then builds and pushes `airflow` and `streamlit` Docker images to GHCR in parallel. Pre-commit hooks enforce formatting locally before code reaches CI.

**Tech Stack:** GNU Make, GitHub Actions (actions/checkout@v4, setup-python@v5, docker/login-action@v4, docker/setup-buildx-action@v4, docker/metadata-action@v6, docker/build-push-action@v7), Black 24.4.2, Flake8 7.1.0, pre-commit, GHCR.

> **Windows note:** The Makefile uses Unix paths (`$(VENV)/bin/python3`) and `find`/`command -v`. Run it from Git Bash or WSL — not PowerShell. CI runs on `ubuntu-latest` and works as-is.

> **No commits:** The user handles all git operations. No commit steps appear in this plan.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `__version__.py` | Create | Single source of truth for semver |
| `requirements-dev.txt` | Create | Dev-only tools: black, flake8, pre-commit, pytest |
| `scripts/check_version_bump.py` | Create | Pre-push local version gate |
| `Makefile` | Create | Local dev ergonomics (install, run, lint, docker) |
| `.pre-commit-config.yaml` | Create | Git hook configuration |
| `.github/workflows/ci.yml` | Create | Lint on every push + PR |
| `.github/workflows/cd.yml` | Create | Orchestrator: prepare → build-push on main |
| `.github/workflows/_prep.yml` | Create | Reusable: semver gate + annotated git tag |
| `.github/workflows/_build-push.yml` | Create | Reusable: parallel airflow + streamlit → GHCR |

---

## Task 1: Foundation — `__version__.py` and `requirements-dev.txt`

**Files:**
- Create: `__version__.py`
- Create: `requirements-dev.txt`

- [ ] **Step 1: Create `__version__.py` at the repo root**

```python
__version__ = "0.1.0"
```

- [ ] **Step 2: Create `requirements-dev.txt` at the repo root**

```
black==24.4.2
flake8==7.1.0
flake8-pyproject
pre-commit
pytest
```

- [ ] **Step 3: Verify both files parse cleanly**

```bash
python -c "exec(open('__version__.py').read()); print('version:', __version__)"
# Expected: version: 0.1.0
```

---

## Task 2: Version Gate Script — `scripts/check_version_bump.py`

**Files:**
- Create: `scripts/check_version_bump.py`

- [ ] **Step 1: Create the `scripts/` directory and write `check_version_bump.py`**

```python
import subprocess
import sys


def get_current_version():
    ns = {}
    exec(open("__version__.py").read(), ns)
    return ns["__version__"]


def get_latest_tag():
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return tag.lstrip("v")
    except subprocess.CalledProcessError:
        return "0.0.0"


def parse_version(v):
    return tuple(int(x) for x in v.split("."))


def main():
    current = get_current_version()
    latest = get_latest_tag()
    curr_tuple = parse_version(current)
    prev_tuple = parse_version(latest)
    if curr_tuple <= prev_tuple:
        print(
            f"[version-gate] FAIL: bump __version__.py before pushing. "
            f"latest={latest} current={current}"
        )
        sys.exit(1)
    print(f"[version-gate] OK: {latest} -> {current}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script runs (no tags exist yet, so 0.0.0 is the baseline)**

```bash
python scripts/check_version_bump.py
# Expected: [version-gate] OK: 0.0.0 -> 0.1.0
```

---

## Task 3: Makefile

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Create `Makefile` at the repo root**

Paste the entire content exactly as shown — tab characters are required before each recipe line (not spaces):

```makefile
.DEFAULT_GOAL := help

# ── Variables ──────────────────────────────────────────────────────────────────
VENV          := .venv
SYSTEM_PYTHON := $(shell command -v python3.11 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)
PYTHON        := $(VENV)/bin/python3
PIP           := $(PYTHON) -m pip
BLACK         := $(PYTHON) -m black
FLAKE8        := $(PYTHON) -m flake8
SRC           := agents pipeline utils airflow_dags streamlit_app main.py

.PHONY: help install hooks \
        pipeline \
        up down build logs \
        format lint check \
        version clean

# ── Help ───────────────────────────────────────────────────────────────────────
help: ## Show available targets
	@grep -E '^[a-zA-Z_%-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Setup ──────────────────────────────────────────────────────────────────────
install: ## Create .venv (if needed) and install runtime + dev dependencies
	@test -f $(PYTHON) || $(SYSTEM_PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

hooks: ## Install pre-commit hooks (run once after clone)
	pre-commit install --hook-type pre-commit --hook-type pre-push

# ── Local dev ──────────────────────────────────────────────────────────────────
pipeline: ## Run the pipeline locally (requires ANTHROPIC_API_KEY)
	@test -n "$(ANTHROPIC_API_KEY)" || (echo "Error: ANTHROPIC_API_KEY is not set"; exit 1)
	$(PYTHON) main.py

# ── Docker ─────────────────────────────────────────────────────────────────────
up: ## Build and start all services via Docker Compose (requires ANTHROPIC_API_KEY)
	@test -n "$(ANTHROPIC_API_KEY)" || (echo "Error: ANTHROPIC_API_KEY is not set"; exit 1)
	docker compose up --build

down: ## Stop and remove all Docker Compose services
	docker compose down

build: ## Build Docker images without starting containers
	docker compose build

logs: ## Tail logs from all services
	docker compose logs -f

# ── Code quality ───────────────────────────────────────────────────────────────
format: ## Auto-format code with Black
	$(BLACK) $(SRC)

lint: ## Lint with Flake8
	$(FLAKE8) $(SRC)

check: ## Check formatting + linting without modifying files (same as CI)
	$(BLACK) --check $(SRC)
	$(FLAKE8) $(SRC)

# ── Version ────────────────────────────────────────────────────────────────────
version: ## Show current project version
	@$(PYTHON) -c "exec(open('__version__.py').read()); print(__version__)"

# ── Clean ──────────────────────────────────────────────────────────────────────
clean: ## Remove caches, build artifacts, and coverage output
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	rm -f .coverage
```

- [ ] **Step 2: Verify the Makefile parses and `help` renders correctly (run from Git Bash or WSL)**

```bash
make help
```

Expected output — a coloured table of all targets:
```
  help                   Show available targets
  install                Create .venv (if needed) and install runtime + dev dependencies
  hooks                  Install pre-commit hooks (run once after clone)
  pipeline               Run the pipeline locally (requires ANTHROPIC_API_KEY)
  up                     Build and start all services via Docker Compose (requires ANTHROPIC_API_KEY)
  down                   Stop and remove all Docker Compose services
  build                  Build Docker images without starting containers
  logs                   Tail logs from all services
  format                 Auto-format code with Black
  lint                   Lint with Flake8
  check                  Check formatting + linting without modifying files (same as CI)
  version                Show current project version
  clean                  Remove caches, build artifacts, and coverage output
```

---

## Task 4: Pre-commit Configuration — `.pre-commit-config.yaml`

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Create `.pre-commit-config.yaml` at the repo root**

```yaml
repos:
  # ── File hygiene ──────────────────────────────────────────────────────────────
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ["--maxkb=500"]

  # ── Formatting ────────────────────────────────────────────────────────────────
  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black
        language_version: python3

  # ── Linting ───────────────────────────────────────────────────────────────────
  - repo: https://github.com/pycqa/flake8
    rev: 7.1.0
    hooks:
      - id: flake8
        additional_dependencies: [flake8-pyproject]

  # ── Version gate (pre-push only) ──────────────────────────────────────────────
  - repo: local
    hooks:
      - id: version-bump-check
        name: Version bump check
        language: system
        entry: python scripts/check_version_bump.py
        stages: [pre-push]
        pass_filenames: false
        always_run: true
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.pre-commit-config.yaml')); print('YAML OK')"
# Expected: YAML OK
```

---

## Task 5: CI Workflow — `.github/workflows/ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the `.github/workflows/` directory and write `ci.yml`**

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  lint:
    name: Lint & format check
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Check formatting & lint
        run: |
          black --check agents/ pipeline/ utils/ airflow_dags/ streamlit_app/ main.py
          flake8 agents/ pipeline/ utils/ airflow_dags/ streamlit_app/ main.py
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"
# Expected: YAML OK
```

---

## Task 6: CD Orchestrator — `.github/workflows/cd.yml`

**Files:**
- Create: `.github/workflows/cd.yml`

- [ ] **Step 1: Write `cd.yml`**

```yaml
name: CD

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  prepare:
    uses: ./.github/workflows/_prep.yml
    permissions:
      contents: write

  build-push:
    needs: prepare
    uses: ./.github/workflows/_build-push.yml
    with:
      version: ${{ needs.prepare.outputs.version }}
    secrets: inherit
    permissions:
      contents: read
      packages: write
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/cd.yml')); print('YAML OK')"
# Expected: YAML OK
```

---

## Task 7: Reusable Prep Workflow — `.github/workflows/_prep.yml`

**Files:**
- Create: `.github/workflows/_prep.yml`

- [ ] **Step 1: Write `_prep.yml`**

```yaml
name: _prep

on:
  workflow_call:
    outputs:
      version:
        description: "Semantic version extracted from __version__.py"
        value: ${{ jobs.validate-and-tag.outputs.version }}

jobs:
  validate-and-tag:
    name: Validate version & create tag
    runs-on: ubuntu-latest
    permissions:
      contents: write
    outputs:
      version: ${{ steps.extract.outputs.version }}

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # full history so git describe can find tags

      - name: Extract version from __version__.py
        id: extract
        run: |
          VERSION=$(python -c "exec(open('__version__.py').read()); print(__version__)")
          echo "version=$VERSION" >> $GITHUB_OUTPUT

      - name: Validate semver bump against latest tag
        run: |
          CURR="${{ steps.extract.outputs.version }}"
          PREV_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
          PREV="${PREV_TAG#v}"
          python -c "
          import sys
          curr = tuple(int(x) for x in '${CURR}'.split('.'))
          prev = tuple(int(x) for x in '${PREV}'.split('.'))
          if curr <= prev:
              print(f'[version-gate] FAIL: bump __version__.py before pushing. latest={\".\".join(map(str,prev))} current={\".\".join(map(str,curr))}')
              sys.exit(1)
          print(f'[version-gate] OK: {\".\".join(map(str,prev))} -> {\".\".join(map(str,curr))}')
          "

      - name: Create annotated git tag on last non-merge commit
        run: |
          VERSION="${{ steps.extract.outputs.version }}"
          COMMIT=$(git rev-list --max-count=1 --no-merges HEAD)
          git config user.name "GitHub Actions"
          git config user.email "github-actions@users.noreply.github.com"
          git tag -a "v${VERSION}" "${COMMIT}" -m "Release v${VERSION}"
          git push origin "v${VERSION}"
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/_prep.yml')); print('YAML OK')"
# Expected: YAML OK
```

---

## Task 8: Reusable Build-Push Workflow — `.github/workflows/_build-push.yml`

**Files:**
- Create: `.github/workflows/_build-push.yml`

- [ ] **Step 1: Write `_build-push.yml`**

```yaml
name: _build-push

on:
  workflow_call:
    inputs:
      version:
        required: true
        type: string
    outputs:
      airflow_image:
        description: "Fully qualified airflow image (tag=version)"
        value: ${{ jobs.build-airflow.outputs.airflow_image }}
      streamlit_image:
        description: "Fully qualified streamlit image (tag=version)"
        value: ${{ jobs.build-streamlit.outputs.streamlit_image }}

jobs:
  build-airflow:
    name: Build & push Airflow
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      airflow_image: ${{ steps.refs.outputs.airflow }}

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v4

      - name: Set versioned image references
        id: refs
        run: |
          OWNER=$(echo "${{ github.repository_owner }}" | tr '[:upper:]' '[:lower:]')
          BASE="ghcr.io/${OWNER}/multi-agent-pipeline"
          echo "airflow=${BASE}-airflow:${{ inputs.version }}" >> $GITHUB_OUTPUT
          echo "airflow_cache=${BASE}-airflow:buildcache" >> $GITHUB_OUTPUT
          echo "owner_lc=${OWNER}" >> $GITHUB_OUTPUT

      - name: Airflow — extract metadata
        id: meta-airflow
        uses: docker/metadata-action@v6
        with:
          images: ghcr.io/${{ steps.refs.outputs.owner_lc }}/multi-agent-pipeline-airflow
          tags: |
            type=raw,value=${{ inputs.version }}
            type=sha,format=short
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Airflow — build and push
        uses: docker/build-push-action@v7
        with:
          context: .
          file: Dockerfile.airflow
          push: true
          tags: ${{ steps.meta-airflow.outputs.tags }}
          labels: ${{ steps.meta-airflow.outputs.labels }}
          provenance: false
          cache-from: type=registry,ref=${{ steps.refs.outputs.airflow_cache }}
          cache-to: type=registry,ref=${{ steps.refs.outputs.airflow_cache }},mode=max,image-manifest=true,oci-mediatypes=true

  build-streamlit:
    name: Build & push Streamlit
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      streamlit_image: ${{ steps.refs.outputs.streamlit }}

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v4

      - name: Set versioned image references
        id: refs
        run: |
          OWNER=$(echo "${{ github.repository_owner }}" | tr '[:upper:]' '[:lower:]')
          BASE="ghcr.io/${OWNER}/multi-agent-pipeline"
          echo "streamlit=${BASE}-streamlit:${{ inputs.version }}" >> $GITHUB_OUTPUT
          echo "streamlit_cache=${BASE}-streamlit:buildcache" >> $GITHUB_OUTPUT
          echo "owner_lc=${OWNER}" >> $GITHUB_OUTPUT

      - name: Streamlit — extract metadata
        id: meta-streamlit
        uses: docker/metadata-action@v6
        with:
          images: ghcr.io/${{ steps.refs.outputs.owner_lc }}/multi-agent-pipeline-streamlit
          tags: |
            type=raw,value=${{ inputs.version }}
            type=sha,format=short
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Streamlit — build and push
        uses: docker/build-push-action@v7
        with:
          context: .
          file: Dockerfile.streamlit
          push: true
          tags: ${{ steps.meta-streamlit.outputs.tags }}
          labels: ${{ steps.meta-streamlit.outputs.labels }}
          provenance: false
          cache-from: type=registry,ref=${{ steps.refs.outputs.streamlit_cache }}
          cache-to: type=registry,ref=${{ steps.refs.outputs.streamlit_cache }},mode=max,image-manifest=true,oci-mediatypes=true
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/_build-push.yml')); print('YAML OK')"
# Expected: YAML OK
```

---

## Final Verification Checklist

After all 8 tasks are complete, confirm the full file tree:

```bash
# Run from repo root (Git Bash / WSL)
ls __version__.py requirements-dev.txt Makefile .pre-commit-config.yaml
ls scripts/check_version_bump.py
ls .github/workflows/ci.yml .github/workflows/cd.yml \
   .github/workflows/_prep.yml .github/workflows/_build-push.yml
```

Expected: all 9 files present, no errors.

```bash
# Verify Makefile target list renders
make help

# Verify version script
python scripts/check_version_bump.py
# Expected: [version-gate] OK: 0.0.0 -> 0.1.0
```
