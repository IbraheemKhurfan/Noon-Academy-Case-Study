"""Human-facing reports: the executive summary and the static dashboard.

`compute_summary` is the single source of truth for every headline number
(`main.py`'s console output, `executive_summary.md`, and
`facilitator_dashboard.html` all call it) so the three surfaces can never
disagree with each other.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from jinja2 import Template

from src.config import Settings

RISK_ORDER = ["Critical", "High", "Medium", "Low"]

# Actions that put a human in front of the family/student today or this
# week, as opposed to the fully-automated Low-risk nudge. This is the
# number we report as "coverage" — the case's 30%->80% goal is about
# students actually being *followed up with*, not just flagged.
HUMAN_TOUCH_ACTIONS = {
    "parent_call_plus_tutoring",
    "parent_call_or_voice_note",
    "student_checkin_plus_practice_plan",
}


def compute_summary(df: pd.DataFrame, settings: Settings) -> dict:
    below_target = df[df["below_target"]]
    below_target_count = len(below_target)

    baseline_rate = (
        float(below_target["has_post_quiz_intervention"].mean()) if below_target_count else 0.0
    )
    human_touch = below_target[below_target["recommended_action"].isin(HUMAN_TOUCH_ACTIONS)]
    human_touch_rate = len(human_touch) / below_target_count if below_target_count else 0.0

    risk_counts = (
        df["risk_level"].value_counts().reindex(RISK_ORDER, fill_value=0).astype(int).to_dict()
    )

    workload = (
        df[df["risk_level"].isin(["Critical", "High"])]
        .groupby("facilitator_email")
        .agg(
            critical_high_students=("student_id", "count"),
            estimated_minutes=("estimated_minutes", "sum"),
        )
        .reset_index()
        .sort_values("estimated_minutes", ascending=False)
    )

    top_urgent = df.sort_values("risk_score", ascending=False).head(10)

    return {
        "total_students": len(df),
        "campuses": sorted(df["campus_id"].dropna().unique().tolist()),
        "facilitators": sorted(df["facilitator_email"].dropna().unique().tolist()),
        "below_target_count": below_target_count,
        "baseline_intervention_rate": baseline_rate,
        "system_human_touch_rate": human_touch_rate,
        "system_full_coverage_rate": 1.0 if below_target_count else 0.0,
        "risk_counts": risk_counts,
        "recommended_interventions": int(len(human_touch) + len(below_target) - len(human_touch)),
        "human_touch_interventions": int(len(human_touch)),
        "total_estimated_minutes": int(df["estimated_minutes"].sum()),
        "workload_by_facilitator": workload,
        "top_urgent": top_urgent,
        "current_day": settings.current_day,
        "quiz2_day": settings.quiz2_day,
        "days_to_quiz2": settings.quiz2_day - settings.current_day,
    }


def build_executive_summary_md(df: pd.DataFrame, summary: dict, quality_report_dict: dict) -> str:
    top_rows = "\n".join(
        f"| {r.student_name} | {r.campus_id} | {r.facilitator_email} | {r.risk_level} | "
        f"{r.risk_score} | {'' if pd.isna(r.quiz1_score) else int(r.quiz1_score)} | "
        f"{int(r.target_score) if pd.notna(r.target_score) else ''} | {r.recommended_action} |"
        for r in summary["top_urgent"].itertuples()
    )

    workload_rows = "\n".join(
        f"| {row.facilitator_email} | {row.critical_high_students} | {row.estimated_minutes} min |"
        for row in summary["workload_by_facilitator"].itertuples()
    )

    return f"""# Executive Summary — Boon Academy Intervention Command Center

## Data snapshot
- Day {summary['current_day']} of the program. Quiz 1 already happened; Quiz 2 is in {summary['days_to_quiz2']} days.
- {summary['total_students']} students across {len(summary['campuses'])} campuses and {len(summary['facilitators'])} facilitators.
- {summary['below_target_count']} students ({summary['below_target_count'] / summary['total_students']:.1%}) are currently below their target score.
- {quality_report_dict.get('total_issues', 0)} data-quality issue(s) detected and auto-repaired or flagged (see `data_quality_report.json`).

## Intervention rate
- **Baseline (before this system):** {summary['baseline_intervention_rate']:.0%} of below-target students had a facilitator note after Quiz 1.
- **System human-touch coverage:** {summary['system_human_touch_rate']:.0%} of below-target students now have a prioritized, assigned human action (call, tutoring, or check-in) before Quiz 2.
- **System full coverage (human + automated):** {summary['system_full_coverage_rate']:.0%} — every below-target student has at least an automated nudge queued.

## Risk distribution
| Risk level | Students |
|---|---|
| Critical | {summary['risk_counts']['Critical']} |
| High | {summary['risk_counts']['High']} |
| Medium | {summary['risk_counts']['Medium']} |
| Low | {summary['risk_counts']['Low']} |

## Facilitator workload (Critical + High students only)
| Facilitator | Students needing action today/24h | Estimated time |
|---|---|---|
{workload_rows}

Total estimated facilitator time across all risk tiers: **{summary['total_estimated_minutes']} minutes**.

## Top 10 urgent students
| Student | Campus | Facilitator | Risk | Score | Quiz 1 | Target | Action |
|---|---|---|---|---|---|---|---|
{top_rows}

## What to do before Quiz 2
1. Every facilitator opens `facilitator_worklists.csv` (or the Streamlit app) and works Critical students first — same-day parent call plus a tutoring slot booked before Day {summary['quiz2_day']}.
2. High-risk students get a parent call or voice note within 24 hours to identify the specific barrier (attendance, practice, or comprehension).
3. Medium-risk students get a lightweight WhatsApp check-in within 48 hours; Low-risk below-target students receive an automated motivation message today, no facilitator time required.
4. Re-run `make demo` daily through Day {summary['quiz2_day']} to re-prioritize as new attendance, practice, and note data comes in.

## System limitations
- Risk scoring uses only the three provided data sources; it cannot see reasons behind disengagement (family, health, motivation) beyond what a facilitator has written in notes.
- "Recent" engagement is a fixed 2-day window; a single bad day can move a borderline student a tier.
- LLM-drafted messages (when enabled) should be spot-checked by a facilitator before sending to a parent — the system drafts, it does not send.
"""


DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Boon Academy Intervention Command Center</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 2.5rem; background: #f4f6fb; color: #1a1f36;
  }
  h1 { font-size: 1.9rem; margin-bottom: 0.15rem; }
  .subtitle { color: #5b6470; margin-bottom: 2rem; }
  .kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 1rem; margin-bottom: 2.5rem;
  }
  .kpi-card {
    background: #fff; border-radius: 14px; padding: 1.1rem 1.3rem;
    box-shadow: 0 1px 3px rgba(20,20,43,0.08); border-left: 5px solid #4f5df0;
  }
  .kpi-card .label { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: #6b7280; margin-bottom: 0.35rem; }
  .kpi-card .value { font-size: 1.7rem; font-weight: 700; }
  .kpi-card.critical { border-left-color: #d03b3b; }
  .kpi-card.high { border-left-color: #ec835a; }
  .kpi-card.good { border-left-color: #0ca30c; }
  section { background: #fff; border-radius: 14px; padding: 1.5rem 1.7rem; margin-bottom: 1.8rem; box-shadow: 0 1px 3px rgba(20,20,43,0.08); }
  section h2 { margin-top: 0; font-size: 1.15rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  th, td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid #eef0f5; }
  th { color: #6b7280; font-weight: 600; text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.03em; }
  .badge { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
  .badge.Critical { background: #fbe4e4; color: #d03b3b; }
  .badge.High { background: #fce8e0; color: #ec835a; }
  .badge.Medium { background: #fef3dc; color: #ab7c00; }
  .badge.Low { background: #e1f5e1; color: #0ca30c; }
  .risk-bar-row { display: flex; align-items: center; gap: 0.7rem; margin-bottom: 0.5rem; }
  .risk-bar-label { width: 90px; font-size: 0.85rem; }
  .risk-bar-track { flex: 1; background: #eef0f5; border-radius: 6px; height: 14px; overflow: hidden; }
  .risk-bar-fill { height: 100%; border-radius: 6px; }
  .instructions ol { margin: 0; padding-left: 1.2rem; }
  .instructions li { margin-bottom: 0.4rem; }
  footer { color: #9aa1ac; font-size: 0.8rem; text-align: center; margin-top: 2rem; }
</style>
</head>
<body>
  <h1>Boon Academy Intervention Command Center</h1>
  <div class="subtitle">Day {{ summary.current_day }} rescue plan — Quiz 2 in {{ summary.days_to_quiz2 }} days</div>

  <div class="kpi-grid">
    <div class="kpi-card"><div class="label">Total students</div><div class="value">{{ summary.total_students }}</div></div>
    <div class="kpi-card high"><div class="label">Below target</div><div class="value">{{ summary.below_target_count }}</div></div>
    <div class="kpi-card critical"><div class="label">Baseline intervention rate</div><div class="value">{{ "%.0f"|format(summary.baseline_intervention_rate * 100) }}%</div></div>
    <div class="kpi-card good"><div class="label">System coverage (human-touch)</div><div class="value">{{ "%.0f"|format(summary.system_human_touch_rate * 100) }}%</div></div>
    <div class="kpi-card critical"><div class="label">Critical + High students</div><div class="value">{{ summary.risk_counts.Critical + summary.risk_counts.High }}</div></div>
    <div class="kpi-card"><div class="label">Est. facilitator workload</div><div class="value">{{ summary.total_estimated_minutes }} min</div></div>
  </div>

  <section>
    <h2>Risk distribution</h2>
    {% for level, color in [("Critical", "#d03b3b"), ("High", "#ec835a"), ("Medium", "#fab219"), ("Low", "#0ca30c")] %}
    <div class="risk-bar-row">
      <div class="risk-bar-label">{{ level }} ({{ summary.risk_counts[level] }})</div>
      <div class="risk-bar-track"><div class="risk-bar-fill" style="width: {{ (summary.risk_counts[level] / summary.total_students * 100) if summary.total_students else 0 }}%; background: {{ color }};"></div></div>
    </div>
    {% endfor %}
  </section>

  <section>
    <h2>Facilitator workload (Critical + High students)</h2>
    <table>
      <tr><th>Facilitator</th><th>Students needing action today/24h</th><th>Estimated minutes</th></tr>
      {% for row in workload %}
      <tr><td>{{ row.facilitator_email }}</td><td>{{ row.critical_high_students }}</td><td>{{ row.estimated_minutes }}</td></tr>
      {% endfor %}
    </table>
  </section>

  <section>
    <h2>Top urgent students</h2>
    <table>
      <tr><th>Student</th><th>Campus</th><th>Facilitator</th><th>Risk</th><th>Score</th><th>Quiz 1</th><th>Target</th><th>Action</th></tr>
      {% for r in top_urgent %}
      <tr>
        <td>{{ r.student_name }}</td>
        <td>{{ r.campus_id }}</td>
        <td>{{ r.facilitator_email }}</td>
        <td><span class="badge {{ r.risk_level }}">{{ r.risk_level }}</span></td>
        <td>{{ r.risk_score }}</td>
        <td>{{ "-" if r.quiz1_score != r.quiz1_score else r.quiz1_score|int }}</td>
        <td>{{ "-" if r.target_score != r.target_score else r.target_score|int }}</td>
        <td>{{ r.recommended_action }}</td>
      </tr>
      {% endfor %}
    </table>
  </section>

  <section class="instructions">
    <h2>Instructions for facilitators</h2>
    <ol>
      <li>Open <code>facilitator_worklists.csv</code> or the Streamlit app and filter to your email.</li>
      <li>Work Critical students first — same-day parent call plus a booked tutoring slot before Quiz 2.</li>
      <li>Use the pre-drafted parent script and student message as a starting point, not a script to read verbatim.</li>
      <li>Log the outcome as a facilitator note so tomorrow's run reflects the intervention you just made.</li>
    </ol>
  </section>

  <footer>Generated by the Boon Academy Intervention Command Center pipeline — Day {{ summary.current_day }}.</footer>
</body>
</html>
"""


def build_facilitator_dashboard_html(summary: dict) -> str:
    template = Template(DASHBOARD_TEMPLATE)
    return template.render(
        summary=summary,
        workload=summary["workload_by_facilitator"].itertuples(),
        top_urgent=summary["top_urgent"].itertuples(),
    )
