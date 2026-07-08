"""Risk scoring is a deterministic weighted rule system (see src/scoring.py
for why: there are no Quiz 2 outcomes yet to train a model against)."""
from src.features import _safe_mean, _trailing_zero_streak
from src.patterns import detect_patterns
from src.scoring import score_student
from tests.test_patterns import base_features


def test_severe_dropout_ranks_above_stable_student():
    dropout = base_features(
        baseline_attendance=85.0, recent_attendance=15.0, attendance_trend=-70.0,
        baseline_practice=18.0, recent_practice=2.0, practice_trend=-16.0,
        zero_practice_streak=4, gap_to_target=15.0, quiz1_score=65.0,
        post_quiz1_note_count=0, intervention_count=0, last_note_follow_up_needed=None,
    )
    stable = base_features(gap_to_target=3.0, quiz1_score=77.0)

    dropout_patterns = [p["code"] for p in detect_patterns(dropout)]
    stable_patterns = [p["code"] for p in detect_patterns(stable)]

    dropout_score = score_student(dropout, dropout_patterns, [])
    stable_score = score_student(stable, stable_patterns, [])

    assert dropout_score["risk_score"] > stable_score["risk_score"]
    assert dropout_score["risk_level"] in ("Critical", "High")


def test_stable_student_slightly_below_target_is_not_automatically_critical():
    stable = base_features(gap_to_target=3.0, quiz1_score=77.0)
    patterns = [p["code"] for p in detect_patterns(stable)]
    result = score_student(stable, patterns, [])
    assert result["risk_level"] != "Critical"


def test_risk_score_always_within_0_100():
    extreme = base_features(
        baseline_attendance=90.0, recent_attendance=0.0, attendance_trend=-90.0,
        baseline_practice=30.0, recent_practice=0.0, practice_trend=-30.0,
        zero_practice_streak=10, gap_to_target=80.0, quiz1_score=0.0,
        post_quiz1_note_count=0, intervention_count=0,
    )
    patterns = [p["code"] for p in detect_patterns(extreme)]
    result = score_student(extreme, patterns,
                            [{"severity": "critical", "follow_up_needed": True}])
    assert 0 <= result["risk_score"] <= 100
    assert 0 <= result["priority_score"] <= 100


def test_missing_attendance_is_not_treated_as_zero_in_feature_averages():
    # None values must be dropped from the mean, not counted as 0 minutes.
    values = [60.0, None, 80.0]
    import pandas as pd
    assert _safe_mean(pd.Series(values)) == 70.0  # (60+80)/2, not (60+0+80)/3


def test_trailing_zero_streak_stops_at_missing_value():
    assert _trailing_zero_streak([5, 0, 0, None]) == 0  # trailing value is unknown, not zero
    assert _trailing_zero_streak([5, 0, 0, 0]) == 3
