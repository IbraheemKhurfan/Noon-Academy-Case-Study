"""Deterministic behavioral pattern detection.

Every rule here is a plain threshold on measured features — no LLM call.
Behavior change is exactly the kind of signal a language model would be
unreliable and unauditable at scoring, while a threshold on "minutes of
attendance" is trivial to check, explain, and unit test.
"""
from __future__ import annotations

from typing import Any

from src.config import FAILING_SCORE_THRESHOLD

# Thresholds are simple, named constants so every rule is auditable at a glance.
ACUTE_DROP_MIN_BASELINE = 45
ACUTE_DROP_THRESHOLD = 30
CHRONIC_LOW_ATTENDANCE_THRESHOLD = 45
ATTENDING_THRESHOLD = 60
NOT_PRACTICING_THRESHOLD = 5
ZERO_STREAK_THRESHOLD = 3
PRACTICE_COLLAPSE_MIN_BASELINE = 10
PRACTICE_COLLAPSE_RATIO = 0.4
CRAMMING_ABSOLUTE = 60
CRAMMING_RELATIVE_MULTIPLIER = 3
RECOVERY_ATTENDANCE_GAIN = 20
RECOVERY_LOW_BASELINE = 70
RECOVERY_PRACTICE_LOW_BASELINE = 15
STABLE_ATTENDANCE_FLOOR = 60
STABLE_PRACTICE_FLOOR = 10
STABLE_TREND_BAND_ATTENDANCE = 15
STABLE_TREND_BAND_PRACTICE = 8
LARGE_GAP_THRESHOLD = 20

TRUST_IMPACTING_FLAGS = {
    "MISSING_ATTENDANCE", "ATTENDANCE_OUT_OF_RANGE", "NEGATIVE_PRACTICE",
    "QUIZ_SCORE_DATE_ANOMALY", "NOTE_OWNERSHIP_CONFLICT", "NOTE_CONTENT_MISMATCH",
}


def _pattern(code: str, explanation: str, evidence: dict[str, Any]) -> dict:
    return {"code": code, "explanation": explanation, "evidence": evidence}


def detect_patterns(f: dict) -> list[dict]:
    """f is one row of the features table (as a dict)."""
    patterns: list[dict] = []

    baseline_att, recent_att, trend_att = f.get("baseline_attendance"), f.get("recent_attendance"), f.get("attendance_trend")
    baseline_prac, recent_prac, trend_prac = f.get("baseline_practice"), f.get("recent_practice"), f.get("practice_trend")

    if trend_att is not None and baseline_att is not None and baseline_att >= ACUTE_DROP_MIN_BASELINE \
            and trend_att <= -ACUTE_DROP_THRESHOLD:
        patterns.append(_pattern(
            "ACUTE_ATTENDANCE_DROP",
            f"Recent attendance fell by {abs(trend_att):.0f} minutes compared with the student's previous baseline.",
            {"previous_average_min": round(baseline_att, 1), "recent_average_min": round(recent_att, 1)},
        ))

    if baseline_att is not None and recent_att is not None \
            and baseline_att < CHRONIC_LOW_ATTENDANCE_THRESHOLD and recent_att < CHRONIC_LOW_ATTENDANCE_THRESHOLD:
        patterns.append(_pattern(
            "CHRONIC_LOW_ATTENDANCE",
            f"Attendance has stayed low both before and after Quiz 1 (baseline {baseline_att:.0f} min, "
            f"recent {recent_att:.0f} min) — this is not a new drop.",
            {"baseline_average_min": round(baseline_att, 1), "recent_average_min": round(recent_att, 1)},
        ))

    if recent_att is not None and recent_prac is not None \
            and recent_att >= ATTENDING_THRESHOLD and recent_prac <= NOT_PRACTICING_THRESHOLD:
        patterns.append(_pattern(
            "ATTENDING_BUT_NOT_PRACTICING",
            f"Student is still attending sessions ({recent_att:.0f} min/day recently) but has nearly stopped "
            f"evening practice ({recent_prac:.0f} questions/day).",
            {"recent_attendance_min": round(recent_att, 1), "recent_practice_questions": round(recent_prac, 1)},
        ))

    if f.get("zero_practice_streak", 0) >= ZERO_STREAK_THRESHOLD:
        patterns.append(_pattern(
            "ZERO_PRACTICE_STREAK",
            f"Student has logged zero practice questions for {f['zero_practice_streak']} consecutive recorded days.",
            {"zero_practice_streak_days": f["zero_practice_streak"]},
        ))

    if baseline_prac is not None and recent_prac is not None \
            and baseline_prac >= PRACTICE_COLLAPSE_MIN_BASELINE and recent_prac <= baseline_prac * PRACTICE_COLLAPSE_RATIO:
        patterns.append(_pattern(
            "PRACTICE_COLLAPSE",
            f"Evening practice dropped from {baseline_prac:.0f} to {recent_prac:.0f} questions/day on average "
            f"({(1 - recent_prac / baseline_prac) * 100:.0f}% decline).",
            {"baseline_average_questions": round(baseline_prac, 1), "recent_average_questions": round(recent_prac, 1)},
        ))

    max_single_day = f.get("max_single_day_practice", 0) or 0
    cramming_bar = max(CRAMMING_ABSOLUTE, CRAMMING_RELATIVE_MULTIPLIER * (baseline_prac or 0))
    if f.get("extreme_practice_burst") or max_single_day >= cramming_bar:
        patterns.append(_pattern(
            "CRAMMING_PATTERN",
            f"A single-day practice spike of {max_single_day:.0f} questions stands far above the student's "
            f"typical daily volume — consistent with cramming rather than steady practice.",
            {"max_single_day_questions": max_single_day, "baseline_average_questions": round(baseline_prac, 1) if baseline_prac is not None else None},
        ))

    if (trend_att is not None and trend_att >= RECOVERY_ATTENDANCE_GAIN and (baseline_att or 0) < RECOVERY_LOW_BASELINE) \
            or (trend_prac is not None and baseline_prac is not None and 0 < baseline_prac < RECOVERY_PRACTICE_LOW_BASELINE
                and trend_prac >= baseline_prac * 0.5):
        patterns.append(_pattern(
            "RECOVERY_TRAJECTORY",
            "Attendance and/or practice have improved noticeably since Quiz 1, starting from a low baseline.",
            {"attendance_trend_min": round(trend_att, 1) if trend_att is not None else None,
             "practice_trend_questions": round(trend_prac, 1) if trend_prac is not None else None},
        ))

    if recent_att is not None and recent_prac is not None \
            and recent_att >= STABLE_ATTENDANCE_FLOOR and recent_prac >= STABLE_PRACTICE_FLOOR \
            and (trend_att is None or abs(trend_att) < STABLE_TREND_BAND_ATTENDANCE) \
            and (trend_prac is None or abs(trend_prac) < STABLE_TREND_BAND_PRACTICE):
        patterns.append(_pattern(
            "STABLE_HEALTHY_BEHAVIOR",
            f"Attendance ({recent_att:.0f} min) and practice ({recent_prac:.0f} questions) are both healthy and "
            f"steady — no concerning change in behavior.",
            {"recent_attendance_min": round(recent_att, 1), "recent_practice_questions": round(recent_prac, 1)},
        ))

    # Failing is an absolute floor (below60/100), independent of this
    # student's own target — a student scoring 55 with a target of 60 is a
    # genuinely different, more urgent situation than one scoring 70 against
    # a target of 95, even though the second student's gap-to-target is
    # larger. Checked ahead of LARGE_TARGET_GAP so it takes priority as the
    # headline "why" when both are true (which, in this cohort, is nearly
    # always — every failing student is also below their own target).
    quiz1_score = f.get("quiz1_score")
    if quiz1_score is not None and quiz1_score < FAILING_SCORE_THRESHOLD:
        patterns.append(_pattern(
            "FAILING_QUIZ_SCORE",
            f"Quiz 1 score of {quiz1_score:.0f}/100 is a failing score in absolute terms — this is true "
            f"regardless of this student's individual target.",
            {"quiz1_score": quiz1_score, "target_score": f.get("target_score"),
             "failing_threshold": FAILING_SCORE_THRESHOLD},
        ))

    gap = f.get("gap_to_target")
    if gap is not None and gap >= LARGE_GAP_THRESHOLD:
        patterns.append(_pattern(
            "LARGE_TARGET_GAP",
            f"Quiz 1 score is {gap:.0f} points below the student's target score.",
            {"quiz1_score": f.get("quiz1_score"), "target_score": f.get("target_score"), "gap": round(gap, 1)},
        ))

    if f.get("quiz1_score") is None:
        patterns.append(_pattern(
            "POSSIBLE_MISSED_ASSESSMENT",
            "No Quiz 1 score is recorded for this student as of today — this may mean the assessment was missed, "
            "or simply not yet entered.",
            {"quiz1_score": None},
        ))

    below_target = f.get("below_target")
    needs_help = bool(below_target) or f.get("quiz1_score") is None
    if needs_help and f.get("post_quiz1_note_count", 0) == 0 and f.get("intervention_count", 0) == 0:
        patterns.append(_pattern(
            "NO_POST_QUIZ_INTERVENTION",
            "Student appears to need support, but there is no documented facilitator contact or intervention "
            "since Quiz 1.",
            {"post_quiz1_note_count": f.get("post_quiz1_note_count", 0), "intervention_count": f.get("intervention_count", 0)},
        ))

    if f.get("last_note_follow_up_needed") and not f.get("completed_intervention_count", 0):
        patterns.append(_pattern(
            "UNRESOLVED_FOLLOW_UP",
            "The most recent trusted facilitator note flagged that follow-up is still needed, and no intervention "
            "has since been completed.",
            {"last_note_date": str(f.get("last_note_date")), "completed_intervention_count": f.get("completed_intervention_count", 0)},
        ))

    quality_flags = [q for q in f.get("data_quality_flags", []) if q in TRUST_IMPACTING_FLAGS]
    if quality_flags:
        patterns.append(_pattern(
            "DATA_QUALITY_RISK",
            f"This student's record has data-quality issues ({', '.join(quality_flags)}) that reduce confidence "
            f"in the risk score.",
            {"flags": quality_flags},
        ))

    return patterns
