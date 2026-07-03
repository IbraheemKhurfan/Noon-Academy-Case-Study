# Boon Academy Intervention Command Center

Turns messy daily attendance/practice/quiz/note data into a prioritized, workload-capped facilitator worklist so intervention coverage moves from ~30% to 80%+ before Quiz 2.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
cp .env.example .env   # edit if your data lives elsewhere or you have an OpenAI key
```

## Environment variables (see `.env.example`)
`DATA_DIR`, `OUTPUT_DIR`, `LLM_ENABLED`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `APP_PORT`

## Run the pipeline
```bash
make demo
```
Installs dependencies, runs ingest → validate → features → risk → actions → outputs, and prints a summary. Works with `LLM_ENABLED=false` (deterministic templates) or `true` + a real `OPENAI_API_KEY`.

## Launch the app
```bash
streamlit run app.py
```

## Outputs (`outputs/`)
`student_risk_roster.csv`, `facilitator_worklists.csv`, `intervention_actions.csv`, `executive_summary.md`, `data_quality_report.json`, `facilitator_dashboard.html`, `llm_messages.jsonl`

Loom walkthrough: <ADD LINK HERE>
