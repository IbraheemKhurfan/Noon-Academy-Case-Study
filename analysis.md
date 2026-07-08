# Analysis

## Diagnosis

On Day 14, six days before Quiz 2, 199 of 200 students (99.5%) are below their target score, yet only 13.5% of students who need support have documented facilitator contact since Quiz 1 — the bottleneck is not detecting who is struggling, it is converting that into a completed, tracked intervention before time runs out. Students who look similar on one risk number need very different help: some show a sudden attendance collapse (the top-priority student's recent attendance fell 51 minutes/day versus their own baseline), others still attend but have nearly stopped practicing, and many are simply a few points under target with stable behavior. With 8 facilitators covering 20-38 students each, and a measured 0% successful-interaction rate before any facilitator has used the system, the job is to turn a 200-student list into a short, correctly-prioritized daily queue and prove, from tracked outcomes rather than generated recommendations, that coverage is moving toward 80%.

## What you found in the data

- 199 of 200 students (99.5%) are below their target score, and only 13.5% of students who need support have documented post-Quiz-1 activity — 173 students (86.5%) show the `NO_POST_QUIZ_INTERVENTION` pattern.
- 102 of 180 facilitator notes (57%) have a `facilitator_email` that does not match the student's assigned facilitator in `student_metadata`; these are retained but excluded from parent communication and qualitative risk scoring until trusted (51 students affected in total across all data-quality flags).
- Risk segmentation splits this one below-target population into sharply different situations — 1 Critical, 9 High, 56 Medium, 134 Low — alongside 3 missing-attendance rows, 3 extreme practice-volume days, and 1 quiz score logged before Quiz 1's date, each a real anomaly rather than a hypothetical.

## What you built and why

- A deterministic, component-based risk score (performance/engagement/trajectory/trusted-note/intervention-gap) instead of a black box, so every score is explainable and testable.
- Rule-based pattern detection (13 patterns) fully separated from LLM usage, so priority never silently shifts with a model update.
- A coverage funnel (recommendation → attempt → success → completed), not one "coverage" number — a recommendation or a no-answer call is not a completed intervention, and conflating them would hide the exact gap this study is about.
- LLM usage scoped to three language tasks (note understanding, messages, parent briefs), each with a deterministic fallback, so the pipeline runs identically with `LLM_ENABLED=false`.
- One Streamlit app with role-based views (facilitator "My Day" queue vs. admin oversight), so the daily action list — not a dashboard — is the primary surface.

## What you cut and why

No trained ML model: Quiz 2 outcome labels do not exist yet, so a black-box score would be less trustworthy than an auditable rule set for a facilitator acting on it today.
No uncontrolled automatic parent communication: 57% of notes carry an unverified facilitator/student pairing, so identity and contact data need human validation first — every notification here is a facilitator-reviewed dry run, never an automatic send.

## What you'd build next

The most valuable next step is closing the loop this system can only half-close today: recommended intervention → completed intervention → outcome → behavior change → future quiz result. The pipeline can measure whether a facilitator completed an action, but not whether that action worked — did attendance recover after a parent call, did practice resume after a check-in, did the eventual Quiz 2 score beat what the pre-intervention trajectory implied? Once Quiz 2 results land, each completed intervention becomes a labeled example (action type, before/after state, outcome), turning today's rule weights from an expert-authored guess into something empirically tunable, so the system can recommend whichever action type has actually worked best for a given pattern.
