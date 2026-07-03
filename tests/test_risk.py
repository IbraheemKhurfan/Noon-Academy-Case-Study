"""Tests for the deterministic risk model in src/risk.py.

These call `score_student` directly with plain dicts rather than going
through the full pipeline — risk scoring is meant to be testable in
isolation from ingestion/features, which is the whole point of keeping it
rule-based (see the module docstring in src/risk.py).
"""

from __future__ import annotations

from src.risk import score_student

# A typical cohort's recent-practice distribution, used for every test so
# percentile-based scoring (recent_practice_points) is comparable across cases.
COHORT_P25 = 10.0
COHORT_MEDIAN = 20.0


def _student(**overrides) -> dict:
    """A reasonably healthy baseline student; tests override just the
    fields relevant to what they're checking."""
    base = {
        "quiz1_score": 85.0,
        "target_score": 80.0,
        "below_target": False,
        "missing_quiz_score": False,
        "missing_target_score": False,
        "recent_attendance_min": 180.0,
        "recent_practice_questions": 25.0,
        "has_post_quiz_intervention": True,
        "learning_track": "Standard",
        "total_attendance_min": 800.0,
        "total_practice_questions": 150.0,
    }
    base.update(overrides)
    return base


def test_low_quiz_low_attendance_no_practice_scores_higher_than_healthy_student():
    """The core promise of the model: a student who bombed Quiz 1, stopped
    attending, and stopped practicing must outrank a student who is fine."""
    struggling = _student(
        quiz1_score=32.0,
        target_score=80.0,
        below_target=True,
        recent_attendance_min=10.0,
        recent_practice_questions=0.0,
        has_post_quiz_intervention=False,
        learning_track="Remedial",
    )
    healthy = _student()

    struggling_result = score_student(struggling, COHORT_P25, COHORT_MEDIAN)
    healthy_result = score_student(healthy, COHORT_P25, COHORT_MEDIAN)

    assert struggling_result["risk_score"] > healthy_result["risk_score"]
    assert struggling_result["risk_level"] == "Critical"
    assert "LOW_QUIZ_SCORE" in struggling_result["reason_codes"]
    assert "LOW_RECENT_ATTENDANCE" in struggling_result["reason_codes"]
    assert "NO_RECENT_PRACTICE" in struggling_result["reason_codes"]


def test_below_target_but_active_student_does_not_become_critical():
    """A student who missed their (ambitious) target by a little, but is
    still attending fully and practicing above the cohort median, should
    read as Low/Medium risk — not Critical. This is what lets the system
    route them to an automated nudge instead of consuming facilitator time."""
    active_student = _student(
        quiz1_score=76.0,
        target_score=80.0,
        below_target=True,
        recent_attendance_min=180.0,
        recent_practice_questions=30.0,
        has_post_quiz_intervention=True,
    )

    result = score_student(active_student, COHORT_P25, COHORT_MEDIAN)

    assert result["risk_level"] != "Critical"
    assert result["risk_score"] < 30  # stays in the Low band


def test_missing_quiz_score_is_flagged_and_boosts_risk_without_crashing():
    """A student with no recorded Quiz 1 score must not crash scoring (no
    NaN comparisons blowing up) and must be flagged as operationally
    invisible rather than silently scoring as low-risk."""
    invisible_student = _student(
        quiz1_score=None,
        target_score=80.0,
        below_target=False,
        missing_quiz_score=True,
    )

    result = score_student(invisible_student, COHORT_P25, COHORT_MEDIAN)

    assert "MISSING_QUIZ_SCORE" in result["reason_codes"]
    assert result["risk_breakdown"]["missing_data_points"] > 0


def test_no_post_quiz_intervention_only_penalizes_below_target_students():
    on_target_no_note = _student(below_target=False, has_post_quiz_intervention=False)
    below_target_no_note = _student(
        quiz1_score=60.0, target_score=80.0, below_target=True, has_post_quiz_intervention=False
    )

    on_target_result = score_student(on_target_no_note, COHORT_P25, COHORT_MEDIAN)
    below_target_result = score_student(below_target_no_note, COHORT_P25, COHORT_MEDIAN)

    assert on_target_result["risk_breakdown"]["no_intervention_points"] == 0
    assert below_target_result["risk_breakdown"]["no_intervention_points"] > 0
    assert "NO_POST_QUIZ_INTERVENTION" in below_target_result["reason_codes"]


def test_remedial_track_adds_a_fixed_point_bump():
    standard = _student(learning_track="Standard")
    remedial = _student(learning_track="Remedial")

    standard_result = score_student(standard, COHORT_P25, COHORT_MEDIAN)
    remedial_result = score_student(remedial, COHORT_P25, COHORT_MEDIAN)

    assert remedial_result["risk_score"] - standard_result["risk_score"] == 5
    assert "REMEDIAL_TRACK" in remedial_result["reason_codes"]
