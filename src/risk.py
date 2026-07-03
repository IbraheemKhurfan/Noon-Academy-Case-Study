"""Deterministic, explainable risk scoring.

Risk is rule-based on purpose, not because an LLM couldn't produce a number:
1. Auditability — a facilitator (or a parent, or a campus lead) can ask "why
   is my kid Critical?" and get an exact point breakdown, not a paraphrase.
2. Determinism — the same input always produces the same score, so the
   roster is reproducible and unit-testable (see tests/test_risk.py).
3. Stability — an LLM score can drift between runs/models; six days before
   Quiz 2, a facilitator's queue should not reshuffle because a prompt
   changed. The LLM (src/llm.py) is used only to *phrase* communications
   about a score that has already been decided here.

Each point weight below is a straightforward, tunable constant. To evolve
the model later (e.g. after Quiz 2 outcomes are known), adjust the
thresholds/weights in one place — the calling code and reason codes stay
the same, so historical rosters remain comparable.
"""

from __future__ import annotations

import pandas as pd

# --- point caps, mirrors the case brief's scoring model ------------------
MAX_QUIZ_GAP_POINTS = 35
MAX_LOW_QUIZ_POINTS = 20
MAX_RECENT_ATTENDANCE_POINTS = 20
MAX_RECENT_PRACTICE_POINTS = 15
NO_INTERVENTION_POINTS = 10
REMEDIAL_TRACK_POINTS = 5
MAX_MISSING_DATA_POINTS = 10

CRITICAL_THRESHOLD = 65
HIGH_THRESHOLD = 50
MEDIUM_THRESHOLD = 30

REMEDIAL_KEYWORDS = ("remedial", "support", "foundation", "low")


def _quiz_gap_points(quiz1_score: float | None, target_score: float | None) -> float:
    if quiz1_score is None or target_score is None or pd.isna(quiz1_score) or pd.isna(target_score):
        return 0.0
    if quiz1_score >= target_score:
        return 0.0
    gap_fraction = (target_score - quiz1_score) / max(target_score, 1)
    return float(min(max(gap_fraction * MAX_QUIZ_GAP_POINTS, 0), MAX_QUIZ_GAP_POINTS))


def _low_quiz_points(quiz1_score: float | None) -> float:
    if quiz1_score is None or pd.isna(quiz1_score):
        return 0.0
    if quiz1_score < 40:
        return 20.0
    if quiz1_score < 60:
        return 12.0
    if quiz1_score < 70:
        return 6.0
    return 0.0


def _recent_attendance_points(recent_attendance_min: float) -> float:
    if recent_attendance_min < 45:
        return 20.0
    if recent_attendance_min < 90:
        return 14.0
    if recent_attendance_min < 135:
        return 8.0
    if recent_attendance_min < 160:
        return 4.0
    return 0.0


def _recent_practice_points(
    recent_practice_questions: float, cohort_p25: float, cohort_median: float
) -> float:
    if recent_practice_questions == 0:
        return 15.0
    if recent_practice_questions < cohort_p25:
        return 10.0
    if recent_practice_questions < cohort_median:
        return 5.0
    return 0.0


def _no_intervention_points(below_target: bool, has_post_quiz_intervention: bool) -> float:
    return NO_INTERVENTION_POINTS if below_target and not has_post_quiz_intervention else 0.0


def _remedial_track_points(learning_track: str | None) -> float:
    if not learning_track or pd.isna(learning_track):
        return 0.0
    track = str(learning_track).lower()
    return REMEDIAL_TRACK_POINTS if any(k in track for k in REMEDIAL_KEYWORDS) else 0.0


def _missing_data_points(
    missing_quiz_score: bool, missing_target_score: bool, severe_missing_records: bool
) -> float:
    # A student invisible to the data (no quiz score, no target, no
    # engagement history at all) is exactly the student most likely to be
    # overlooked by a human skimming a spreadsheet — so missing data itself
    # is a risk signal, capped so it can't alone push someone to Critical.
    points = 0.0
    if missing_quiz_score:
        points += 6.0
    if missing_target_score:
        points += 4.0
    if severe_missing_records:
        points += 4.0
    return min(points, MAX_MISSING_DATA_POINTS)


def _risk_level(score: float) -> str:
    if score >= CRITICAL_THRESHOLD:
        return "Critical"
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def score_student(student: dict, cohort_p25: float, cohort_median: float) -> dict:
    """Score a single student. Takes a plain dict (not a DataFrame row) so
    this function is trivial to unit test with synthetic inputs."""
    quiz1_score = student.get("quiz1_score")
    target_score = student.get("target_score")
    below_target = bool(student.get("below_target"))
    missing_quiz_score = bool(student.get("missing_quiz_score"))
    missing_target_score = bool(student.get("missing_target_score"))
    severe_missing_records = (
        student.get("total_attendance_min", 0) == 0
        and student.get("total_practice_questions", 0) == 0
    )

    quiz_gap = _quiz_gap_points(quiz1_score, target_score)
    low_quiz = _low_quiz_points(quiz1_score)
    recent_attendance = _recent_attendance_points(student.get("recent_attendance_min", 0))
    recent_practice = _recent_practice_points(
        student.get("recent_practice_questions", 0), cohort_p25, cohort_median
    )
    no_intervention = _no_intervention_points(
        below_target, bool(student.get("has_post_quiz_intervention"))
    )
    remedial = _remedial_track_points(student.get("learning_track"))
    missing_data = _missing_data_points(
        missing_quiz_score, missing_target_score, severe_missing_records
    )

    total = (
        quiz_gap + low_quiz + recent_attendance + recent_practice
        + no_intervention + remedial + missing_data
    )

    reason_codes = []
    if missing_quiz_score:
        reason_codes.append("MISSING_QUIZ_SCORE")
    if below_target:
        reason_codes.append("BELOW_TARGET")
    if quiz_gap >= 20:
        reason_codes.append("LARGE_TARGET_GAP")
    if low_quiz > 0:
        reason_codes.append("LOW_QUIZ_SCORE")
    if recent_attendance > 0:
        reason_codes.append("LOW_RECENT_ATTENDANCE")
    if recent_practice > 0:
        reason_codes.append("NO_RECENT_PRACTICE")
    if no_intervention > 0:
        reason_codes.append("NO_POST_QUIZ_INTERVENTION")
    if remedial > 0:
        reason_codes.append("REMEDIAL_TRACK")

    return {
        "risk_score": round(total, 1),
        "risk_level": _risk_level(total),
        "reason_codes": reason_codes,
        "risk_breakdown": {
            "quiz_gap_points": round(quiz_gap, 1),
            "low_quiz_points": round(low_quiz, 1),
            "recent_attendance_points": round(recent_attendance, 1),
            "recent_practice_points": round(recent_practice, 1),
            "no_intervention_points": round(no_intervention, 1),
            "remedial_track_points": round(remedial, 1),
            "missing_data_points": round(missing_data, 1),
        },
    }


def compute_risk(df: pd.DataFrame) -> pd.DataFrame:
    """Score every student in `df` and return it sorted by risk descending.

    Cohort percentiles for recent practice are computed once here (they
    need the full cohort, unlike every other signal which is per-student)
    and passed into `score_student` so scoring logic stays a pure function.
    """
    df = df.copy()
    cohort_p25 = df["recent_practice_questions"].quantile(0.25)
    cohort_median = df["recent_practice_questions"].median()

    results = [
        score_student(row, cohort_p25, cohort_median)
        for row in df.to_dict(orient="records")
    ]
    results_df = pd.DataFrame(results, index=df.index)
    df = pd.concat([df, results_df], axis=1)

    df = df.sort_values("risk_score", ascending=False).reset_index(drop=True)
    return df
