PY ?= python3
TF ?= terraform
TF_DIR ?= terraform

.DEFAULT_GOAL := help

.PHONY: help install test coverage lint security audit inventory estimate tf-fmt tf-validate check clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package plus dev extras
	$(PY) -m pip install -e ".[dev]"

test: ## Run the (deliberately thin) test suite, no AWS credentials needed
	$(PY) -m pytest unit-tests functional-tests

coverage: ## Run tests with coverage; expect a low, honest number
	$(PY) -m pytest unit-tests functional-tests \
		--cov=cloud_pipeline --cov-report=term-missing --cov-report=json:coverage.json

lint: ## Ruff lint
	$(PY) -m ruff check src scripts unit-tests functional-tests

security: ## Bandit static security scan of the application package
	$(PY) -m bandit -q -r src -c pyproject.toml || true

audit: ## Dependency advisory audit (network required)
	$(PY) -m pip_audit || true

inventory: ## Emit JSON inventory of sources, Terraform resources, deps, tests, coverage
	$(PY) scripts/inventory_report.py

estimate: ## Emit assumption-driven cost estimates (NOT a quote)
	$(PY) scripts/estimate_costs.py

tf-fmt: ## Check Terraform formatting
	$(TF) fmt -check -recursive $(TF_DIR)

tf-validate: ## Validate Terraform without creating any resources
	$(TF) -chdir=$(TF_DIR) init -backend=false -input=false
	$(TF) -chdir=$(TF_DIR) validate

check: lint security coverage inventory ## Everything that runs offline

clean: ## Remove local build and report artefacts
	rm -rf .pytest_cache .ruff_cache .coverage coverage.json htmlcov build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Intentionally absent: an `apply` target. Never deploy this lab casually.

