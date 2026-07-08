"""Human-facing documents: the executive summary, the static facilitator
dashboard snapshot, and parent reports. All numbers here are read from
already-computed features/risk/intervention tables — no calculation happens
in this module, only formatting and charting.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go

from src.config import CATEGORICAL_COLORS, GRIDLINE, INK, PAGE_PLANE, REPORT_STATUS_COLORS, REPORT_STATUS_ICONS, RISK_COLORS

STATUS_COLORS = REPORT_STATUS_COLORS  # kept as an alias — this module's original public name
FONT_FAMILY = "-apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif"


def _apply_chart_chrome(fig: go.Figure, title: str, y_title: Optional[str] = None) -> go.Figure:
    """One consistent look for every chart in this file: same font, same
    muted gridlines, same margins — so a reader never has to re-orient
    between the live app, the dashboard snapshot, and a parent report."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK["primary"], family=FONT_FAMILY)),
        font=dict(family=FONT_FAMILY, color=INK["secondary"], size=12),
        yaxis_title=y_title,
        plot_bgcolor="#fcfcfb",
        paper_bgcolor="#fcfcfb",
        margin=dict(l=40, r=20, t=44, b=32),
        height=280,
        showlegend=fig.layout.showlegend if fig.layout.showlegend is not None else False,
    )
    fig.update_xaxes(gridcolor=GRIDLINE, linecolor=GRIDLINE, zeroline=False)
    fig.update_yaxes(gridcolor=GRIDLINE, linecolor=GRIDLINE, zeroline=False)
    return fig


def overall_status_for(risk_level: str, pattern_codes: set[str]) -> str:
    if "RECOVERY_TRAJECTORY" in pattern_codes and risk_level in ("Medium", "Low"):
        return "Improving"
    return {"Critical": "Critical", "High": "Needs Attention", "Medium": "Watch", "Low": "Stable"}.get(risk_level, "Watch")


def build_executive_summary_md(stats: dict) -> str:
    lines = [
        "# Boon Academy Intervention Command Center — Executive Summary",
        "",
        f"_Generated {stats['generated_at']} — as of Day {stats['as_of_day']} "
        f"({stats['days_until_quiz2']} days until Quiz 2)_",
        "",
        "## Headline numbers",
        "",
        f"- **{stats['total_students']}** students across **{stats['total_campuses']}** campuses and "
        f"**{stats['total_facilitators']}** facilitators.",
        f"- **{stats['below_target_count']}** students ({stats['below_target_pct']:.1f}%) are below their target score.",
        f"- Post-Quiz-1 documented facilitator activity currently covers "
        f"**{stats['post_quiz_activity_pct']:.1f}%** of students who need it.",
        f"- Actual successful-interaction rate is **{stats['successful_interaction_rate']:.1f}%**, "
        f"against an **80%** target — **{stats['additional_students_needed']}** more successful "
        f"interactions are needed among students who need one to hit target.",
        "",
        "## Risk distribution",
        "",
        f"| Level | Students |",
        f"|---|---|",
        f"| Critical | {stats['risk_counts'].get('Critical', 0)} |",
        f"| High | {stats['risk_counts'].get('High', 0)} |",
        f"| Medium | {stats['risk_counts'].get('Medium', 0)} |",
        f"| Low | {stats['risk_counts'].get('Low', 0)} |",
        "",
        "## Intervention coverage funnel",
        "",
        f"- Recommendation coverage: **{stats['recommendation_coverage']:.1f}%**",
        f"- Contact attempt rate: **{stats['contact_attempt_rate']:.1f}%**",
        f"- Successful interaction rate: **{stats['successful_interaction_rate']:.1f}%**",
        f"- Completed intervention rate: **{stats['completed_intervention_rate']:.1f}%**",
        f"- Overdue intervention rate: **{stats['overdue_intervention_rate']:.1f}%**",
        f"- Projected coverage (including today's planned queue): **{stats['projected_coverage']:.1f}%** _(projected, not actual)_",
        "",
        "## LLM usage",
        "",
        f"- {stats['llm_success_count']} successful LLM calls, {stats['llm_fallback_count']} used the deterministic fallback.",
        "",
        "## Data quality",
        "",
        f"- {stats['data_quality_issue_count']} data-quality checks flagged issues "
        f"across {stats['students_with_quality_flags']} students. See `data_quality_report.json` for detail.",
    ]
    return "\n".join(lines) + "\n"


def build_pattern_summary_df(risk_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = len(risk_df)
    exploded = risk_df.explode("pattern_codes")
    for code, group in exploded.groupby("pattern_codes"):
        if pd.isna(code):
            continue
        rows.append({
            "pattern_code": code,
            "student_count": len(group),
            "pct_of_students": round(100 * len(group) / total, 1) if total else 0.0,
            "avg_risk_score": round(group["risk_score"].mean(), 1),
        })
    return pd.DataFrame(rows).sort_values("student_count", ascending=False).reset_index(drop=True)


def _line_chart(dates: list, values: list, title: str, y_title: str) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=dates, y=values, mode="lines+markers",
        line=dict(color=CATEGORICAL_COLORS[0], width=2),
        marker=dict(size=8, color=CATEGORICAL_COLORS[0]),
    ))
    return _apply_chart_chrome(fig, title, y_title)


def _bar_chart(labels: list[str], values: list[float], title: str, colors: Optional[list[str]] = None) -> go.Figure:
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=colors or CATEGORICAL_COLORS[0]))
    return _apply_chart_chrome(fig, title)


def build_facilitator_dashboard_html(stats: dict, risk_df: pd.DataFrame) -> str:
    risk_counts = stats["risk_counts"]
    fig1 = _bar_chart(
        list(risk_counts.keys()), list(risk_counts.values()), "Students by risk level",
        colors=[RISK_COLORS.get(k, INK["muted"]) for k in risk_counts.keys()],
    )

    # Funnel stages are an *ordinal* progression (one step further along the
    # same journey), not unrelated categories, so they take one hue stepped
    # light->dark rather than four arbitrary colors.
    funnel_labels = ["Recommendation", "Contact attempt", "Successful interaction", "Completed"]
    funnel_values = [stats["recommendation_coverage"], stats["contact_attempt_rate"],
                      stats["successful_interaction_rate"], stats["completed_intervention_rate"]]
    funnel_ramp = ["#86b6ef", "#5598e7", "#2a78d6", "#184f95"]
    fig2 = go.Figure(go.Funnel(y=funnel_labels, x=funnel_values, marker=dict(color=funnel_ramp)))
    fig2 = _apply_chart_chrome(fig2, "Intervention coverage funnel (%)")
    fig2.update_layout(height=320)

    workload = risk_df.groupby("facilitator_email").size().sort_values(ascending=False)
    workload_colors = [CATEGORICAL_COLORS[i % len(CATEGORICAL_COLORS)] for i in range(len(workload))]
    fig3 = _bar_chart(list(workload.index), list(workload.values), "Facilitator workload (students)",
                       colors=workload_colors)

    parts = [fig.to_html(full_html=False, include_plotlyjs=(i == 0)) for i, fig in enumerate([fig1, fig2, fig3])]
    return f"""
<!doctype html><html><head><meta charset="utf-8">
<title>Boon Academy — Facilitator Dashboard Snapshot</title>
<style>
body {{ font-family: {FONT_FAMILY}; margin: 24px; background:{PAGE_PLANE}; color:{INK['primary']};}}
h1 {{ font-size: 22px; }}
.grid {{ display:grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.card {{ background:#fff; border-radius:12px; padding:16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);}}
.kpis {{ display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap;}}
.kpi {{ background:#fff; border-radius:12px; padding:16px 20px; box-shadow:0 1px 3px rgba(0,0,0,0.08); min-width:160px;}}
.kpi .v {{ font-size:28px; font-weight:700; color:{INK['primary']};}}
.kpi .l {{ font-size:12px; color:{INK['secondary']};}}
</style></head><body>
<h1>📊 Boon Academy Intervention Command Center — Snapshot ({stats['generated_at']})</h1>
<div class="kpis">
  <div class="kpi"><div class="v">👥 {stats['total_students']}</div><div class="l">Students</div></div>
  <div class="kpi"><div class="v">🎯 {stats['successful_interaction_rate']:.1f}%</div><div class="l">Successful interaction rate (target 80%)</div></div>
  <div class="kpi"><div class="v">📉 {stats['below_target_count']}</div><div class="l">Below target</div></div>
  <div class="kpi"><div class="v">⏳ {stats['days_until_quiz2']}</div><div class="l">Days until Quiz 2</div></div>
</div>
<div class="grid">
  <div class="card">{parts[0]}</div>
  <div class="card">{parts[1]}</div>
  <div class="card" style="grid-column: span 2;">{parts[2]}</div>
</div>
</body></html>"""


def assemble_parent_context(
    row: dict,
    metrics_df: pd.DataFrame,
    peer_avgs: dict[str, float],
    trusted_note_summary: str,
    llm_summary: str,
    generated_at: str,
) -> dict:
    """Builds the full template context for build_parent_report_html from
    already-computed data. Shared by the pipeline (sample reports) and the
    live Streamlit "Parent Report" tab so both render identically."""
    pattern_codes = set(row.get("pattern_codes", []))
    overall_status = overall_status_for(row["risk_level"], pattern_codes)

    gap = row.get("gap_to_target")
    if gap is None:
        gap_display = "Unknown (no Quiz 1 score)"
    elif gap > 0:
        gap_display = f"{gap:.0f} pts below target"
    else:
        gap_display = "At or above target"

    metrics_df = metrics_df.sort_values("date")
    dates = [d.isoformat() if hasattr(d, "isoformat") else str(d) for d in metrics_df["date"]]
    attendance_fig_html = _line_chart(dates, metrics_df["session_attended_min"].tolist(),
                                       "Attendance (minutes/day)", "minutes").to_html(full_html=False, include_plotlyjs="cdn")
    practice_fig_html = _line_chart(dates, metrics_df["practice_questions"].tolist(),
                                     "Practice (questions/day)", "questions").to_html(full_html=False, include_plotlyjs=False)

    # Two distinct identities (this student vs. their peer group), not a
    # magnitude scale, so each gets its own categorical color — the peer bar
    # uses a muted ink tone since it is reference context, not a competitor.
    cohort_fig = go.Figure()
    cohort_fig.add_trace(go.Bar(name="Student", x=["Quiz score", "Attendance", "Practice"],
                                 y=[row.get("quiz1_score") or 0, row.get("recent_attendance") or 0, row.get("recent_practice") or 0],
                                 marker_color=CATEGORICAL_COLORS[0]))
    cohort_fig.add_trace(go.Bar(name="Peer average", x=["Quiz score", "Attendance", "Practice"],
                                 y=[peer_avgs["quiz"], peer_avgs["attendance"], peer_avgs["practice"]],
                                 marker_color=INK["muted"]))
    cohort_fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.15, x=0))
    cohort_fig = _apply_chart_chrome(cohort_fig, "Student vs. peer group average")
    cohort_fig.update_layout(showlegend=True)
    cohort_fig_html = cohort_fig.to_html(full_html=False, include_plotlyjs=False)

    strengths = []
    if row.get("attendance_trend") is not None and row["attendance_trend"] >= 0:
        strengths.append("Attendance has held steady or improved since Quiz 1.")
    if "RECOVERY_TRAJECTORY" in pattern_codes:
        strengths.append("Clear recent improvement in engagement since Quiz 1.")
    if "STABLE_HEALTHY_BEHAVIOR" in pattern_codes:
        strengths.append("Consistent attendance and practice habits.")
    if not strengths:
        strengths.append("Still actively enrolled and attending the program.")

    concerns = []
    if "ACUTE_ATTENDANCE_DROP" in pattern_codes:
        concerns.append("A recent, sudden drop in attendance.")
    if "CHRONIC_LOW_ATTENDANCE" in pattern_codes:
        concerns.append("Attendance has been low for an extended period.")
    if "ATTENDING_BUT_NOT_PRACTICING" in pattern_codes:
        concerns.append("Evening practice has nearly stopped despite regular attendance.")
    if "PRACTICE_COLLAPSE" in pattern_codes or "ZERO_PRACTICE_STREAK" in pattern_codes:
        concerns.append("Practice volume has dropped sharply.")
    if "LARGE_TARGET_GAP" in pattern_codes:
        concerns.append("Quiz 1 score is meaningfully below target.")
    if not concerns:
        concerns.append("No major concerns detected at this time.")

    six_day_plan = [
        f"Days 1-2: {row['next_step']}",
        f"Days 3-4: Daily practice near the peer benchmark of ~{peer_avgs['practice']:.0f} questions/day.",
        "Day 5: Short review session with the facilitator on the weakest topic.",
        "Day 6: Light review and rest before Quiz 2.",
    ]

    return {
        "student_name": row["student_name"],
        "campus_id": row["campus_id"],
        "grade": row["grade"],
        "learning_track": row["learning_track"],
        "facilitator_email": row["facilitator_email"],
        "overall_status": overall_status,
        "quiz1_score": row.get("quiz1_score"),
        "target_score": row["target_score"],
        "gap_display": gap_display,
        "attendance_fig_html": attendance_fig_html,
        "practice_fig_html": practice_fig_html,
        "cohort_fig_html": cohort_fig_html,
        "strengths_text": " ".join(strengths),
        "areas_to_improve_text": " ".join(concerns),
        "trusted_note_summary": trusted_note_summary or "No trusted facilitator notes recorded yet.",
        "six_day_plan": six_day_plan,
        "peer_benchmark_text": llm_summary,
        "generated_at": generated_at,
    }


def build_parent_report_html(ctx: dict, sections: Optional[list[str]] = None) -> str:
    all_sections = [
        "overview", "attendance_trend", "practice_trend", "cohort_comparison",
        "strengths", "areas_to_improve", "notes_summary", "six_day_plan", "peer_benchmark",
    ]
    sections = sections or all_sections
    color = STATUS_COLORS.get(ctx["overall_status"], INK["muted"])
    icon = REPORT_STATUS_ICONS.get(ctx["overall_status"], "⚪")

    blocks = []
    blocks.append(f"""
    <div class="header">
      <h1>{ctx['student_name']}</h1>
      <div class="badge" style="background:{color}">{icon} {ctx['overall_status']}</div>
      <div class="sub">🏫 {ctx['campus_id']} · 🎓 Grade {ctx['grade']} · {ctx['learning_track']} track · 👤 {ctx['facilitator_email']}</div>
    </div>""")

    if "overview" in sections:
        quiz_display = ctx['quiz1_score'] if ctx['quiz1_score'] is not None else "Not recorded"
        blocks.append(f"""
        <div class="card">
          <h2>📋 Overview</h2>
          <div class="statrow">
            <div class="stat"><div class="v">{quiz_display}</div><div class="l">Quiz 1 score</div></div>
            <div class="stat"><div class="v">{ctx['target_score']:.0f}</div><div class="l">Target score</div></div>
            <div class="stat"><div class="v">{ctx['gap_display']}</div><div class="l">Gap to target</div></div>
          </div>
        </div>""")

    if "attendance_trend" in sections and ctx.get("attendance_fig_html"):
        blocks.append(f'<div class="card"><h2>📈 Attendance trend</h2>{ctx["attendance_fig_html"]}</div>')
    if "practice_trend" in sections and ctx.get("practice_fig_html"):
        blocks.append(f'<div class="card"><h2>✏️ Practice trend</h2>{ctx["practice_fig_html"]}</div>')
    if "cohort_comparison" in sections and ctx.get("cohort_fig_html"):
        blocks.append(f'<div class="card"><h2>👥 Compared with peers</h2>{ctx["cohort_fig_html"]}</div>')

    if "strengths" in sections:
        blocks.append(f'<div class="card"><h2>💪 Strengths</h2><p>{ctx["strengths_text"]}</p></div>')
    if "areas_to_improve" in sections:
        blocks.append(f'<div class="card"><h2>🎯 Areas to improve</h2><p>{ctx["areas_to_improve_text"]}</p></div>')
    if "notes_summary" in sections:
        blocks.append(f'<div class="card"><h2>📝 Facilitator note summary</h2><p>{ctx["trusted_note_summary"]}</p></div>')
    if "six_day_plan" in sections:
        items = "".join(f"<li>{b}</li>" for b in ctx["six_day_plan"])
        blocks.append(f'<div class="card"><h2>📅 6-day plan before Quiz 2</h2><ul>{items}</ul></div>')
    if "peer_benchmark" in sections:
        blocks.append(f"""
        <div class="card">
          <h2>📊 Peer Benchmark Estimate</h2>
          <p class="note">This is a reference point from similar students, not a guaranteed outcome.</p>
          <p>{ctx['peer_benchmark_text']}</p>
        </div>""")

    blocks.append(f'<div class="footer">Generated {ctx["generated_at"]} · Boon Academy Intervention Command Center</div>')

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Parent report — {ctx['student_name']}</title>
<style>
body {{ font-family: {FONT_FAMILY}; margin:0; background:{PAGE_PLANE}; color:{INK['primary']};}}
.header {{ background:#fff; padding:20px 28px; border-bottom:4px solid {color}; }}
.header h1 {{ margin:0 0 6px 0; font-size:24px; }}
.badge {{ display:inline-block; color:#fff; padding:4px 12px; border-radius:12px; font-size:13px; font-weight:600;}}
.sub {{ color:{INK['secondary']}; font-size:13px; margin-top:6px;}}
.card {{ background:#fff; margin:14px 28px; padding:16px 20px; border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,0.08);}}
.card h2 {{ font-size:16px; margin-top:0; color:{INK['primary']};}}
.statrow {{ display:flex; gap:24px; }}
.stat .v {{ font-size:22px; font-weight:700; color:{INK['primary']};}}
.stat .l {{ font-size:12px; color:{INK['secondary']};}}
.note {{ font-size:12px; color:{INK['muted']}; font-style:italic;}}
.footer {{ text-align:center; color:{INK['muted']}; font-size:12px; padding:20px;}}
</style></head><body>
{''.join(blocks)}
</body></html>"""
