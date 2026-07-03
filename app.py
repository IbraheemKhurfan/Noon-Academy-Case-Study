"""Streamlit demo app for facilitators and reviewers.

Reads only from `OUTPUT_DIR` — it never touches `DATA_DIR` or re-runs the
pipeline itself. That separation mirrors how this would work in production:
`main.py` (or a cron job) recomputes the roster; the app is a thin, fast
viewer over whatever the last run produced.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.config import settings

st.set_page_config(
    page_title="Boon Academy Intervention Command Center",
    page_icon="🎯",
    layout="wide",
)

# Status palette: fixed, validated, and never reused for anything else on
# the page — a risk level is always shown as color *and* text label, never
# color alone (Critical/High/Medium/Low badges everywhere below).
RISK_COLORS = {
    "Critical": "#d03b3b",
    "High": "#ec835a",
    "Medium": "#fab219",
    "Low": "#0ca30c",
}
RISK_ORDER = ["Critical", "High", "Medium", "Low"]

st.markdown(
    """
    <style>
      .kpi-card {
        background: var(--background-color, #fff);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 12px;
        padding: 0.9rem 1.1rem;
        margin-bottom: 0.4rem;
      }
      .kpi-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.65; }
      .kpi-value { font-size: 1.6rem; font-weight: 700; }
      .risk-badge {
        display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        font-size: 0.8rem; font-weight: 600; color: white;
      }
      .section-card {
        border: 1px solid rgba(128,128,128,0.25); border-radius: 12px;
        padding: 1.1rem 1.3rem; margin-bottom: 1rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_outputs(output_dir: str):
    """Load the worklist CSV rather than the roster CSV: it's a superset of
    every roster column plus `estimated_minutes` / `priority_rank_for_facilitator`
    / `must_do_today`, computed once in src/outputs.py — so the app never
    recomputes workload numbers with logic that could drift from the CSVs
    a facilitator actually opens."""
    base = pd.io.common.stringify_path(output_dir)
    df = pd.read_csv(f"{base}/facilitator_worklists.csv")
    df["reason_codes"] = df["reason_codes"].fillna("").apply(
        lambda s: [c for c in s.split(";") if c]
    )
    quality = {}
    try:
        with open(f"{base}/data_quality_report.json", encoding="utf-8") as f:
            quality = json.load(f)
    except FileNotFoundError:
        pass
    return df, quality


def kpi_card(label: str, value: str) -> str:
    return f"""<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>"""


def risk_badge(level: str) -> str:
    color = RISK_COLORS.get(level, "#888")
    return f'<span class="risk-badge" style="background:{color}">{level}</span>'


# --- load data, or ask the user to run the pipeline first -----------------
roster_file = settings.output_dir / "student_risk_roster.csv"
worklist_file = settings.output_dir / "facilitator_worklists.csv"
if not (roster_file.exists() and worklist_file.exists()):
    st.title("🎯 Boon Academy Intervention Command Center")
    st.warning(
        "No pipeline outputs found yet.\n\n"
        f"Expected `{roster_file}`. Run **`make demo`** (or `python main.py`) "
        "first, then reload this page."
    )
    st.stop()

df, quality_report = load_outputs(str(settings.output_dir))

days_to_quiz2 = settings.quiz2_day - settings.current_day

# --- sidebar filters --------------------------------------------------------
st.sidebar.header("Filters")
campus_options = sorted(df["campus_id"].dropna().unique())
facilitator_options = sorted(df["facilitator_email"].dropna().unique())
track_options = sorted(df["learning_track"].dropna().unique())

selected_campuses = st.sidebar.multiselect("Campus", campus_options, default=campus_options)
selected_facilitators = st.sidebar.multiselect(
    "Facilitator", facilitator_options, default=facilitator_options
)
selected_risk = st.sidebar.multiselect("Risk level", RISK_ORDER, default=RISK_ORDER)
selected_tracks = st.sidebar.multiselect("Learning track", track_options, default=track_options)

filtered = df[
    df["campus_id"].isin(selected_campuses)
    & df["facilitator_email"].isin(selected_facilitators)
    & df["risk_level"].isin(selected_risk)
    & df["learning_track"].isin(selected_tracks)
].copy()

# --- header ------------------------------------------------------------------
st.title("🎯 Boon Academy Intervention Command Center")
st.caption(
    f"Day {settings.current_day} of the program · Quiz 1 was Day {settings.quiz1_day} · "
    f"Quiz 2 is Day {settings.quiz2_day} — **{days_to_quiz2} days away**"
)

# --- KPI row -------------------------------------------------------------
below_target = df[df["below_target"]]
below_target_count = len(below_target)
baseline_rate = (
    below_target["has_post_quiz_intervention"].mean() if below_target_count else 0.0
)
human_touch_actions = {
    "parent_call_plus_tutoring",
    "parent_call_or_voice_note",
    "student_checkin_plus_practice_plan",
}
human_touch_rate = (
    below_target["recommended_action"].isin(human_touch_actions).mean()
    if below_target_count
    else 0.0
)
risk_counts = df["risk_level"].value_counts().reindex(RISK_ORDER, fill_value=0)

kpi_cols = st.columns(6)
kpi_values = [
    ("Total students", f"{len(df)}"),
    ("Below target", f"{below_target_count}"),
    ("Baseline intervention rate", f"{baseline_rate:.0%}"),
    ("System coverage (human + auto)", "100%"),
    ("Human-touch coverage", f"{human_touch_rate:.0%}"),
    ("Critical + High students", f"{risk_counts['Critical'] + risk_counts['High']}"),
]
for col, (label, value) in zip(kpi_cols, kpi_values):
    col.markdown(kpi_card(label, value), unsafe_allow_html=True)

st.divider()

# --- risk distribution + facilitator workload -----------------------------
left, right = st.columns([1, 1.3])

with left:
    st.subheader("Risk distribution")
    dist_df = risk_counts.rename_axis("risk_level").reset_index(name="students")
    fig = px.bar(
        dist_df,
        x="students",
        y="risk_level",
        orientation="h",
        category_orders={"risk_level": RISK_ORDER},
        color="risk_level",
        color_discrete_map=RISK_COLORS,
        text="students",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        showlegend=False,
        yaxis_title=None,
        xaxis_title="Students",
        margin=dict(l=10, r=10, t=10, b=10),
        height=300,
    )
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Facilitator workload (Critical + High)")
    workload = (
        df[df["risk_level"].isin(["Critical", "High"])]
        .groupby("facilitator_email")
        .agg(students=("student_id", "count"), minutes=("estimated_minutes", "sum"))
        .reset_index()
        .sort_values("minutes", ascending=True)
    )
    if workload.empty:
        st.info("No Critical/High students in the current filter.")
    else:
        fig2 = go.Figure(
            go.Bar(
                x=workload["minutes"],
                y=workload["facilitator_email"],
                orientation="h",
                marker_color="#2a78d6",
                text=workload["students"].astype(str) + " students",
                textposition="outside",
            )
        )
        fig2.update_layout(
            xaxis_title="Estimated minutes today",
            yaxis_title=None,
            margin=dict(l=10, r=10, t=10, b=10),
            height=300,
        )
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# --- main student table -----------------------------------------------------
st.subheader(f"Student roster ({len(filtered)} students)")

table_df = filtered.sort_values("risk_score", ascending=False)[
    [
        "student_name",
        "campus_id",
        "facilitator_email",
        "risk_level",
        "risk_score",
        "quiz1_score",
        "target_score",
        "recent_attendance_min",
        "recent_practice_questions",
        "recommended_action",
        "sla",
    ]
].reset_index(drop=True)


def _style_risk(row: pd.Series) -> list[str]:
    color = RISK_COLORS.get(row["risk_level"], "#888")
    return [f"background-color: {color}22" if col == "risk_level" else "" for col in row.index]


st.dataframe(
    table_df.style.apply(_style_risk, axis=1),
    use_container_width=True,
    height=380,
)

st.divider()

# --- student detail panel ---------------------------------------------------
st.subheader("Student detail")
if filtered.empty:
    st.info("No students match the current filters.")
else:
    name_to_id = dict(zip(filtered["student_name"] + " (" + filtered["student_id"] + ")", filtered["student_id"]))
    picked_label = st.selectbox("Choose a student", list(name_to_id.keys()))
    picked_id = name_to_id[picked_label]
    student = filtered[filtered["student_id"] == picked_id].iloc[0]

    detail_left, detail_right = st.columns([1, 1.4])

    with detail_left:
        st.markdown(risk_badge(student["risk_level"]) + f"  &nbsp; **Risk score:** {student['risk_score']}", unsafe_allow_html=True)
        st.markdown(f"**Facilitator:** {student['facilitator_email']}  \n**Campus:** {student['campus_id']}  \n**Track:** {student['learning_track']}")

        quiz_val = student["quiz1_score"]
        target_val = student["target_score"]
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(
            x=["Quiz 1 score", "Target score"],
            y=[0 if pd.isna(quiz_val) else quiz_val, target_val],
            marker_color=["#d03b3b" if student["below_target"] else "#0ca30c", "#2a78d6"],
            text=[("No score" if pd.isna(quiz_val) else f"{quiz_val:g}"), f"{target_val:g}"],
            textposition="outside",
        ))
        fig3.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=10), yaxis_title="Score")
        st.plotly_chart(fig3, use_container_width=True)

        st.metric("Recent attendance (last 2 sessions)", f"{student['recent_attendance_min']:.0f} / 180 min")
        st.metric("Recent practice questions", f"{student['recent_practice_questions']:.0f}")

    with detail_right:
        st.markdown("**Reason codes**")
        st.markdown(
            " ".join(f"`{code}`" for code in student["reason_codes"]) or "_none_",
        )

        st.markdown("**Notes summary**")
        st.info(
            student.get("facilitator_brief", "")
        )

        st.markdown(f"**Recommended action:** `{student['recommended_action']}`  ·  **SLA:** {student['sla']}  ·  **Effort:** {student['human_effort']}")

        with st.expander("Parent script", expanded=True):
            st.write(student["parent_script"])
        with st.expander("Student message"):
            st.write(student["student_message"])
        with st.expander("Next best step"):
            st.write(student["next_best_step"])

st.divider()

# --- narrative sections -------------------------------------------------
rescue_col, quiz2_col = st.columns(2)

with rescue_col:
    st.markdown(
        f"""
        <div class="section-card">
        <h3>📌 Day {settings.current_day} Rescue Plan</h3>
        <p>On Day {settings.current_day}, {below_target_count} of {len(df)} students are below
        their target score, but only <b>{baseline_rate:.0%}</b> of them have received any
        facilitator follow-up since Quiz 1. The plan for today:</p>
        <ol>
          <li><b>Critical ({risk_counts['Critical']} students):</b> facilitator calls the parent
          today and books a 1:1 tutoring slot before Quiz 2.</li>
          <li><b>High ({risk_counts['High']} students):</b> parent call or voice note within
          24 hours to find the specific barrier.</li>
          <li><b>Medium ({risk_counts['Medium']} students):</b> a short WhatsApp check-in plus a
          practice plan within 48 hours.</li>
          <li><b>Low ({risk_counts['Low']} students):</b> an automated motivational message goes
          out today — no facilitator time required, but the student still gets contacted.</li>
        </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )

with quiz2_col:
    st.markdown(
        f"""
        <div class="section-card">
        <h3>⏳ What happens before Quiz 2</h3>
        <p>Quiz 2 is on Day {settings.quiz2_day}, {days_to_quiz2} days from today. Between now
        and then:</p>
        <ul>
          <li>Facilitators work their prioritized worklist
          (<code>facilitator_worklists.csv</code>), Critical students first.</li>
          <li>Every logged outcome (a new facilitator note) feeds back into the next
          pipeline run, so risk scores and worklists update daily.</li>
          <li>Automated nudges keep Low-risk, below-target students engaged without
          consuming facilitator time, so human effort stays concentrated on the
          {risk_counts['Critical'] + risk_counts['High']} students who need it most.</li>
          <li>Re-run <code>make demo</code> each morning through Day {settings.quiz2_day} to
          refresh the roster with the latest attendance, practice, and notes.</li>
        </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

if quality_report.get("total_issues"):
    with st.expander(f"⚠️ Data quality report — {quality_report['total_issues']} issue(s) detected"):
        for issue in quality_report.get("issues", []):
            st.write(f"**{issue['check']}** ({issue['severity']}, {issue['count']}): {issue['detail']}")
