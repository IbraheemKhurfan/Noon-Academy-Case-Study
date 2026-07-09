# Boon Academy Intervention Command Center

Helps facilitators find, prioritize, and track student interventions before
Quiz 2 — turning documented coverage from ~30% toward an 80% target.

**Prerequisites:** Python 3.11+, `make`.

**Setup:**
```
cp .env.example .env   # edit OPENAI_API_KEY to enable real LLM calls (optional)
make demo               # installs deps, runs the full pipeline, launches the app
```

**Other commands:**
- `make pipeline` — run the data/risk/output pipeline only (no UI)
- `make test` — run the pytest suite
- `make reset` — clear the database and generated outputs

**App URL:** http://localhost:8501

**Outputs:** generated in `outputs/` — `student_risk_roster.csv` (per-student risk/priority/recommended action),
`intervention_actions.csv` (every recorded action and its outcome), `pattern_summary.csv` (behavioral pattern
rollup), `data_quality_report.json`, `llm_messages.jsonl` (LLM call audit log), `executive_summary.md` and
`facilitator_dashboard.html` (narrative and visual snapshots), `run_summary.json` (machine-readable run manifest),
and `parent_reports/` (a sample of generated parent reports).

**Demo credentials** (from `.env`, created on first pipeline run):
- Admin: `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` (default `admin@boonacademy.demo` / `Admin@2025`)
- Facilitator: any `facilitator*@noon.com` from `data/student_metadata.csv` / `SEED_FACILITATOR_PASSWORD` (default `Coach@2025`)

Loom walkthrough: <ADD LINK HERE>
