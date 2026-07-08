# User Manual — Boon Academy Intervention Command Center

## Admin

**Login.** Go to the app URL and sign in with the admin email/password from
`.env` (`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`).

**Overview tab.** System-wide KPIs (students, campuses, facilitators,
successful-interaction rate vs. the 80% target) and the risk-level bar chart.

**Campuses tab.** View all campuses; add a new one (ID + name) or delete one
by ID.

**Facilitators tab.** See per-facilitator workload (student count, Critical/
High counts); create a new facilitator account (email, display name, temporary
password) — the account can log in immediately.

**Students tab.** Browse every student with their risk level; add a new
student or update an existing one (campus, facilitator, grade, track, target
score, parent phone) by entering their `student_id`.

**Data Quality tab.** The full `data_quality_report.json` findings — which
checks fired, how many rows, and sample student IDs — so problems in the
source CSVs are visible, not hidden.

## Facilitator

**Login.** Use any facilitator email from `data/student_metadata.csv` (e.g.
`facilitator1@noon.com`) with `SEED_FACILITATOR_PASSWORD` from `.env`.

**My Day.** Your home page: KPI cards (students, need-intervention count,
successful-interaction rate vs. 80% target, due-today, overdue, planned
minutes) and the **Highest Priority Actions Today** list — each card shows
why the student is flagged, the evidence behind it, and the recommended
action. Buttons: Start, No Answer, Complete, Follow Up, Open Detail, Generate
Message.

**My Students.** Your full roster, filterable by campus/risk/track/action.
Pick a student and click **Open Student Detail** for the full view.

**Student Detail.** Tabs for Overview (risk, patterns, reason codes),
Trends (attendance/practice charts), Peer Comparison (percentiles), Notes
(add a note here — it is analyzed immediately and risk/priority recompute
on the spot, with the before/after change shown), Interventions (history),
Parent Report (build and preview a report, then use **Notify Parent** for a
dry-run send), and Timeline (chronological history).

**Enter metrics / CSV upload.** Data Entry page: a manual form for one
student/day, or upload a CSV — invalid rows are shown with reasons and
excluded; valid rows import without blocking on the bad ones.

**Parent Calls.** The parent-call queue (only students who genuinely
qualify — see `src/actions.py`). Generate a call brief, make the call, then
record the outcome (reached/no answer, response, agreed action, follow-up
date).

**Calendar.** Create 1-on-1 availability for a student (one or more time
options) and copy the generated booking link. The public booking page (no
login) lets the student pick a time; booking one cancels the others in that
batch and creates an intervention record.

**Completing interventions / interaction rate.** Only real actions (Start →
Complete, or a sent message, or a booking) move the successful-interaction
rate — a recommendation or a no-answer call never does. Track your rate on
My Day.

## Technical notes

- **Architecture:** `main.py` runs DATA → VALIDATE → FEATURES → PATTERNS →
  RISK → ACTIONS → OUTPUTS once, then `app.py` (Streamlit) calls
  `main.recompute_all()` after any facilitator action so risk/priority
  always reflect the latest data.
- **Files:** one module per concern under `src/` — `data.py` (ingest),
  `validation.py`, `features.py`, `patterns.py`, `scoring.py`, `actions.py`,
  `llm.py`, `reports.py`, `outputs.py`, `db.py`.
- **Database:** SQLite via SQLAlchemy (`boon.db`); schema in `src/db.py`.
- **LLM:** OpenAI Responses API, isolated in `src/llm.py`, with a content
  cache, one retry, and a deterministic fallback for every task. Disable
  with `LLM_ENABLED=false` or by leaving `OPENAI_API_KEY` blank.
- **Environment variables:** see `.env.example` — all paths, dates, and
  secrets are configurable, nothing is hardcoded.
- **Testing:** `make test` runs `tests/` (validation, patterns, risk, LLM
  fallback, coverage math, role access).
- **Scaling path:** swap `DATABASE_URL` for Postgres, move `recompute_all()`
  to a background job/queue if the student count grows past a few thousand,
  and add the outcome-tracking loop described in `analysis.md`.
