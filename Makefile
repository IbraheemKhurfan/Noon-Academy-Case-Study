.PHONY: demo pipeline test reset install

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install: $(VENV)/bin/activate

.env:
	cp .env.example .env

# 1) install deps  2) create outputs/  3-12) main.py does DB init, ingest,
# validation, features, patterns, risk, actions, outputs, summary
# 13) launch the app
demo: install .env
	mkdir -p outputs
	$(PYTHON) main.py
	$(PYTHON) -m streamlit run app.py --server.port $$(grep -m1 '^APP_PORT=' .env | cut -d= -f2)

pipeline: install .env
	mkdir -p outputs
	$(PYTHON) main.py

test: install
	$(PYTHON) -m pytest tests/ -v

reset:
	rm -f boon.db
	rm -rf .cache
	rm -rf outputs/parent_reports
	rm -f outputs/*.csv outputs/*.json outputs/*.md outputs/*.jsonl outputs/*.html
