"""Streamlit UI. Thin on purpose: every calculation (features, patterns,
risk, actions, coverage) lives in src/ and main.py — this file only reads
those results, renders them, and writes back the small set of mutations a
facilitator can make (a note, a metric, an intervention status change).
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

import main as pipeline
from src import llm as llm_mod
from src import outputs as outputs_mod
from src import reports as reports_mod
from src.config import (
    CATEGORICAL_COLORS,
    DARK_ACCENT,
    DARK_BG,
    DARK_BG_DEEP,
    DARK_BORDER,
    DARK_GRIDLINE,
    DARK_INK,
    DARK_SURFACE,
    DARK_SURFACE_RAISED,
    MONO_FONT,
    RISK_COLORS,
    RISK_ICONS,
    SETTINGS,
    TARGET_COVERAGE,
)
from src.db import (
    AvailabilitySlot,
    Campus,
    FacilitatorNote,
    Intervention,
    Notification,
    Student,
    User,
    DailyMetric,
    get_user_by_email,
    hash_password,
    init_db,
    mark_onboarding_seen,
    session_scope,
    verify_password,
)

st.set_page_config(page_title="Boon Academy Intervention Command Center", page_icon="📚",
                    layout="wide", initial_sidebar_state="expanded")

STATUS_LABELS = {
    "recommended": "Recommended", "in_progress": "In progress", "attempted": "Attempted",
    "no_answer": "No answer", "message_sent": "Message sent", "booked": "Booked",
    "completed": "Completed", "follow_up_required": "Follow-up required",
    "escalated": "Escalated", "resolved": "Resolved",
}
STATUS_ICONS = {
    "recommended": "🆕", "in_progress": "🔄", "attempted": "☎️",
    "no_answer": "🔇", "message_sent": "✉️", "booked": "📅",
    "completed": "✅", "follow_up_required": "🔁", "escalated": "⬆️", "resolved": "✔️",
}
# One icon per nav destination — keeps the internal page keys (used throughout
# for routing) untouched; icons are applied only at render time via format_func.
NAV_ICONS = {
    "My Day": "🏠", "My Students": "👥", "Student Detail": "🔍", "Actions": "🎯",
    "Parent Calls": "📞", "Calendar": "📅", "Data Entry": "📝", "Admin": "🛠️",
}

# Design system for the app chrome — dark, technical, high-contrast, built
# from patterns actually measured on motion.dev (see src/config.py's DARK_*
# constants for the extraction/reasoning): a warm near-black base rather
# than pure black, a monospace "eyebrow" label for technical metadata, thin
# hairline dividers, small accent-square section markers, and tight radii
# instead of soft SaaS rounding. Parent-facing documents (src/reports.py)
# intentionally stay on the light palette — this is for the app shell only.
st.markdown(f"""
<style>
:root {{
  --space-xs: 6px; --space-sm: 10px; --space-md: 16px; --space-lg: 24px;
  --radius: 8px; --radius-pill: 999px;
  --shadow: 0 1px 3px rgba(0,0,0,0.24);
  --bg: {DARK_BG}; --bg-deep: {DARK_BG_DEEP}; --surface: {DARK_SURFACE}; --surface-raised: {DARK_SURFACE_RAISED};
  --ink-primary: {DARK_INK['primary']}; --ink-secondary: {DARK_INK['secondary']}; --ink-muted: {DARK_INK['muted']};
  --border: {DARK_BORDER}; --accent: {DARK_ACCENT};
  --mono: {MONO_FONT};
}}
h1, h2, h3 {{ letter-spacing: -0.02em; font-weight: 700; }}

/* Monospace technical eyebrow label, e.g. "// DAY 14 · QUIZ 2 IN 6 DAYS" */
.eyebrow {{
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--ink-muted); margin: 0 0 6px 0; display: flex; align-items: center; gap: 8px;
}}
.eyebrow .rule {{ flex: 1; height: 1px; background: var(--border); }}

/* Small accent square before a section heading, mirroring motion.dev's
   section markers — a cheap, distinctive way to mark a new section. */
.section-marker {{ display: inline-block; width: 9px; height: 9px; background: var(--accent);
  margin-right: 8px; vertical-align: middle; }}

.kpi-card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: var(--space-md); text-align: left; box-shadow: var(--shadow);
  transition: border-color 0.15s ease, transform 0.15s ease;
}}
.kpi-card:hover {{ border-color: var(--accent); }}
.kpi-icon {{ font-size: 18px; margin-bottom: 2px; }}
.kpi-value {{ font-size: 28px; font-weight: 700; margin: 0; color: var(--ink-primary); font-variant-numeric: tabular-nums; }}
.kpi-label {{ font-size: 12px; margin: 2px 0 0 0; color: var(--ink-secondary); }}
.badge {{
  display: inline-block; padding: 3px 12px; border-radius: var(--radius-pill);
  font-size: 12px; font-weight: 700;
}}
.status-chip {{
  display: inline-block; padding: 3px 10px; border-radius: var(--radius-pill);
  font-size: 11px; font-weight: 600; font-family: var(--mono); letter-spacing: 0.03em;
  background: var(--surface-raised); color: var(--ink-secondary); border: 1px solid var(--border);
}}
.priority-card {{
  border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface);
  padding: var(--space-md); margin-bottom: var(--space-sm); box-shadow: var(--shadow);
}}
.section-caption {{ color: var(--ink-muted); font-size: 13px; margin-top: -6px; }}
[data-testid="stSidebar"] {{ border-right: 1px solid var(--border); background: var(--bg-deep); }}

/* Dotted hairline divider, echoing motion.dev's dotted section separators */
.dotted-rule {{
  height: 1px; margin: 18px 0; background-image: radial-gradient(circle, var(--border) 1px, transparent 1px);
  background-size: 6px 1px; background-repeat: repeat-x;
}}
</style>
""", unsafe_allow_html=True)


def eyebrow(text: str) -> None:
    """A small monospace technical label with a trailing hairline rule —
    used at the top of a page to anchor it in the Day 14 / Quiz 2 clock."""
    st.markdown(f'<div class="eyebrow">// {text}<div class="rule"></div></div>', unsafe_allow_html=True)


def section_header(text: str) -> None:
    """A section heading with a small accent-square marker before it."""
    st.markdown(f'<h3><span class="section-marker"></span>{text}</h3>', unsafe_allow_html=True)

# One explanation per column concept, applied to every table below via
# with_column_help() — keyed by whatever label a table happens to show it
# under (raw field name or a human-friendly rename), so a facilitator never
# has to guess what a number means.
COLUMN_HELP = {
    "ID": "Unique student identifier from the source roster.",
    "student_id": "Unique student identifier from the source roster.",
    "Student": "Student's full name.",
    "student_name": "Student's full name.",
    "Track": "Learning track — used only as peer-comparison context, never to penalize risk.",
    "learning_track": "Learning track — used only as peer-comparison context, never to penalize risk.",
    "Quiz 1": "Score on Quiz 1 (out of 100). Blank means no score is recorded yet for this student.",
    "quiz1_score": "Score on Quiz 1 (out of 100). Blank means no score is recorded yet for this student.",
    "Target": "This student's individual target score.",
    "target_score": "This student's individual target score.",
    "gap_to_target": "Target score minus Quiz 1 score. Positive means still below target.",
    "Attendance Δ": "Change in attendance (minutes/day) since Quiz 1, vs. this student's own pre-Quiz-1 baseline.",
    "attendance_trend": "Change in attendance (minutes/day) since Quiz 1, vs. this student's own pre-Quiz-1 baseline.",
    "Practice Δ": "Change in practice questions/day since Quiz 1, vs. this student's own pre-Quiz-1 baseline.",
    "practice_trend": "Change in practice questions/day since Quiz 1, vs. this student's own pre-Quiz-1 baseline.",
    "Risk": "Critical / High / Medium / Low — a deterministic 0-100 score from performance, engagement, "
            "trajectory, trusted notes, and intervention gap. Never set by the LLM.",
    "risk_level": "Critical / High / Medium / Low — a deterministic 0-100 score from performance, engagement, "
                  "trajectory, trusted notes, and intervention gap. Never set by the LLM.",
    "Priority": "0-100 blend of risk (80%) and urgency (20% — days left before Quiz 2, overdue work). "
                "Sets the daily queue order.",
    "priority_score": "0-100 blend of risk (80%) and urgency (20% — days left before Quiz 2, overdue work). "
                       "Sets the daily queue order.",
    "Confidence": "How complete the underlying data is — lower when attendance is missing, a note's ownership "
                  "is unverified, or the quiz score is absent.",
    "confidence": "How complete the underlying data is — lower when attendance is missing, a note's ownership "
                  "is unverified, or the quiz score is absent.",
    "Next action": "The single rule-based recommended action for this student right now.",
    "recommended_action": "The single rule-based recommended action for this student right now.",
    "action_type": "The recommended or in-progress action for this student.",
    "priority": "Risk level at the time this action was recommended.",
    "due_date": "When this action should be completed by, based on how urgent its type is (its SLA).",
    "status": "recommended → in_progress/attempted/no_answer → completed/resolved/message_sent/booked. "
              "A bare recommendation or a no-answer call never counts as a successful interaction.",
    "campus_id": "Campus code the student is enrolled at.",
    "facilitator_email": "The facilitator assigned to this student.",
    "grade": "Student's grade level.",
    "name": "Campus display name.",
    "students": "Number of active students currently assigned to this facilitator.",
    "critical": "Number of this facilitator's students currently at Critical risk.",
    "high": "Number of this facilitator's students currently at High risk.",
    "check": "Which data-quality rule fired — see src/validation.py for its exact logic.",
    "severity": "info = worth noting; warning = should be reviewed; error = affected rows were dropped.",
    "count": "How many rows this check flagged.",
    "description": "What the check looked for and why it matters.",
    "sample_student_ids": "A few example student IDs affected by this check.",
    "topic": "What the session is about.",
    "start": "Scheduled start time.",
    "link": "Shareable booking link — the student picks a time with no login needed.",
    "date": "The day this metric was recorded for.",
    "attendance_min": "Minutes attended that day (0-90). Missing means not recorded — never treated as zero.",
    "practice_questions": "Practice questions completed that day. Values above 60 are flagged as an anomaly "
                           "but kept, not deleted — it may be a real cramming burst.",
    "errors": "Why this row was rejected from the import.",
    "note_text": "The facilitator's original note, in their own words.",
    "parent_phone": "Parent/guardian contact number.",
    "student_name": "Student's full name.",
    "grade": "Student's grade level.",
    "learning_track": "Learning track — used only as peer-comparison context, never to penalize risk.",
    "campus_id": "Campus code the student is enrolled at.",
}


def with_column_help(df: pd.DataFrame) -> dict:
    return {col: st.column_config.Column(help=COLUMN_HELP[col]) for col in df.columns if col in COLUMN_HELP}


# --- Session-state helpers -------------------------------------------------

def get_computed(force: bool = False) -> dict:
    if force or "computed" not in st.session_state:
        with st.spinner("Recomputing risk and priorities..."):
            st.session_state.computed = pipeline.recompute_all()
    return st.session_state.computed


def refresh_and_rerun() -> None:
    get_computed(force=True)
    st.rerun()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def risk_badge(level: str) -> str:
    # Status color is never the only signal — the icon (a colored circle)
    # repeats the same meaning so the badge still reads for colorblind users.
    # On the dark surface, a soft tinted badge (colored text/border on a low-
    # opacity fill) reads better across all four hues than a solid fill,
    # which would need a different text color per hue to stay legible.
    color = RISK_COLORS.get(level, DARK_INK["muted"])
    icon = RISK_ICONS.get(level, "⚪")
    r, g, b = _hex_to_rgb(color)
    style = f"background:rgba({r},{g},{b},0.16); color:{color}; border:1px solid rgba({r},{g},{b},0.4);"
    return f'<span class="badge" style="{style}">{icon} {level}</span>'


def status_chip(status: str) -> str:
    icon = STATUS_ICONS.get(status, "•")
    label = STATUS_LABELS.get(status, status)
    return f'<span class="status-chip">{icon} {label}</span>'


def chart_chrome(fig: go.Figure, title: str, height: int = 300) -> go.Figure:
    """Dark chart chrome matching the app shell (src/reports.py's exported,
    parent-facing documents intentionally stay on the light palette — this
    is only for charts rendered live inside the app)."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=DARK_INK["primary"])),
        font=dict(color=DARK_INK["secondary"], size=12),
        height=height,
        margin=dict(l=40, r=20, t=44, b=32),
        plot_bgcolor=DARK_SURFACE, paper_bgcolor=DARK_SURFACE,
    )
    fig.update_xaxes(gridcolor=DARK_GRIDLINE, linecolor=DARK_GRIDLINE, zeroline=False)
    fig.update_yaxes(gridcolor=DARK_GRIDLINE, linecolor=DARK_GRIDLINE, zeroline=False)
    return fig


def fmt_pct(value: float) -> str:
    """1 decimal place, not 0 — with a few hundred students, one real
    success can be a rate like 0.5%, and Python's `.0f` formatting rounds
    that *down* to "0%" (round-half-to-even), which would make genuine
    progress invisible right after the first completed interaction."""
    return f"{value:.1f}%"


def kpi(col, value, label, icon: str = "", help_text: str = "") -> None:
    icon_html = f'<div class="kpi-icon">{icon}</div>' if icon else ""
    title_attr = f' title="{help_text}"' if help_text else ""
    col.markdown(f'<div class="kpi-card"{title_attr}>{icon_html}<p class="kpi-value">{value}</p>'
                 f'<p class="kpi-label">{label}</p></div>', unsafe_allow_html=True)


def open_intervention_for(interventions_df: pd.DataFrame, student_id: str) -> dict | None:
    rows = interventions_df[interventions_df["student_id"] == student_id]
    if rows.empty:
        return None
    open_rows = rows[rows["status"].isin(outputs_mod.OPEN_STATUSES)]
    chosen = open_rows.iloc[-1] if not open_rows.empty else rows.iloc[-1]
    return chosen.to_dict()


def set_intervention_status(student_id: str, facilitator_email: str, action_type: str, priority: str,
                             due_date: date, status: str, outcome: str | None = None) -> None:
    with session_scope() as session:
        existing = session.scalars(
            select(Intervention).where(Intervention.student_id == student_id).order_by(Intervention.id.desc())
        ).first()
        if existing is not None:
            existing.status = status
            if outcome is not None:
                existing.outcome = outcome
            if status in ("completed", "resolved"):
                existing.completed_at = datetime.utcnow()
        else:
            session.add(Intervention(
                student_id=student_id, facilitator_email=facilitator_email, action_type=action_type,
                priority=priority, due_date=due_date, status=status, outcome=outcome,
                completed_at=datetime.utcnow() if status in ("completed", "resolved") else None,
            ))


# --- Login ------------------------------------------------------------------

def render_login() -> None:
    st.title("📚 Boon Academy Intervention Command Center")
    st.caption("Day 14 · Quiz 1 was Day 10 · Quiz 2 is Day 20 · 6 days remain")
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.form("login_form"):
            st.subheader("🔐 Sign in")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in →", use_container_width=True, type="primary")
        if submitted:
            init_db()
            with session_scope() as session:
                user = get_user_by_email(session, email.strip().lower())
                ok = user is not None and user.active and verify_password(password, user.password_hash)
                if ok:
                    st.session_state.user = {
                        "email": user.email, "role": user.role, "display_name": user.display_name,
                        "has_seen_onboarding": user.has_seen_onboarding,
                    }
            if st.session_state.get("user"):
                st.rerun()
            else:
                st.error("Invalid email or password.")
        st.info("💡 Demo credentials come from `.env` (SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD, or any "
                "facilitator email from the dataset with SEED_FACILITATOR_PASSWORD). See README.md.")


# --- My Day (facilitator home) ---------------------------------------------

def render_my_day(user: dict) -> None:
    computed = get_computed()
    risk_df = computed["risk_df"]
    interventions_df = computed["interventions_df"]
    mine = risk_df[risk_df["facilitator_email"] == user["email"]]
    my_ids = set(mine["student_id"])
    my_interventions = interventions_df[interventions_df["student_id"].isin(my_ids)]

    coverage = outputs_mod.coverage_metrics(mine, my_interventions, SETTINGS.as_of_date, TARGET_COVERAGE)

    eyebrow(f"DAY {SETTINGS.days_since_quiz1 + 10} · QUIZ 2 IN {SETTINGS.days_until_quiz2} DAYS")
    st.title("🏠 My Day")
    st.caption(f"Signed in as {user['display_name']} · {len(mine)} students assigned to you")

    action_message = st.session_state.pop("action_message", None)
    if action_message:
        st.success(action_message)

    today = SETTINGS.as_of_date
    due_today = my_interventions[(pd.to_datetime(my_interventions["due_date"]).dt.date == today) &
                                  (my_interventions["status"].isin(outputs_mod.OPEN_STATUSES))]
    overdue = my_interventions[(pd.to_datetime(my_interventions["due_date"]).dt.date < today) &
                                (my_interventions["status"].isin(outputs_mod.OPEN_STATUSES))]
    completed_today = my_interventions[my_interventions["status"].isin(["completed", "resolved"])]
    planned_minutes = mine[mine["student_id"].isin(due_today["student_id"])]["estimated_minutes"].sum()

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    kpi(c1, len(mine), "My Students", "👥", "Total active students assigned to you.")
    kpi(c2, coverage["students_needing_intervention"], "Need Intervention", "⚠️",
        "Students at Medium/High/Critical risk, or below their target score.")
    kpi(c3, fmt_pct(coverage['successful_interaction_rate']), "Successful Interaction Rate", "✅",
        "Share of students-who-need-help with a real completed/sent/booked interaction — "
        "not just a recommendation or an unanswered call.")
    kpi(c4, "80%", "Target", "🎯", "The academy-wide coverage goal for successful interactions.")
    kpi(c5, len(due_today), "Due Today", "📌", "Open actions whose due date is today.")
    kpi(c6, len(overdue), "Overdue", "⏰", "Open actions whose due date has already passed.")
    kpi(c7, int(planned_minutes), "Planned Minutes", "⏱️", "Estimated facilitator time for everything due today.")

    st.progress(min(1.0, coverage["successful_interaction_rate"] / 100),
                text=f"Progress toward 80% successful interaction rate ({fmt_pct(coverage['successful_interaction_rate'])} actual, "
                     f"{fmt_pct(coverage['projected_coverage'])} projected including today's queue)")

    st.subheader("🚨 Highest Priority Actions Today")
    needing = mine[outputs_mod.needs_intervention_mask(mine)].sort_values("priority_score", ascending=False)
    if needing.empty:
        st.success("No students currently need intervention. 🎉")
        return

    # Group by where each student's intervention actually stands, so
    # completing one moves it out of the "to do" tabs into its own Completed
    # tab instead of leaving every status mixed into one long list — the
    # tab counts themselves are the visible "the number went down" signal.
    def current_status(sid: str) -> str:
        iv = open_intervention_for(my_interventions, sid)
        return iv["status"] if iv else "recommended"

    needing = needing.copy()
    needing["_status"] = needing["student_id"].apply(current_status)

    completed_statuses = {"completed", "resolved", "message_sent", "booked"}
    followup_statuses = {"follow_up_required", "escalated"}
    attempted_statuses = {"attempted", "no_answer"}
    buckets = [
        ("🆕 Recommended", needing[needing["_status"] == "recommended"]),
        ("🔄 In Progress", needing[needing["_status"] == "in_progress"]),
        ("☎️ Attempted / No Answer", needing[needing["_status"].isin(attempted_statuses)]),
        ("🔁 Follow Up", needing[needing["_status"].isin(followup_statuses)]),
        ("✅ Completed", needing[needing["_status"].isin(completed_statuses)]),
    ]
    tabs = st.tabs([f"{name} ({len(df)})" for name, df in buckets])
    for tab, (name, df) in zip(tabs, buckets):
        with tab:
            if df.empty:
                st.info("Nothing in this category right now.")
            else:
                for _, row in df.head(15).iterrows():
                    render_priority_card(row, my_interventions)


def render_priority_card(row: pd.Series, interventions_df: pd.DataFrame) -> None:
    iv = open_intervention_for(interventions_df, row["student_id"])
    status = iv["status"] if iv else "recommended"
    with st.container(border=True):
        top = st.columns([3, 1, 1, 1])
        top[0].markdown(f"**{row['student_name']}** &nbsp; {risk_badge(row['risk_level'])}", unsafe_allow_html=True)
        top[1].metric("🎯 Priority", f"{row['priority_score']:.0f}",
                       help="0-100 blend of risk (80%) and urgency (20%) — sets this card's place in the queue.")
        top[2].metric("📶 Confidence", f"{row['confidence']:.0%}",
                       help="How complete the underlying data is for this student.")
        top[3].markdown(status_chip(status), unsafe_allow_html=True)

        patterns = row["patterns"] if isinstance(row["patterns"], list) else []
        why = patterns[0]["explanation"] if patterns else "No acute pattern detected."
        st.markdown(f"**💡 Why:** {why}")
        if patterns and patterns[0].get("evidence"):
            st.caption("📎 Evidence: " + ", ".join(f"{k}={v}" for k, v in patterns[0]["evidence"].items() if v is not None))
        st.markdown(f"**✅ Recommended:** {row['recommended_action'].replace('_', ' ').title()} · "
                    f"Due {row['due_date']} · ~{row['estimated_minutes']} min")

        btns = st.columns(6)
        sid = row["student_id"]
        name = row["student_name"]
        if btns[0].button("▶️ Start", key=f"start_{sid}", use_container_width=True):
            set_intervention_status(sid, row["facilitator_email"], row["recommended_action"], row["risk_level"],
                                     row["due_date"], "in_progress")
            st.session_state["action_message"] = f"▶️ **{name}** marked in progress — moved to the In Progress tab."
            refresh_and_rerun()
        if btns[1].button("🔇 No Answer", key=f"noans_{sid}", use_container_width=True):
            set_intervention_status(sid, row["facilitator_email"], row["recommended_action"], row["risk_level"],
                                     row["due_date"], "no_answer")
            st.session_state["action_message"] = f"🔇 Logged a no-answer attempt for **{name}** — this counts as an attempt, not a success yet."
            refresh_and_rerun()
        if btns[2].button("✅ Complete", key=f"complete_{sid}", use_container_width=True):
            set_intervention_status(sid, row["facilitator_email"], row["recommended_action"], row["risk_level"],
                                     row["due_date"], "completed")
            st.session_state["action_message"] = f"✅ **{name}**'s intervention marked complete — moved to the Completed tab and counted toward your interaction rate."
            refresh_and_rerun()
        if btns[3].button("🔁 Follow Up", key=f"followup_{sid}", use_container_width=True):
            set_intervention_status(sid, row["facilitator_email"], row["recommended_action"], row["risk_level"],
                                     row["due_date"], "follow_up_required")
            st.session_state["action_message"] = f"🔁 **{name}** flagged for follow-up — moved to the Follow Up tab."
            refresh_and_rerun()
        if btns[4].button("🔍 Open Detail", key=f"detail_{sid}", use_container_width=True):
            st.session_state.selected_student_id = sid
            st.session_state.nav_request = "Student Detail"
            st.rerun()
        if btns[5].button("✉️ Message", key=f"msg_{sid}", use_container_width=True):
            # Streamlit has no API to pre-select a tab, so this opens Student
            # Detail and the facilitator picks the "✉️ Message" tab from there.
            st.session_state.selected_student_id = sid
            st.session_state.nav_request = "Student Detail"
            st.rerun()


# --- My Students -------------------------------------------------------------

def render_my_students(user: dict) -> None:
    computed = get_computed()
    risk_df = computed["risk_df"]
    df = risk_df if user["role"] == "admin" else risk_df[risk_df["facilitator_email"] == user["email"]]

    eyebrow(f"{len(df)} STUDENTS")
    st.title("👥 My Students" if user["role"] != "admin" else "👥 All Students")
    c1, c2, c3, c4 = st.columns(4)
    campus_filter = c1.multiselect("Campus", sorted(df["campus_id"].unique()))
    risk_filter = c2.multiselect("Risk level", ["Critical", "High", "Medium", "Low"])
    track_filter = c3.multiselect("Learning track", sorted(df["learning_track"].unique()))
    action_filter = c4.multiselect("Recommended action", sorted(df["recommended_action"].unique()))

    view = df.copy()
    if campus_filter:
        view = view[view["campus_id"].isin(campus_filter)]
    if risk_filter:
        view = view[view["risk_level"].isin(risk_filter)]
    if track_filter:
        view = view[view["learning_track"].isin(track_filter)]
    if action_filter:
        view = view[view["recommended_action"].isin(action_filter)]

    view = view.sort_values("priority_score", ascending=False)
    display_cols = ["student_id", "student_name", "learning_track", "quiz1_score", "target_score",
                     "attendance_trend", "practice_trend", "risk_level", "priority_score", "confidence",
                     "recommended_action"]
    display_df = view[display_cols].rename(columns={
        "student_id": "ID", "student_name": "Student", "learning_track": "Track", "quiz1_score": "Quiz 1",
        "target_score": "Target", "attendance_trend": "Attendance Δ", "practice_trend": "Practice Δ",
        "risk_level": "Risk", "priority_score": "Priority", "confidence": "Confidence",
        "recommended_action": "Next action",
    })
    st.dataframe(display_df, use_container_width=True, height=420, column_config=with_column_help(display_df))

    st.caption("Pick a student to open their full detail view:")
    chosen = st.selectbox("Student", view["student_id"] + " — " + view["student_name"], index=None,
                          placeholder="Search by ID or name...")
    if chosen and st.button("🔍 Open Student Detail"):
        st.session_state.selected_student_id = chosen.split(" — ")[0]
        st.session_state.nav_request = "Student Detail"
        st.rerun()


# --- Student Detail -----------------------------------------------------------

def render_student_detail(user: dict) -> None:
    sid = st.session_state.get("selected_student_id")
    if not sid:
        st.title("🔍 Student Detail")
        st.info("Select a student from **My Students** first.")
        return

    computed = get_computed()
    risk_df = computed["risk_df"]
    row_matches = risk_df[risk_df["student_id"] == sid]
    if row_matches.empty:
        st.error("Student not found.")
        return
    row = row_matches.iloc[0]
    if user["role"] != "admin" and row["facilitator_email"] != user["email"]:
        st.error("You do not have access to this student.")
        return

    title_col, badge_col = st.columns([5, 1])
    title_col.title(f"🧑‍🎓 {row['student_name']}")
    badge_col.markdown(f"<div style='margin-top:28px'>{risk_badge(row['risk_level'])}</div>", unsafe_allow_html=True)
    st.caption(f"🆔 {row['student_id']} · 🏫 {row['campus_id']} · 🎓 Grade {row['grade']} · {row['learning_track']} track · "
               f"🧑‍🏫 {row['facilitator_email']}")

    tabs = st.tabs(["📋 Overview", "📈 Trends", "👥 Peer Comparison", "📝 Notes",
                    "✉️ Message", "🎯 Interventions", "📄 Parent Report", "🕒 Timeline"])

    with tabs[0]:
        c1, c2, c3, c4 = st.columns(4)
        quiz_display = row["quiz1_score"] if pd.notna(row["quiz1_score"]) else "Not recorded"
        c1.metric("Quiz 1 vs Target", f"{quiz_display} / {row['target_score']:.0f}",
                   help="Quiz 1 score out of this student's individual target score.")
        c2.metric("Risk", row["risk_level"], help=f"Risk score {row['risk_score']:.1f}/100 — deterministic, "
                  "never set by the LLM. See the Overview patterns/reason codes below for why.")
        c3.metric("Priority", f"{row['priority_score']:.0f}",
                   help="0-100 blend of risk (80%) and urgency (20% — days left, overdue work).")
        c4.metric("Confidence", f"{row['confidence']:.0%}",
                   help="How complete the underlying data is — lower when attendance/quiz data is missing "
                        "or a note is unverified.")

        st.markdown("#### ⚠️ Detected patterns")
        patterns = row["patterns"] if isinstance(row["patterns"], list) else []
        if not patterns:
            st.write("No behavioral patterns detected.")
        for p in patterns:
            with st.container(border=True):
                st.markdown(f"**{p['code']}** — {p['explanation']}")
                st.caption("Evidence: " + ", ".join(f"{k}={v}" for k, v in p["evidence"].items() if v is not None))

        st.markdown("#### 📌 Reason codes")
        st.write(", ".join(row["reason_codes"]) if row["reason_codes"] else "None")

        st.markdown("#### ✅ Recommended action")
        st.success(f"**{row['recommended_action'].replace('_', ' ').title()}** — {row['action_brief']}\n\n"
                   f"Next step: {row['next_step']} (due {row['due_date']}, ~{row['estimated_minutes']} min)")

    with tabs[1]:
        metrics_df = computed["metrics_df"]
        student_metrics = metrics_df[metrics_df["student_id"] == sid].sort_values("date")
        fig_a = go.Figure(go.Scatter(x=student_metrics["date"], y=student_metrics["session_attended_min"],
                                      mode="lines+markers", name="Attendance",
                                      line=dict(color=CATEGORICAL_COLORS[0], width=2),
                                      marker=dict(size=8, color=CATEGORICAL_COLORS[0])))
        st.plotly_chart(chart_chrome(fig_a, "📈 Attendance (minutes/day)"), use_container_width=True)
        fig_p = go.Figure(go.Scatter(x=student_metrics["date"], y=student_metrics["practice_questions"],
                                      mode="lines+markers", name="Practice",
                                      line=dict(color=CATEGORICAL_COLORS[1], width=2),
                                      marker=dict(size=8, color=CATEGORICAL_COLORS[1])))
        st.plotly_chart(chart_chrome(fig_p, "✏️ Practice (questions/day)"), use_container_width=True)

    with tabs[2]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Quiz percentile", f"{row['quiz_percentile']:.0f}",
                   help="Where this student's Quiz 1 score ranks within their peer group (100 = highest).")
        c2.metric("Attendance percentile", f"{row['attendance_percentile']:.0f}",
                   help="Where this student's recent attendance ranks within their peer group.")
        c3.metric("Practice percentile", f"{row['practice_percentile']:.0f}",
                   help="Where this student's recent practice volume ranks within their peer group.")
        st.caption(f"Peer group: {row['peer_group']} — grade+track when that group is large enough, "
                   "otherwise the full cohort.")

    with tabs[3]:
        render_notes_tab(user, sid, row)

    with tabs[4]:
        render_message_tab(user, sid, row)

    with tabs[5]:
        render_interventions_tab(sid, row, computed["interventions_df"])

    with tabs[6]:
        render_parent_report_tab(user, sid, row, computed)

    with tabs[7]:
        render_timeline_tab(sid, computed)


def render_notes_tab(user: dict, sid: str, row: pd.Series) -> None:
    change_message = st.session_state.pop(f"note_change_message_{sid}", None)
    if change_message:
        st.success(change_message)

    notes_df = get_computed()["notes_df"]
    student_notes = notes_df[notes_df["student_id"] == sid].sort_values("date")
    for _, n in student_notes.iterrows():
        trust_color = {"trusted": "#2e7d32", "unverified_ownership": "#d35400", "orphan": "#c0392b"}.get(n["trust_status"], "#777")
        with st.container(border=True):
            st.markdown(f"**{n['date']}** &nbsp; "
                        f'<span class="badge" style="background:{trust_color}">{n["trust_status"]}</span>',
                        unsafe_allow_html=True)
            st.write(n["note_text"])
            if n["ai_summary"]:
                st.caption(f"AI summary: {n['ai_summary']} · barrier: {n['ai_barrier']} · "
                           f"severity: {n['ai_severity']} · follow-up needed: {n['ai_follow_up_needed']}")
            else:
                st.caption("Not analyzed (untrusted note — excluded from qualitative risk and parent communication).")

    st.markdown("#### 📝 Add a note")
    with st.form(f"add_note_{sid}"):
        text = st.text_area("Note text", placeholder="e.g. اتصلت على ولي الأمر بخصوص الغياب...")
        submitted = st.form_submit_button("💾 Save note")
    if submitted and text.strip():
        note_id = f"UI-{secrets.token_hex(4)}"
        with session_scope() as session:
            session.add(FacilitatorNote(
                note_id=note_id, student_id=sid, facilitator_email=user["email"],
                date=SETTINGS.as_of_date, note_text=text.strip(), trust_status="trusted",
            ))
        before_level, before_priority = row["risk_level"], row["priority_score"]
        get_computed(force=True)
        after = get_computed()["risk_df"]
        after_row = after[after["student_id"] == sid].iloc[0]
        if after_row["risk_level"] != before_level or abs(after_row["priority_score"] - before_priority) >= 0.5:
            message = (f"Note saved and analyzed. Risk changed: {before_level} ({before_priority:.0f}) → "
                       f"{after_row['risk_level']} ({after_row['priority_score']:.0f}).")
        else:
            message = "Note saved and analyzed. No material change to risk/priority."
        # Streamlit wipes any st.success() shown right before st.rerun(), so
        # the message is staged here and displayed on the next run instead.
        st.session_state[f"note_change_message_{sid}"] = message
        st.rerun()


def _positive_fact_for(row: pd.Series) -> str | None:
    """Only ever returns something backed by an actual computed signal — the
    motivational message must never invent a positive fact that isn't real."""
    patterns = set(row.get("pattern_codes") or [])
    if "RECOVERY_TRAJECTORY" in patterns:
        return "لاحظنا تحسناً واضحاً في التزامك مؤخراً"
    if "STABLE_HEALTHY_BEHAVIOR" in patterns:
        return "لاحظنا التزامك المستمر بالحضور والتمرين"
    if row.get("attendance_trend") is not None and row["attendance_trend"] >= 0:
        return "لاحظنا التزامك بالحضور هذا الأسبوع"
    if row.get("practice_trend") is not None and row["practice_trend"] >= 0:
        return "لاحظنا استمرارك في حل التمارين"
    return None


def render_message_tab(user: dict, sid: str, row: pd.Series) -> None:
    sent_notice = st.session_state.pop(f"msg_sent_notice_{sid}", None)
    if sent_notice:
        st.success(sent_notice)

    st.caption("Generate a short, personalized motivational message in Arabic — built only from verified "
               "data below, never invented details.")
    positive_fact = _positive_fact_for(row)
    if positive_fact:
        st.caption(f"✅ Verified positive fact available: _{positive_fact}_")
    else:
        st.caption("ℹ️ No standout positive fact detected yet — the message will focus on encouragement + next step.")

    variant_key = f"msg_variant_{sid}"
    text_key = f"msg_text_{sid}"

    gen_col, regen_col = st.columns(2)
    if gen_col.button("🧠 Generate Message", key=f"gen_msg_{sid}", use_container_width=True, type="primary"):
        st.session_state[variant_key] = 0
        text, _log = llm_mod.generate_motivational_message({
            "student_id": sid, "first_name": row["student_name"].split()[0],
            "positive_fact": positive_fact, "next_step": row["next_step"], "variant": 0,
        })
        st.session_state[text_key] = text
    if regen_col.button("🔄 Regenerate", key=f"regen_msg_{sid}", use_container_width=True,
                         disabled=text_key not in st.session_state):
        st.session_state[variant_key] = st.session_state.get(variant_key, 0) + 1
        text, _log = llm_mod.generate_motivational_message({
            "student_id": sid, "first_name": row["student_name"].split()[0],
            "positive_fact": positive_fact, "next_step": row["next_step"], "variant": st.session_state[variant_key],
        })
        st.session_state[text_key] = text

    if text_key in st.session_state:
        edited = st.text_area("✏️ Edit before sending", value=st.session_state[text_key], height=120, key=f"edit_{sid}")
        st.session_state[text_key] = edited
        st.caption("📋 Copy — hover the box below and click its copy icon:")
        st.code(edited, language=None)

        if st.button("✅ Mark as Sent", key=f"send_msg_{sid}", type="primary"):
            with session_scope() as session:
                session.add(Notification(
                    student_id=sid, facilitator_email=user["email"], channel="student_message",
                    sections="[]", content=edited, status="simulated_sent",
                ))
            set_intervention_status(sid, user["email"], row["recommended_action"], row["risk_level"],
                                     row["due_date"], "message_sent",
                                     outcome=f"Motivational message sent: {edited[:150]}")
            st.session_state[f"msg_sent_notice_{sid}"] = (
                "Message marked as sent (dry-run) and logged as a completed interaction — "
                "this is what actually moves the successful-interaction rate, not the draft itself.")
            del st.session_state[text_key]
            st.session_state.pop(variant_key, None)
            refresh_and_rerun()
    else:
        st.info("Click **Generate Message** to draft a personalized note.")


def render_interventions_tab(sid: str, row: pd.Series, interventions_df: pd.DataFrame) -> None:
    mine = interventions_df[interventions_df["student_id"] == sid].sort_values("created_at")
    if mine.empty:
        st.info("No interventions recorded yet.")
    for _, iv in mine.iterrows():
        with st.container(border=True):
            st.markdown(f"**{iv['action_type'].replace('_', ' ').title()}** — status: "
                        f"**{STATUS_LABELS.get(iv['status'], iv['status'])}** · due {iv['due_date']}")
            if iv["outcome"]:
                st.caption(f"Outcome: {iv['outcome']}")


def render_parent_report_tab(user: dict, sid: str, row: pd.Series, computed: dict) -> None:
    all_sections = ["overview", "attendance_trend", "practice_trend", "cohort_comparison",
                     "strengths", "areas_to_improve", "notes_summary", "six_day_plan", "peer_benchmark"]
    sections = st.multiselect("Sections to include", all_sections, default=all_sections)

    if st.button("📄 Generate / Refresh Preview", key=f"gen_report_{sid}"):
        risk_df = computed["risk_df"]
        peer_rows = risk_df[risk_df["peer_group"] == row["peer_group"]]
        peer_avgs = {"quiz": peer_rows["quiz1_score"].mean(), "attendance": peer_rows["recent_attendance"].mean(),
                     "practice": peer_rows["recent_practice"].mean()}
        notes_df = computed["notes_df"]
        trusted = notes_df[(notes_df["student_id"] == sid) & (notes_df["trust_status"] == "trusted")]
        trusted_summary = " ".join(n for n in trusted["ai_summary"].dropna().tolist()) or "No trusted notes yet."
        summary_text, log = llm_mod.generate_parent_report_summary({
            "student_id": sid, "first_name": row["student_name"].split()[0],
            "quiz1_score": row["quiz1_score"], "target_score": row["target_score"],
            "overall_status": reports_mod.overall_status_for(row["risk_level"], set(row["pattern_codes"])),
            "peer_quiz_avg": peer_avgs["quiz"], "peer_attendance_avg": peer_avgs["attendance"],
            "peer_practice_avg": peer_avgs["practice"],
        })
        student_metrics = computed["metrics_df"]
        student_metrics = student_metrics[student_metrics["student_id"] == sid]
        ctx = reports_mod.assemble_parent_context(row.to_dict(), student_metrics, peer_avgs, trusted_summary,
                                                   summary_text, datetime.utcnow().isoformat())
        st.session_state[f"report_html_{sid}"] = reports_mod.build_parent_report_html(ctx, sections)
        st.session_state[f"report_text_{sid}"] = summary_text

    html = st.session_state.get(f"report_html_{sid}")
    if html:
        import streamlit.components.v1 as components
        components.html(html, height=700, scrolling=True)

        st.markdown("#### 📤 Notify Parent (dry-run)")
        with st.form(f"notify_{sid}"):
            channel = st.radio("Channel", ["email", "whatsapp"], horizontal=True)
            preview = st.text_area("Message preview (editable)", value=st.session_state.get(f"report_text_{sid}", ""))
            confirm = st.form_submit_button("📤 Send (simulated)")
        if confirm:
            with session_scope() as session:
                session.add(Notification(
                    student_id=sid, facilitator_email=user["email"], channel=channel,
                    sections=str(sections), content=preview,
                    status="simulated_sent" if SETTINGS.notification_mode == "dry_run" else "failed",
                ))
            st.success(f"Simulated {channel} sent (dry-run) and saved to the outbox. No real message was delivered.")


def render_timeline_tab(sid: str, computed: dict) -> None:
    events = []
    metrics_df = computed["metrics_df"]
    for _, m in metrics_df[metrics_df["student_id"] == sid].iterrows():
        label = f"Attendance {m['session_attended_min']}, Practice {m['practice_questions']}"
        if pd.notna(m["last_quiz_score"]):
            label += f", Quiz score {m['last_quiz_score']}"
        events.append((m["date"], "Metric", label))
    for _, n in computed["notes_df"][computed["notes_df"]["student_id"] == sid].iterrows():
        events.append((n["date"], "Note", n["note_text"][:80]))
    for _, iv in computed["interventions_df"][computed["interventions_df"]["student_id"] == sid].iterrows():
        events.append((pd.to_datetime(iv["created_at"]).date(), "Intervention",
                        f"{iv['action_type']} → {iv['status']}"))

    events.sort(key=lambda e: e[0])
    for d, kind, label in events:
        st.markdown(f"**{d}** · _{kind}_ — {label}")


# --- Actions page -------------------------------------------------------------

def render_actions(user: dict) -> None:
    computed = get_computed()
    risk_df = computed["risk_df"]
    interventions_df = computed["interventions_df"]
    df = risk_df if user["role"] == "admin" else risk_df[risk_df["facilitator_email"] == user["email"]]
    iv = interventions_df[interventions_df["student_id"].isin(df["student_id"])].copy()
    iv["due_date"] = pd.to_datetime(iv["due_date"]).dt.date
    iv = iv.merge(df[["student_id", "student_name", "risk_level", "priority_score"]], on="student_id", how="left")

    eyebrow("STATUS QUEUE")
    st.title("🎯 Actions")
    today = SETTINGS.as_of_date
    buckets = {
        "📌 Due Today": iv[(iv["due_date"] == today) & iv["status"].isin(outputs_mod.OPEN_STATUSES)],
        "⏰ Overdue": iv[(iv["due_date"] < today) & iv["status"].isin(outputs_mod.OPEN_STATUSES)],
        "🔄 In Progress": iv[iv["status"] == "in_progress"],
        "🔇 No Answer": iv[iv["status"] == "no_answer"],
        "🔁 Follow Up": iv[iv["status"] == "follow_up_required"],
        "✅ Completed": iv[iv["status"].isin(["completed", "resolved", "message_sent", "booked"])],
    }
    tabs = st.tabs([f"{label} ({len(sub)})" for label, sub in buckets.items()])
    for tab, (label, sub) in zip(tabs, buckets.items()):
        with tab:
            if sub.empty:
                st.write("Nothing here.")
            else:
                bucket_df = sub.sort_values("priority_score", ascending=False)[
                    ["student_id", "student_name", "action_type", "priority", "due_date", "status"]
                ]
                # Explicit key (six tabs render structurally identical dataframes)
                # AND an explicit height: left to auto-size, Streamlit's grid
                # recalculates its height against the row count on every layout
                # pass, which for a large bucket (dozens of rows) triggered a
                # measure -> resize -> measure loop and crashed with React's
                # "Maximum update depth exceeded". A fixed height stops the loop.
                st.dataframe(bucket_df, use_container_width=True, column_config=with_column_help(bucket_df),
                             key=f"actions_bucket_{label}", height=380)


# --- Parent Calls page ---------------------------------------------------------

def render_parent_calls(user: dict) -> None:
    computed = get_computed()
    risk_df = computed["risk_df"]
    mine = risk_df[(risk_df["facilitator_email"] == user["email"]) & (risk_df["recommended_action"] == "PARENT_CALL")]
    mine = mine.sort_values("priority_score", ascending=False)

    st.title("📞 Parents to Contact Today")
    if mine.empty:
        st.success("No urgent parent calls needed right now.")
    for _, row in mine.iterrows():
        with st.container(border=True):
            st.markdown(f"**{row['student_name']}** {risk_badge(row['risk_level'])}", unsafe_allow_html=True)
            st.caption(row["action_brief"])
            if st.button("🧠 Generate Call Brief", key=f"brief_{row['student_id']}"):
                brief, _ = llm_mod.generate_parent_call_brief({
                    "student_id": row["student_id"], "first_name": row["student_name"].split()[0],
                    "concern": row["action_brief"], "supporting_data": "; ".join(row["reason_codes"]),
                    "recommended_action": row["next_step"], "positive_fact": None,
                })
                st.session_state[f"brief_text_{row['student_id']}"] = brief

            brief = st.session_state.get(f"brief_text_{row['student_id']}")
            if brief:
                for key in ["opening", "positive_fact", "concern", "supporting_data",
                            "recommended_action", "question_for_parent", "next_agreed_step"]:
                    st.write(f"**{key.replace('_', ' ').title()}:** {brief[key]}")

                with st.form(f"call_outcome_{row['student_id']}"):
                    reached = st.radio("Outcome", ["Reached", "No answer"], horizontal=True,
                                        key=f"reached_{row['student_id']}")
                    parent_response = st.text_input("Parent response (if reached)", key=f"resp_{row['student_id']}")
                    agreed_action = st.text_input("Agreed action", key=f"agreed_{row['student_id']}")
                    follow_up = st.date_input("Follow-up date", value=SETTINGS.as_of_date + timedelta(days=2),
                                               key=f"fu_{row['student_id']}")
                    submit = st.form_submit_button("💾 Record call outcome")
                if submit:
                    status = "follow_up_required" if reached == "Reached" else "no_answer"
                    outcome = f"reached={reached=='Reached'}; response={parent_response}; agreed={agreed_action}; follow_up={follow_up}"
                    set_intervention_status(row["student_id"], user["email"], "PARENT_CALL", row["risk_level"],
                                             row["due_date"], status, outcome)
                    refresh_and_rerun()


# --- Calendar / booking page ---------------------------------------------------

def render_calendar(user: dict) -> None:
    computed = get_computed()
    risk_df = computed["risk_df"]
    mine = risk_df[risk_df["facilitator_email"] == user["email"]] if user["role"] != "admin" else risk_df

    st.title("📅 Calendar & 1-on-1 Booking")
    st.subheader("➕ Create availability")
    priority_students = mine.sort_values("priority_score", ascending=False)
    with st.form("create_slots"):
        student_label = st.selectbox("Student", priority_students["student_id"] + " — " + priority_students["student_name"])
        topic = st.text_input("Topic", value="Quiz 2 prep session")
        n_slots = st.number_input("Number of time options to offer", 1, 5, 2)
        slot_inputs = []
        for i in range(int(n_slots)):
            c1, c2 = st.columns(2)
            d = c1.date_input(f"Date #{i+1}", value=SETTINGS.as_of_date + timedelta(days=1), key=f"slot_date_{i}")
            t = c2.time_input(f"Start time #{i+1}", value=time(16, 0), key=f"slot_time_{i}")
            slot_inputs.append((d, t))
        submitted = st.form_submit_button("📅 Create availability & generate booking link")
    if submitted:
        sid = student_label.split(" — ")[0]
        batch_token = secrets.token_urlsafe(8)
        with session_scope() as session:
            for d, t in slot_inputs:
                start = datetime.combine(d, t)
                session.add(AvailabilitySlot(
                    facilitator_email=user["email"], topic=topic, start_time=start,
                    end_time=start + timedelta(minutes=45), booking_token=batch_token, student_id=sid, status="open",
                ))
        link = f"http://localhost:{SETTINGS.app_port}/?book={batch_token}"
        st.success("Availability created.")
        st.code(link)

    st.subheader("📋 My slots")
    with session_scope() as session:
        slots = session.scalars(
            select(AvailabilitySlot).where(AvailabilitySlot.facilitator_email == user["email"])
            .order_by(AvailabilitySlot.start_time)
        ).all()
        slot_rows = [{"student_id": s.student_id, "topic": s.topic, "start": s.start_time, "status": s.status,
                      "link": f"http://localhost:{SETTINGS.app_port}/?book={s.booking_token}"} for s in slots]
    if slot_rows:
        slots_df = pd.DataFrame(slot_rows)
        st.dataframe(slots_df, use_container_width=True, column_config=with_column_help(slots_df))
    else:
        st.write("No availability created yet.")


def render_public_booking(token: str) -> None:
    st.title("📅 Book your 1-on-1 session")
    with session_scope() as session:
        slots = session.scalars(
            select(AvailabilitySlot).where(AvailabilitySlot.booking_token == token, AvailabilitySlot.status == "open")
        ).all()
        if not slots:
            st.warning("This link has no open time slots (already booked, or invalid).")
            return
        student = session.scalars(select(Student).where(Student.student_id == slots[0].student_id)).first()
        st.write(f"Session topic: **{slots[0].topic}** for **{student.student_name if student else slots[0].student_id}**")
        # Indexed (not keyed by label text) so two slots that happen to
        # render the same label never collide into a single radio option.
        labels = [s.start_time.strftime("%a %Y-%m-%d %H:%M") for s in slots]
        choice_idx = st.radio("Choose a time", range(len(slots)), format_func=lambda i: labels[i])
        if st.button("✅ Confirm booking", type="primary"):
            chosen_id = slots[choice_idx].id
            for s in slots:
                if s.id == chosen_id:
                    s.status = "booked"
                else:
                    s.status = "cancelled"
            session.add(Intervention(
                student_id=slots[0].student_id, facilitator_email=slots[0].facilitator_email,
                action_type="ONE_TO_ONE_TUTORING", priority="Medium", due_date=slots[0].start_time.date(),
                status="booked",
            ))
            st.success("Booking confirmed! Your facilitator will see this on their calendar.")


# --- Data Entry page -----------------------------------------------------------

def render_data_entry(user: dict) -> None:
    flash = st.session_state.pop("data_entry_message", None)
    if flash:
        st.success(flash)

    computed = get_computed()
    risk_df = computed["risk_df"]
    mine = risk_df[risk_df["facilitator_email"] == user["email"]]

    st.title("📝 Data Entry")
    st.subheader("✍️ Manual daily metric entry")
    with st.form("manual_metric"):
        student_label = st.selectbox("Student", mine["student_id"] + " — " + mine["student_name"])
        d = st.date_input("Date", value=SETTINGS.as_of_date)
        attendance = st.number_input("Attendance minutes (leave 0 and check box if unknown)", 0, 90, 60)
        unknown_attendance = st.checkbox("Attendance unknown / not recorded")
        practice = st.number_input("Practice questions", 0, 500, 10)
        submitted = st.form_submit_button("💾 Save metric")
    if submitted:
        sid = student_label.split(" — ")[0]
        with session_scope() as session:
            existing = session.scalars(
                select(DailyMetric).where(DailyMetric.student_id == sid, DailyMetric.date == d)
            ).first()
            if existing is None:
                existing = DailyMetric(student_id=sid, date=d)
                session.add(existing)
            existing.attendance_min = None if unknown_attendance else float(attendance)
            existing.practice_questions = float(practice)
        refresh_and_rerun()

    st.subheader("📤 CSV upload")
    st.caption("Columns expected: student_id, date, attendance_min (or session_attended_min), practice_questions")
    uploaded = st.file_uploader("Upload CSV", type="csv")
    if uploaded is not None:
        raw = pd.read_csv(uploaded, dtype={"student_id": str})
        raw = raw.rename(columns={"session_attended_min": "attendance_min"})
        valid_ids = set(mine["student_id"])
        errors = []
        valid_rows = []
        for i, r in raw.iterrows():
            row_errors = []
            if r.get("student_id") not in valid_ids:
                row_errors.append("student_id not in your student list")
            try:
                parsed_date = pd.to_datetime(r.get("date")).date()
            except Exception:
                row_errors.append("unparseable date")
                parsed_date = None
            attendance_val = r.get("attendance_min")
            if pd.notna(attendance_val) and not (0 <= float(attendance_val) <= 90):
                row_errors.append("attendance out of 0-90 range")
            practice_val = r.get("practice_questions")
            if pd.notna(practice_val) and float(practice_val) < 0:
                row_errors.append("negative practice")
            if row_errors:
                errors.append({**r.to_dict(), "errors": "; ".join(row_errors)})
            else:
                valid_rows.append({"student_id": r["student_id"], "date": parsed_date,
                                    "attendance_min": attendance_val, "practice_questions": practice_val})

        st.write(f"**{len(valid_rows)} valid rows**, **{len(errors)} invalid rows**")
        if valid_rows:
            valid_df = pd.DataFrame(valid_rows)
            st.dataframe(valid_df, column_config=with_column_help(valid_df))
        if errors:
            errors_df = pd.DataFrame(errors)
            st.dataframe(errors_df, column_config=with_column_help(errors_df))
        if valid_rows and st.button("📥 Import valid rows"):
            with session_scope() as session:
                for r in valid_rows:
                    existing = session.scalars(
                        select(DailyMetric).where(DailyMetric.student_id == r["student_id"], DailyMetric.date == r["date"])
                    ).first()
                    if existing is None:
                        existing = DailyMetric(student_id=r["student_id"], date=r["date"])
                        session.add(existing)
                    existing.attendance_min = None if pd.isna(r["attendance_min"]) else float(r["attendance_min"])
                    existing.practice_questions = None if pd.isna(r["practice_questions"]) else float(r["practice_questions"])
            st.session_state["data_entry_message"] = f"Imported {len(valid_rows)} rows."
            refresh_and_rerun()

    st.divider()
    st.subheader("📝 Bulk facilitator notes upload")
    st.caption("Columns expected: student_id, date, note_text — matches facilitator_notes.csv. "
               "Imported notes are always trusted (they're recorded under your own account for your "
               "own students) and are analyzed immediately, same as adding one note by hand.")
    notes_uploaded = st.file_uploader("Upload notes CSV", type="csv", key="notes_csv_uploader")
    if notes_uploaded is not None:
        raw_notes = pd.read_csv(notes_uploaded, dtype={"student_id": str})
        valid_ids = set(mine["student_id"])
        note_errors, valid_note_rows = [], []
        for _, r in raw_notes.iterrows():
            row_errors = []
            sid = r.get("student_id")
            if sid not in valid_ids:
                row_errors.append("student_id not in your student list")
            try:
                parsed_date = pd.to_datetime(r.get("date")).date()
            except Exception:
                row_errors.append("unparseable date")
                parsed_date = None
            text = str(r.get("note_text", "")).strip()
            if not text or text.lower() == "nan":
                row_errors.append("empty note text")
            if row_errors:
                note_errors.append({**r.to_dict(), "errors": "; ".join(row_errors)})
            else:
                valid_note_rows.append({"student_id": sid, "date": parsed_date, "note_text": text})

        st.write(f"**{len(valid_note_rows)} valid rows**, **{len(note_errors)} invalid rows**")
        if valid_note_rows:
            valid_notes_df = pd.DataFrame(valid_note_rows)
            st.dataframe(valid_notes_df, column_config=with_column_help(valid_notes_df))
        if note_errors:
            note_errors_df = pd.DataFrame(note_errors)
            st.dataframe(note_errors_df, column_config=with_column_help(note_errors_df))
        if valid_note_rows and st.button("📥 Import valid notes"):
            with session_scope() as session:
                for r in valid_note_rows:
                    session.add(FacilitatorNote(
                        note_id=f"UI-{secrets.token_hex(4)}", student_id=r["student_id"],
                        facilitator_email=user["email"], date=r["date"], note_text=r["note_text"],
                        trust_status="trusted",
                    ))
            st.session_state["data_entry_message"] = (
                f"Imported {len(valid_note_rows)} notes — analyzing them and recomputing risk now.")
            refresh_and_rerun()


# --- Admin page ------------------------------------------------------------------

def render_admin(user: dict) -> None:
    computed = get_computed()
    risk_df = computed["risk_df"]
    interventions_df = computed["interventions_df"]

    eyebrow(f"SYSTEM-WIDE · {len(risk_df)} STUDENTS")
    st.title("🛠️ Admin")
    tabs = st.tabs(["📊 Overview", "🏫 Campuses", "🧑‍🏫 Facilitators", "🧑‍🎓 Students", "🧪 Data Quality"])

    with tabs[0]:
        coverage = outputs_mod.coverage_metrics(risk_df, interventions_df, SETTINGS.as_of_date, TARGET_COVERAGE)
        c1, c2, c3, c4 = st.columns(4)
        kpi(c1, len(risk_df), "Students", "👥", "Total active students system-wide.")
        kpi(c2, risk_df["campus_id"].nunique(), "Campuses", "🏫", "Number of distinct campuses.")
        kpi(c3, risk_df["facilitator_email"].nunique(), "Facilitators", "🧑‍🏫", "Number of active facilitator accounts.")
        kpi(c4, fmt_pct(coverage['successful_interaction_rate']), "Successful Interaction Rate", "✅",
            "Share of students-who-need-help with a real completed/sent/booked interaction, system-wide.")
        st.progress(min(1.0, coverage["successful_interaction_rate"] / 100), text="Progress toward 80% target")
        risk_order = ["Critical", "High", "Medium", "Low"]
        counts_by_level = risk_df["risk_level"].value_counts()
        levels_present = [lvl for lvl in risk_order if lvl in counts_by_level.index]
        fig = go.Figure(go.Bar(x=levels_present, y=[counts_by_level[lvl] for lvl in levels_present],
                                marker_color=[RISK_COLORS[lvl] for lvl in levels_present]))
        st.plotly_chart(chart_chrome(fig, "📊 Risk distribution", height=320), use_container_width=True)

    with tabs[1]:
        with session_scope() as session:
            campuses = session.scalars(select(Campus)).all()
            campuses_df = pd.DataFrame([{"campus_id": c.campus_id, "name": c.name} for c in campuses])
            st.dataframe(campuses_df, column_config=with_column_help(campuses_df))
        with st.form("add_campus"):
            cid = st.text_input("Campus ID")
            name = st.text_input("Name")
            if st.form_submit_button("💾 Add / update campus") and cid:
                with session_scope() as session:
                    existing = session.scalars(select(Campus).where(Campus.campus_id == cid)).first()
                    if existing is None:
                        session.add(Campus(campus_id=cid, name=name or cid))
                    else:
                        existing.name = name or existing.name
                st.rerun()
        del_cid = st.text_input("Campus ID to delete")
        if st.button("🗑️ Delete campus") and del_cid:
            with session_scope() as session:
                session.query(Campus).filter(Campus.campus_id == del_cid).delete()
            st.rerun()

    with tabs[2]:
        workload = risk_df.groupby("facilitator_email").agg(
            students=("student_id", "count"), critical=("risk_level", lambda s: (s == "Critical").sum()),
            high=("risk_level", lambda s: (s == "High").sum()),
        ).reset_index()
        st.dataframe(workload, use_container_width=True, column_config=with_column_help(workload))
        with st.form("add_facilitator"):
            email = st.text_input("Facilitator email")
            name = st.text_input("Display name")
            password = st.text_input("Temporary password", type="password")
            if st.form_submit_button("➕ Add facilitator account") and email and password:
                with session_scope() as session:
                    if get_user_by_email(session, email) is None:
                        session.add(User(email=email.strip().lower(), password_hash=hash_password(password),
                                          display_name=name or email, role="facilitator", active=True))
                        st.success("Facilitator account created.")
                    else:
                        st.warning("A user with that email already exists.")

    with tabs[3]:
        students_df = risk_df[["student_id", "student_name", "campus_id", "facilitator_email", "grade",
                                "learning_track", "risk_level"]]
        st.dataframe(students_df, use_container_width=True, height=350, column_config=with_column_help(students_df))
        with st.form("add_student"):
            c1, c2 = st.columns(2)
            student_id = c1.text_input("Student ID")
            student_name = c2.text_input("Student name")
            campus_id = c1.text_input("Campus ID")
            facilitator_email = c2.text_input("Facilitator email")
            grade = c1.number_input("Grade", 1, 12, 10)
            track = c2.selectbox("Learning track", ["Standard", "Accelerated", "Remedial"])
            target = c1.number_input("Target score", 0, 100, 80)
            phone = c2.text_input("Parent phone")
            if st.form_submit_button("💾 Add / update student") and student_id:
                with session_scope() as session:
                    existing = session.scalars(select(Student).where(Student.student_id == student_id)).first()
                    if existing is None:
                        existing = Student(student_id=student_id)
                        session.add(existing)
                    existing.student_name = student_name
                    existing.campus_id = campus_id
                    existing.facilitator_email = facilitator_email
                    existing.grade = int(grade)
                    existing.learning_track = track
                    existing.target_score = float(target)
                    existing.parent_phone = phone
                    existing.active = True
                refresh_and_rerun()

        st.divider()
        st.subheader("📤 Bulk student roster upload")
        st.caption("Columns expected: student_id, student_name, campus_id, facilitator_email, grade, "
                   "learning_track, target_score, parent_phone — matches student_metadata.csv. "
                   "Existing student_ids are updated in place; new ones are created.")
        roster_uploaded = st.file_uploader("Upload roster CSV", type="csv", key="roster_csv_uploader")
        if roster_uploaded is not None:
            raw_roster = pd.read_csv(roster_uploaded, dtype={"student_id": str, "campus_id": str})
            required_cols = ["student_id", "student_name", "campus_id", "facilitator_email", "grade",
                              "learning_track", "target_score", "parent_phone"]
            roster_errors, valid_roster_rows = [], []
            for _, r in raw_roster.iterrows():
                row_errors = []
                sid = r.get("student_id")
                if pd.isna(sid) or not str(sid).strip():
                    row_errors.append("missing student_id")
                for col in required_cols:
                    if col not in raw_roster.columns:
                        row_errors.append(f"missing column: {col}")
                        break
                grade_val = r.get("grade")
                if pd.notna(grade_val) and not (1 <= float(grade_val) <= 12):
                    row_errors.append("grade out of 1-12 range")
                target_val = r.get("target_score")
                if pd.notna(target_val) and not (0 <= float(target_val) <= 100):
                    row_errors.append("target_score out of 0-100 range")
                if row_errors:
                    roster_errors.append({**r.to_dict(), "errors": "; ".join(row_errors)})
                else:
                    valid_roster_rows.append({
                        "student_id": str(sid).strip(), "student_name": r["student_name"],
                        "campus_id": r["campus_id"], "facilitator_email": r["facilitator_email"],
                        "grade": int(grade_val), "learning_track": r["learning_track"],
                        "target_score": float(target_val), "parent_phone": r["parent_phone"],
                    })

            st.write(f"**{len(valid_roster_rows)} valid rows**, **{len(roster_errors)} invalid rows**")
            if valid_roster_rows:
                valid_roster_df = pd.DataFrame(valid_roster_rows)
                st.dataframe(valid_roster_df, column_config=with_column_help(valid_roster_df))
            if roster_errors:
                roster_errors_df = pd.DataFrame(roster_errors)
                st.dataframe(roster_errors_df, column_config=with_column_help(roster_errors_df))
            if valid_roster_rows and st.button("📥 Import valid roster rows"):
                with session_scope() as session:
                    for r in valid_roster_rows:
                        existing = session.scalars(
                            select(Student).where(Student.student_id == r["student_id"])
                        ).first()
                        if existing is None:
                            existing = Student(student_id=r["student_id"])
                            session.add(existing)
                        existing.student_name = r["student_name"]
                        existing.campus_id = r["campus_id"]
                        existing.facilitator_email = r["facilitator_email"]
                        existing.grade = r["grade"]
                        existing.learning_track = r["learning_track"]
                        existing.target_score = r["target_score"]
                        existing.parent_phone = r["parent_phone"]
                        existing.active = True
                st.session_state["data_entry_message"] = f"Imported/updated {len(valid_roster_rows)} students."
                refresh_and_rerun()

    with tabs[4]:
        import json
        report = json.loads((SETTINGS.output_dir / "data_quality_report.json").read_text())
        st.metric("Total flagged rows", report["total_flagged_rows"],
                  help="Sum of every row any data-quality check flagged — a row can be counted by more than one check.")
        checks_df = pd.DataFrame(report["checks"])
        st.dataframe(checks_df, use_container_width=True, column_config=with_column_help(checks_df))


# --- First-login onboarding ---------------------------------------------------

FACILITATOR_TOUR = [
    ("🏠", "My Day", "Your home page — today's highest-priority students, KPIs, and one-click actions."),
    ("👥", "My Students", "Your full roster, filterable by campus, risk level, track, or recommended action."),
    ("🔍", "Student Detail", "A deep dive per student: patterns, trends, peer comparison, notes, and parent report."),
    ("🎯", "Actions", "Everything due today, overdue, in progress, or completed — organized by status."),
    ("📞", "Parent Calls", "Today's parent-call queue, with an AI-drafted talking-points brief for each call."),
    ("📅", "Calendar", "Create 1-on-1 booking slots for a student and share the link — no login needed to book."),
    ("📝", "Data Entry", "Log a metric by hand, or bulk-import a CSV of attendance/practice data."),
]
ADMIN_TOUR = [
    ("📊", "Overview", "System-wide KPIs, risk distribution, and progress toward the 80% coverage target."),
    ("🏫", "Campuses", "View every campus, and add or remove one."),
    ("🧑‍🏫", "Facilitators", "See each facilitator's workload and create new facilitator accounts."),
    ("🧑‍🎓", "Students", "Browse every student and add or edit a record."),
    ("🧪", "Data Quality", "Every issue the pipeline found in the source CSVs — nothing is hidden."),
]


@st.dialog("👋 Welcome to Boon Academy", width="large")
def render_onboarding_dialog(user: dict) -> None:
    st.write(f"Hi **{user['display_name']}** — here's a quick tour of what each section does.")
    tour = ADMIN_TOUR if user["role"] == "admin" else FACILITATOR_TOUR
    for icon, name, description in tour:
        st.markdown(f"**{icon} {name}** — {description}")
    st.divider()
    st.caption("You can reopen this tour anytime from the **❓ Help** button in the sidebar.")
    if st.button("Got it — let's go 🚀", type="primary", use_container_width=True):
        mark_onboarding_seen(user["email"])
        st.session_state.user["has_seen_onboarding"] = True
        st.rerun()


# --- Router ------------------------------------------------------------------

def main() -> None:
    query_params = st.query_params
    if "book" in query_params:
        init_db()
        render_public_booking(query_params["book"])
        return

    if "user" not in st.session_state:
        st.session_state.user = None
    if st.session_state.user is None:
        render_login()
        return

    user = st.session_state.user
    role_icon = "🛠️" if user["role"] == "admin" else "🧑‍🏫"
    st.sidebar.title("📚 Boon Academy")
    st.sidebar.caption(f"{role_icon} {user['display_name']} · {user['role'].title()}")

    if not user.get("has_seen_onboarding"):
        render_onboarding_dialog(user)

    if user["role"] == "admin":
        pages = ["Admin", "My Students", "Student Detail", "Actions", "Calendar"]
    else:
        pages = ["My Day", "My Students", "Student Detail", "Actions", "Parent Calls", "Calendar", "Data Entry"]

    # A button elsewhere in the app can request a page switch (e.g. "Open
    # Detail"), but Streamlit forbids writing to a widget-bound session_state
    # key after that widget has been instantiated. So a request is staged in
    # nav_request and only merged into the actual "nav" key here, before the
    # radio widget below is created. Once "nav" is set this way, the widget
    # must be created with no `index=` — Streamlit forbids setting a default
    # through both the index parameter and Session State at once.
    if "nav_request" in st.session_state:
        st.session_state.nav = st.session_state.pop("nav_request")
    elif st.session_state.get("nav") not in pages:
        st.session_state.nav = pages[0]

    choice = st.sidebar.radio("Navigate", pages, key="nav",
                               format_func=lambda p: f"{NAV_ICONS.get(p, '')} {p}")

    st.sidebar.divider()
    if st.sidebar.button("❓ Help / tutorial", use_container_width=True):
        render_onboarding_dialog(user)
    if st.sidebar.button("🚪 Log out", use_container_width=True):
        st.session_state.user = None
        st.rerun()

    if choice == "My Day":
        render_my_day(user)
    elif choice == "My Students":
        render_my_students(user)
    elif choice == "Student Detail":
        render_student_detail(user)
    elif choice == "Actions":
        render_actions(user)
    elif choice == "Parent Calls":
        render_parent_calls(user)
    elif choice == "Calendar":
        render_calendar(user)
    elif choice == "Data Entry":
        render_data_entry(user)
    elif choice == "Admin":
        render_admin(user)


main()
