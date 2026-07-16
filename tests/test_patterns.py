"""Behavioral pattern detection is pure threshold logic over features — no
LLM involved (see src/patterns.py). These tests build minimal feature dicts
rather than running the full pipeline, so each rule is tested in isolation.
"""
from src.patterns import detect_patterns


def base_features(**overrides) -> dict:
    f = {
        "baseline_attendance": 80.0, "recent_attendance": 78.0, "attendance_trend": -2.0,
        "baseline_practice": 15.0, "recent_practice": 14.0, "practice_trend": -1.0,
        "zero_practice_streak": 0, "max_single_day_practice": 20.0, "extreme_practice_burst": False,
        "gap_to_target": 2.0, "quiz1_score": 78.0, "below_target": True,
        "post_quiz1_note_count": 1, "intervention_count": 1,
        "last_note_follow_up_needed": False, "completed_intervention_count": 1,
        "data_quality_flags": [],
    }
    f.update(overrides)
    return f


def codes(patterns: list[dict]) -> set[str]:
    return {p["code"] for p in patterns}


def test_acute_attendance_drop_detected():
    f = base_features(baseline_attendance=87.0, recent_attendance=22.0, attendance_trend=-65.0)
    result = codes(detect_patterns(f))
    assert "ACUTE_ATTENDANCE_DROP" in result


def test_no_acute_drop_when_stable():
    f = base_features()
    result = codes(detect_patterns(f))
    assert "ACUTE_ATTENDANCE_DROP" not in result


def test_attending_but_not_practicing_detected():
    f = base_features(recent_attendance=80.0, recent_practice=1.0)
    result = codes(detect_patterns(f))
    assert "ATTENDING_BUT_NOT_PRACTICING" in result


def test_cramming_pattern_detected():
    f = base_features(baseline_practice=5.0, recent_practice=5.0, max_single_day_practice=90.0)
    result = codes(detect_patterns(f))
    assert "CRAMMING_PATTERN" in result


def test_recovery_trajectory_detected():
    f = base_features(baseline_attendance=40.0, recent_attendance=65.0, attendance_trend=25.0)
    result = codes(detect_patterns(f))
    assert "RECOVERY_TRAJECTORY" in result


def test_stable_healthy_behavior_has_no_recovery_flag():
    f = base_features()
    result = codes(detect_patterns(f))
    assert "STABLE_HEALTHY_BEHAVIOR" in result
    assert "RECOVERY_TRAJECTORY" not in result


def test_no_post_quiz_intervention_when_no_documented_contact():
    f = base_features(post_quiz1_note_count=0, intervention_count=0, below_target=True)
    result = codes(detect_patterns(f))
    assert "NO_POST_QUIZ_INTERVENTION" in result


def test_missing_quiz_score_flags_possible_missed_assessment():
    f = base_features(quiz1_score=None, gap_to_target=None)
    result = codes(detect_patterns(f))
    assert "POSSIBLE_MISSED_ASSESSMENT" in result


def test_no_note_at_all_does_not_falsely_trigger_unresolved_follow_up():
    # A student with zero notes must have last_note_follow_up_needed=None,
    # not NaN — bool(float("nan")) is True in Python, which would make every
    # never-noted student look like they have an unresolved follow-up.
    f = base_features(last_note_follow_up_needed=None)
    result = codes(detect_patterns(f))
    assert "UNRESOLVED_FOLLOW_UP" not in result


def test_failing_quiz_score_detected_even_with_a_small_target_gap():
    # 58/100 is failing in absolute terms even though this student's target
    # (60) is barely above their score — a tiny gap must not hide it.
    f = base_features(quiz1_score=58.0, gap_to_target=2.0)
    result = codes(detect_patterns(f))
    assert "FAILING_QUIZ_SCORE" in result


def test_passing_score_never_flagged_as_failing_even_with_a_large_target_gap():
    # 70/100 against an ambitious target of 95 (gap=25) is a real gap, but
    # not a failing score — the two signals must stay distinct.
    f = base_features(quiz1_score=70.0, gap_to_target=25.0)
    result = codes(detect_patterns(f))
    assert "FAILING_QUIZ_SCORE" not in result
    assert "LARGE_TARGET_GAP" in result
