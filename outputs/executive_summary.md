# Executive Summary — Boon Academy Intervention Command Center

## Data snapshot
- Day 14 of the program. Quiz 1 already happened; Quiz 2 is in 6 days.
- 200 students across 5 campuses and 8 facilitators.
- 199 students (99.5%) are currently below their target score.
- 1 data-quality issue(s) detected and auto-repaired or flagged (see `data_quality_report.json`).

## Intervention rate
- **Baseline (before this system):** 29% of below-target students had a facilitator note after Quiz 1.
- **System human-touch coverage:** 36% of below-target students now have a prioritized, assigned human action (call, tutoring, or check-in) before Quiz 2.
- **System full coverage (human + automated):** 100% — every below-target student has at least an automated nudge queued.

## Risk distribution
| Risk level | Students |
|---|---|
| Critical | 28 |
| High | 10 |
| Medium | 35 |
| Low | 127 |

## Facilitator workload (Critical + High students only)
| Facilitator | Students needing action today/24h | Estimated time |
|---|---|---|
| facilitator8@noon.com | 8 | 150 min |
| facilitator7@noon.com | 5 | 100 min |
| facilitator3@noon.com | 6 | 90 min |
| facilitator4@noon.com | 5 | 90 min |
| facilitator6@noon.com | 5 | 90 min |
| facilitator2@noon.com | 4 | 60 min |
| facilitator5@noon.com | 3 | 50 min |
| facilitator1@noon.com | 2 | 30 min |

Total estimated facilitator time across all risk tiers: **765 minutes**.

## Top 10 urgent students
| Student | Campus | Facilitator | Risk | Score | Quiz 1 | Target | Action |
|---|---|---|---|---|---|---|---|
| Khalid Al-Zahrani | C05 | facilitator8@noon.com | Critical | 78.8 | 9 | 12 | parent_call_plus_tutoring |
| Layla Al-Mutairi | C05 | facilitator8@noon.com | Critical | 77.5 | 11 | 14 | parent_call_plus_tutoring |
| Maryam Al-Mansour | C05 | facilitator8@noon.com | Critical | 76.6 | 13 | 16 | parent_call_plus_tutoring |
| Ahmad Al-Dossari | C05 | facilitator8@noon.com | Critical | 75.8 | 20 | 24 | parent_call_plus_tutoring |
| Layla Al-Khaldi | C05 | facilitator8@noon.com | Critical | 75.8 | 15 | 18 | parent_call_plus_tutoring |
| Amal Al-Salem | C04 | facilitator7@noon.com | Critical | 75.6 | 21 | 25 | parent_call_plus_tutoring |
| Amal Al-Subai | C04 | facilitator6@noon.com | Critical | 75.2 | 23 | 27 | parent_call_plus_tutoring |
| Ahmad Al-Anzi | C04 | facilitator7@noon.com | Critical | 75.2 | 23 | 27 | parent_call_plus_tutoring |
| Nora Al-Saud | C05 | facilitator8@noon.com | Critical | 75.2 | 17 | 20 | parent_call_plus_tutoring |
| Abdullah Al-Otaibi | C05 | facilitator8@noon.com | Critical | 75.0 | 18 | 21 | parent_call_plus_tutoring |

## What to do before Quiz 2
1. Every facilitator opens `facilitator_worklists.csv` (or the Streamlit app) and works Critical students first — same-day parent call plus a tutoring slot booked before Day 20.
2. High-risk students get a parent call or voice note within 24 hours to identify the specific barrier (attendance, practice, or comprehension).
3. Medium-risk students get a lightweight WhatsApp check-in within 48 hours; Low-risk below-target students receive an automated motivation message today, no facilitator time required.
4. Re-run `make demo` daily through Day 20 to re-prioritize as new attendance, practice, and note data comes in.

## System limitations
- Risk scoring uses only the three provided data sources; it cannot see reasons behind disengagement (family, health, motivation) beyond what a facilitator has written in notes.
- "Recent" engagement is a fixed 2-day window; a single bad day can move a borderline student a tier.
- LLM-drafted messages (when enabled) should be spot-checked by a facilitator before sending to a parent — the system drafts, it does not send.
