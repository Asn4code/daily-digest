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
	@test -f tests/fixtures/make_projects.py || { echo 'Generador de fixtures pendiente de CB-05.'; exit 1; }
	$(BIN)/python tests/fixtures/make_projects.py
