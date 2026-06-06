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
	@test -n "$(ANTHROPIC_API_KEY)" || { echo "Error: ANTHROPIC_API_KEY is not set"; exit 1; }
	$(PYTHON) main.py

# ── Docker ─────────────────────────────────────────────────────────────────────
up: ## Build and start all services via Docker Compose (requires ANTHROPIC_API_KEY)
	@test -n "$(ANTHROPIC_API_KEY)" || { echo "Error: ANTHROPIC_API_KEY is not set"; exit 1; }
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
