"""Turn cleaned daily rows into one feature row per student.

Day numbering: we don't assume the source CSV starts on any particular
calendar date. Instead `day_number = (date - earliest_date).days + 1`, so
"Day 14" always means "the 14th calendar day of the program" regardless of
which real-world dates the data happens to use. `Settings.current_day` /
`quiz1_day` / `quiz2_day` (default 14 / 10 / 20 per the case brief) are then
converted to real dates once and used for all window logic below.
"""

from __future__ import annotations

import pandas as pd

from src.config import Settings
from src.validate import QualityReport


def _day_to_date(min_date: pd.Timestamp, day_number: int) -> pd.Timestamp:
    return min_date + pd.Timedelta(days=day_number - 1)


def _recent_window_dates(metrics: pd.DataFrame, quiz1_date: pd.Timestamp) -> list[pd.Timestamp]:
    """The "recent" window is the two latest session dates after Quiz 1
    (Days 13-14 in the reference dataset). Computed once across the whole
    cohort — a single shared window keeps every student's recent-engagement
    score comparable, rather than drifting per-student if a few rows are
    missing."""
    post_quiz_dates = sorted(d for d in metrics["date"].unique() if d > quiz1_date)
    if len(post_quiz_dates) >= 2:
        return post_quiz_dates[-2:]
    # Not enough post-quiz history yet (e.g. Quiz 1 just happened) — fall
    # back to the two most recent dates available at all.
    return sorted(metrics["date"].unique())[-2:]


def build_features(
    metrics: pd.DataFrame,
    notes: pd.DataFrame,
    meta: pd.DataFrame,
    settings: Settings,
    report: QualityReport,
) -> pd.DataFrame:
    """Return one row per student in `meta`, joined with engagement,
    quiz, and note-derived signals. Every student in metadata gets a row
    even if they have zero metrics/notes rows (they simply score as fully
    disengaged, which is the correct, conservative reading)."""

    min_date = metrics["date"].min()
    quiz1_date = _day_to_date(min_date, settings.quiz1_day)
    current_date = _day_to_date(min_date, settings.current_day)

    metrics = metrics[metrics["date"] <= current_date]
    recent_dates = _recent_window_dates(metrics, quiz1_date)

    # --- engagement totals -------------------------------------------------
    totals = (
        metrics.groupby("student_id")
        .agg(
            total_attendance_min=("session_attended_min", "sum"),
            total_practice_questions=("practice_questions", "sum"),
        )
        .reset_index()
    )

    recent = metrics[metrics["date"].isin(recent_dates)]
    recent_totals = (
        recent.groupby("student_id")
        .agg(
            recent_attendance_min=("session_attended_min", "sum"),
            recent_practice_questions=("practice_questions", "sum"),
        )
        .reset_index()
    )

    # --- quiz 1 score: latest non-null value on/before current_date -------
    # (Handles both a single-day quiz row and a forward-filled column.)
    quiz_rows = metrics[metrics["quiz_score"].notna()].sort_values("date")
    quiz_latest = quiz_rows.groupby("student_id").last()[["quiz_score"]]
    quiz_latest = quiz_latest.rename(columns={"quiz_score": "quiz1_score"}).reset_index()

    # --- post-quiz facilitator notes ---------------------------------------
    notes = notes.copy()
    notes["date"] = pd.to_datetime(notes["date"])
    notes_sorted = notes.sort_values("date")
    post_quiz_notes = notes_sorted[notes_sorted["date"] > quiz1_date]

    post_quiz_counts = (
        post_quiz_notes.groupby("student_id").size().rename("post_quiz_note_count")
    )
    last_note = notes_sorted.groupby("student_id").last()[["date", "note_text"]].rename(
        columns={"date": "last_note_date", "note_text": "last_note_text"}
    )

    # --- assemble ------------------------------------------------------------
    df = meta.copy()
    df = df.merge(totals, on="student_id", how="left")
    df = df.merge(recent_totals, on="student_id", how="left")
    df = df.merge(quiz_latest, on="student_id", how="left")
    df = df.merge(post_quiz_counts, on="student_id", how="left")
    df = df.merge(last_note, on="student_id", how="left")

    for col in [
        "total_attendance_min",
        "total_practice_questions",
        "recent_attendance_min",
        "recent_practice_questions",
        "post_quiz_note_count",
    ]:
        df[col] = df[col].fillna(0)

    df["has_post_quiz_intervention"] = df["post_quiz_note_count"] > 0
    df["days_since_last_note"] = (current_date - df["last_note_date"]).dt.days

    # --- missing quiz score: flagged and scored as risk, not dropped -------
    df["missing_quiz_score"] = df["quiz1_score"].isna()
    if df["missing_quiz_score"].any():
        report.add(
            check="students_missing_quiz1_score",
            severity="warning",
            count=int(df["missing_quiz_score"].sum()),
            detail="Students with no recorded Quiz 1 score are operationally invisible; flagged and risk-boosted rather than excluded",
        )

    missing_target = df["target_score"].isna()
    if missing_target.any():
        report.add(
            check="students_missing_target_score",
            severity="warning",
            count=int(missing_target.sum()),
            detail="Students with no target_score cannot have a gap-to-target computed; flagged in missing_data_points",
        )
    df["missing_target_score"] = missing_target

    df["gap_to_target"] = df["target_score"] - df["quiz1_score"]
    df["below_target"] = (df["quiz1_score"] < df["target_score"]).fillna(False)

    df["attendance_rate_recent"] = df["recent_attendance_min"] / 180.0
    # Normalized against the cohort median so a "typical" student reads ~1.0;
    # this is a display/context metric only — risk.py scores recent practice
    # off cohort percentiles directly, not off this ratio.
    cohort_median_practice = df["recent_practice_questions"].median()
    df["practice_rate_recent"] = df["recent_practice_questions"] / max(cohort_median_practice, 1)

    df["current_day"] = settings.current_day
    df["quiz1_day"] = settings.quiz1_day
    df["quiz2_day"] = settings.quiz2_day

    return df
