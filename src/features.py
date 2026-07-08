"""Per-student feature engineering. Pure functions over pandas data — no risk
scoring or LLM calls happen here, only measurement.

Baseline vs. recent is split at Quiz 1's date: "baseline" is behavior before
Quiz 1, "recent" is behavior after it. That split is what lets us measure
whether a student changed behavior *because of* the quiz, which is exactly
the signal a facilitator needs (a student who was always low-attendance is a
different problem than one who collapsed right after seeing their score).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

MIN_PEER_GROUP = 10


def _trailing_zero_streak(values: list[Optional[float]]) -> int:
    streak = 0
    for v in reversed(values):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            break
        if v == 0:
            streak += 1
        else:
            break
    return streak


def _safe_mean(values: pd.Series) -> Optional[float]:
    values = values.dropna()
    return float(values.mean()) if len(values) else None


def compute_student_features(
    student_row: pd.Series,
    student_metrics: pd.DataFrame,
    quiz1_date: date,
    as_of_date: date,
    quality_flags: list[str],
) -> dict:
    student_metrics = student_metrics.sort_values("date")
    baseline = student_metrics[student_metrics["date"] < quiz1_date]
    recent = student_metrics[student_metrics["date"] >= quiz1_date]

    baseline_attendance = _safe_mean(baseline["session_attended_min"])
    recent_attendance = _safe_mean(recent["session_attended_min"])
    avg_attendance = _safe_mean(student_metrics["session_attended_min"])

    baseline_practice = _safe_mean(baseline["practice_questions"])
    recent_practice = _safe_mean(recent["practice_questions"])
    avg_practice = _safe_mean(student_metrics["practice_questions"])

    quiz_rows = student_metrics[student_metrics["last_quiz_score"].notna()]
    quiz1_score = float(quiz_rows["last_quiz_score"].iloc[-1]) if len(quiz_rows) else None

    target_score = float(student_row["target_score"])
    gap_to_target = (target_score - quiz1_score) if quiz1_score is not None else None
    below_target = (gap_to_target > 0) if gap_to_target is not None else None

    attendance_series = student_metrics["session_attended_min"].tolist()
    practice_series = student_metrics["practice_questions"].tolist()

    max_single_day_practice = float(student_metrics["practice_questions"].max()) if len(student_metrics) else 0.0
    extreme_practice_burst = bool((student_metrics.get("practice_extreme", pd.Series(dtype=bool))).any())

    return {
        "student_id": student_row["student_id"],
        "student_name": student_row["student_name"],
        "campus_id": student_row["campus_id"],
        "facilitator_email": student_row["facilitator_email"],
        "grade": int(student_row["grade"]),
        "learning_track": student_row["learning_track"],
        "target_score": target_score,
        "quiz1_score": quiz1_score,
        "gap_to_target": gap_to_target,
        "below_target": below_target,
        "avg_attendance": avg_attendance,
        "baseline_attendance": baseline_attendance,
        "recent_attendance": recent_attendance,
        "attendance_trend": (recent_attendance - baseline_attendance)
        if (recent_attendance is not None and baseline_attendance is not None) else None,
        "zero_attendance_streak": _trailing_zero_streak(attendance_series),
        "avg_practice": avg_practice,
        "baseline_practice": baseline_practice,
        "recent_practice": recent_practice,
        "practice_trend": (recent_practice - baseline_practice)
        if (recent_practice is not None and baseline_practice is not None) else None,
        "zero_practice_streak": _trailing_zero_streak(practice_series),
        "max_single_day_practice": max_single_day_practice,
        "extreme_practice_burst": extreme_practice_burst,
        "days_until_quiz2": (student_row.get("_quiz2_date") - as_of_date).days
        if student_row.get("_quiz2_date") else None,
        "data_quality_flags": list(quality_flags),
        "n_metric_rows": len(student_metrics),
        "n_missing_attendance_days": int(student_metrics["session_attended_min"].isna().sum()),
    }


def build_features_table(
    meta: pd.DataFrame,
    metrics: pd.DataFrame,
    quiz1_date: date,
    quiz2_date: date,
    as_of_date: date,
    quality_flags: dict[str, list[str]],
) -> pd.DataFrame:
    rows = []
    metrics_by_student = {sid: g for sid, g in metrics.groupby("student_id")}
    for _, student_row in meta.iterrows():
        sid = student_row["student_id"]
        student_metrics = metrics_by_student.get(sid, metrics.iloc[0:0])
        row = student_row.copy()
        row["_quiz2_date"] = quiz2_date
        rows.append(compute_student_features(row, student_metrics, quiz1_date, as_of_date, quality_flags.get(sid, [])))
    df = pd.DataFrame(rows)
    df["days_until_quiz2"] = (quiz2_date - as_of_date).days
    return add_peer_percentiles(df)


def add_peer_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    """Percentile within grade+learning_track when that group is large enough
    to be statistically meaningful; otherwise fall back to the full cohort so
    a small track (e.g. Accelerated) doesn't get noisy percentiles."""
    df = df.copy()
    group_sizes = df.groupby(["grade", "learning_track"])["student_id"].transform("size")
    use_narrow = group_sizes >= MIN_PEER_GROUP

    for col, out_col in [
        ("quiz1_score", "quiz_percentile"),
        ("recent_attendance", "attendance_percentile"),
        ("recent_practice", "practice_percentile"),
    ]:
        narrow_pct = df.groupby(["grade", "learning_track"])[col].rank(pct=True) * 100
        wide_pct = df[col].rank(pct=True) * 100
        df[out_col] = np.where(use_narrow, narrow_pct, wide_pct)
        df[out_col] = df[out_col].round(1)
    df["peer_group"] = np.where(use_narrow, df["grade"].astype(str) + "-" + df["learning_track"], "all_students")
    return df


def attach_note_features(df: pd.DataFrame, notes: pd.DataFrame, quiz1_date: date, as_of_date: date) -> pd.DataFrame:
    """Adds note-derived features. Only trusted notes count toward
    post-quiz-activity evidence — an ownership-conflicted note might not even
    be about this student's real facilitator, so it should not make a
    student look "handled" when it may not be."""
    df = df.copy()
    trusted = notes[notes["trust_status"] == "trusted"]

    post_quiz_counts = (
        trusted[trusted["date"] >= quiz1_date].groupby("student_id").size().to_dict()
    )
    last_note_date = trusted.groupby("student_id")["date"].max().to_dict()
    last_note_severity_needs_follow_up = (
        trusted.sort_values("date").groupby("student_id")["ai_follow_up_needed"].last().to_dict()
    )

    df["post_quiz1_note_count"] = df["student_id"].map(post_quiz_counts).fillna(0).astype(int)
    df["has_post_quiz1_activity"] = df["post_quiz1_note_count"] > 0
    df["last_note_date"] = df["student_id"].map(last_note_date)
    df["days_since_note"] = df["last_note_date"].apply(
        lambda d: (as_of_date - d).days if pd.notna(d) else None
    )
    # Explicit None (not NaN) for "no note at all" — bool(float("nan")) is
    # True in Python, so leaving this as NaN would make every never-noted
    # student look like they have an unresolved follow-up.
    df["last_note_follow_up_needed"] = df["student_id"].map(last_note_severity_needs_follow_up).astype(object)
    df["last_note_follow_up_needed"] = df["last_note_follow_up_needed"].where(df["last_note_follow_up_needed"].notna(), None)
    return df


def attach_intervention_features(df: pd.DataFrame, interventions: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if interventions.empty:
        df["intervention_count"] = 0
        df["completed_intervention_count"] = 0
        df["last_successful_intervention"] = None
        df["has_overdue_intervention"] = False
        df["has_unresolved_intervention"] = False
        return df

    # "recommended" is a status the pipeline assigns to itself the moment a
    # pattern fires — it must NOT count as an intervention having happened,
    # or NO_POST_QUIZ_INTERVENTION would silently stop firing the moment the
    # system first recommends something, before any human has acted.
    attempted_or_beyond = {"in_progress", "attempted", "no_answer", "message_sent", "booked",
                           "completed", "follow_up_required", "escalated", "resolved"}
    active_unresolved = {"in_progress", "attempted", "no_answer", "follow_up_required", "escalated"}
    open_including_recommended = {"recommended"} | active_unresolved

    counts = interventions[interventions["status"].isin(attempted_or_beyond)].groupby("student_id").size().to_dict()
    completed = interventions[interventions["status"].isin(["completed", "resolved"])]
    completed_counts = completed.groupby("student_id").size().to_dict()
    last_success = completed.groupby("student_id")["completed_at"].max().to_dict()

    unresolved = interventions[interventions["status"].isin(active_unresolved)]
    unresolved_ids = set(unresolved["student_id"])
    overdue = interventions[
        interventions["status"].isin(open_including_recommended) & (pd.to_datetime(interventions["due_date"]) < pd.Timestamp.now())
    ]
    overdue_ids = set(overdue["student_id"])

    df["intervention_count"] = df["student_id"].map(counts).fillna(0).astype(int)
    df["completed_intervention_count"] = df["student_id"].map(completed_counts).fillna(0).astype(int)
    df["last_successful_intervention"] = df["student_id"].map(last_success)
    df["has_overdue_intervention"] = df["student_id"].isin(overdue_ids)
    df["has_unresolved_intervention"] = df["student_id"].isin(unresolved_ids)
    return df
