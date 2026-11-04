PYTHON ?= python3.11
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: setup check fixtures
setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install -e '.[dev]'

check:
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests
	$(BIN)/mypy src
	$(BIN)/python -m pytest

fixtures:
	$(BIN)/python tests/fixtures/make_projects.py
