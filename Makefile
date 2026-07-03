.PHONY: demo install test

# Picks the newest available Python 3.11+ interpreter so `make demo` works
# on a fresh clone even when the system `python3` is older (e.g. macOS's
# stock 3.9). Falls back to plain `python3` if nothing newer is found.
PYTHON := $(shell command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
VENV := .venv

# One-command demo: create an isolated venv, install deps, run the
# pipeline end to end, and print the summary.
demo: install
	@mkdir -p outputs
	@$(VENV)/bin/python main.py
	@echo ""
	@echo "Launch the app with: streamlit run app.py"

$(VENV)/bin/python:
	@$(PYTHON) -m venv $(VENV)

install: $(VENV)/bin/python
	@$(VENV)/bin/pip install -q --upgrade pip
	@$(VENV)/bin/pip install -q -r requirements.txt

test: install
	@$(VENV)/bin/pytest -q
