.PHONY: help test format lint type-check all clean install

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies and sync environment
	uv sync
	uv pip install -e ".[test]"

test:  ## Run tests
	pytest

format:  ## Format code with ruff
	ruff format .

lint:  ## Lint and fix issues
	ruff check --fix .

type-check:  ## Run mypy type checking
	mypy src/

all: format lint type-check test  ## Run all checks (format, lint, type-check, test)

pre-commit: all  ## Run all checks before committing

clean:  ## Remove cache and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
