## Diagnosis

Boon's problem isn't detection, it's prioritization and workload: facilitators already write notes, but with ~200 students spread across 8 facilitators and no ranked queue, only 29% of below-target students get followed up before Quiz 2. Six days out from Quiz 2 leaves no room for a research-grade ML system — what's needed is a ranked worklist that separates students who genuinely need a same-day call from the majority who just need a lighter nudge. Given the 2-day, 20-campus constraint, the system must be trustworthy immediately, explainable to a parent, and fast to rerun daily as new data lands.

## What you found in the data

- 199 of 200 students (99.5%) are below their target score, but only 29% (57 of 199) have a facilitator note logged after Quiz 1 — this confirms the case's ~30% baseline intervention rate almost exactly.
- Risk is concentrated, not evenly spread: only 38 students (28 Critical + 10 High, 19% of the cohort) show the low-quiz-score + low-engagement + no-intervention pattern that warrants a same-day human call; the remaining 162 are recoverable with lighter touch or automation.
- 58 students (29%) sit on the Remedial learning track, and they are disproportionately represented in the Critical/High tiers — track alone is a meaningful risk signal, not just quiz score.
- Data quality was largely clean: only 3 of 2,000 daily records (0.15%) had missing attendance, and there were zero negative practice values, zero orphaned rows, and zero missing Quiz 1 scores — though the pipeline is built to survive much worse without crashing.

## What you built and why

- A rule-based, auditable risk score (quiz gap, quiz level, recent attendance, recent practice, missed intervention, track, missing data) so any facilitator can see exactly *why* a student is Critical, and rerunning the pipeline never reshuffles the queue for opaque reasons.
- A four-tier action policy that caps facilitator workload by design: 38 Critical/High students need a call today/within 24h (≈765 minutes across 8 facilitators — manageable), while 127 Low-risk students get an automated message instead of consuming facilitator time.
- An LLM layer (`src/llm.py`) used only to phrase facilitator briefs and warm bilingual Arabic messages — never to decide who is at risk — with a deterministic fallback so the system runs correctly with zero API dependency.
- A data-quality layer that repairs (clips attendance, zero-fills missing engagement, drops orphan rows) instead of crashing on a messy export, logging every repair to `data_quality_report.json`.
- A Streamlit app plus a static HTML dashboard from the same roster CSV, so facilitators get a daily worklist and reviewers get KPIs and a top-10 urgent list without divergent logic.

## What you cut and why

1. **No trained ML model for risk prediction.** Fourteen days of per-student history isn't enough to train or validate anything reliable, and an opaque model would be harder to trust under a 6-day deadline than a transparent point system a facilitator can explain to a parent.
2. **No database, API, or scheduler.** At 20 campuses in 2 days, a CSV-in/CSV-out pipeline that reruns via `make demo` is faster to deploy and debug than shared infrastructure. That investment only pays off once real usage patterns from a 100-campus rollout are known.

## What you'd build next

The highest-leverage next step is closing the feedback loop: today, a facilitator's call outcome only re-enters the system as a fresh note the next time someone reruns the pipeline. A lightweight "log outcome" action inside the Streamlit app — writing status back into `intervention_actions.csv` — would let the system track real contact-to-outcome rates by facilitator and campus, turning this from a one-shot Day-14 rescue into a measurable, improving program ahead of the 100-campus scale-up.
