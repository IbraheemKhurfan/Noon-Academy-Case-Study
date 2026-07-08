"""Deterministic, explainable risk and priority scoring.

There are no Quiz 2 outcomes yet to train a model against, so risk is a
transparent weighted rule system instead of a trained classifier — every
point in the score traces back to a named, testable rule (see tests/test_risk.py).

Performance risk intentionally folds quiz score *and* gap-to-target into one
0-25 bucket instead of scoring them separately, because they are the same
underlying fact (how far below target the last quiz put the student) —
scoring both independently would double-count one piece of evidence.

Learning track is never scored directly. It is used only as context for
peer-group selection (see features.add_peer_percentiles) — a Remedial-track
student is not penalized simply for being in that track.
"""
from __future__ import annotations

from typing import Any, Optional

MAX_PERFORMANCE = 25
MAX_ENGAGEMENT = 25
MAX_TRAJECTORY = 25
MAX_TRUSTED_NOTE = 15
MAX_INTERVENTION_GAP = 10

HEALTHY_ATTENDANCE_MIN = 75.0
HEALTHY_PRACTICE_QUESTIONS = 20.0
LARGE_GAP_NORMALIZER = 40.0  # gap_to_target at which performance risk saturates

SEVERITY_RISK = {"critical": 15, "high": 10, "medium": 5, "low": 1, "unknown": 3}

RISK_LEVELS = (("Critical", 70), ("High", 50), ("Medium", 30), ("Low", 0))


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def risk_level_for(score: float) -> str:
    for label, floor in RISK_LEVELS:
        if score >= floor:
            return label
    return "Low"


def performance_risk(f: dict) -> tuple[float, Optional[str]]:
    if f.get("quiz1_score") is None:
        # Unknown, not zero — a missing score is a data problem
        # (POSSIBLE_MISSED_ASSESSMENT), not evidence the student is fine.
        return 15.0, "MISSING_QUIZ_SCORE"
    gap = f.get("gap_to_target") or 0
    if gap <= 0:
        return 0.0, None
    score = _clip(MAX_PERFORMANCE * gap / LARGE_GAP_NORMALIZER, 0, MAX_PERFORMANCE)
    reason = "LARGE_PERFORMANCE_GAP" if score >= 15 else ("MODERATE_PERFORMANCE_GAP" if score >= 7 else None)
    return score, reason


def engagement_risk(f: dict) -> tuple[float, Optional[str]]:
    attendance = f.get("recent_attendance")
    if attendance is None:
        attendance = f.get("avg_attendance")
    practice = f.get("recent_practice")
    if practice is None:
        practice = f.get("avg_practice")

    attendance_deficit = _clip((HEALTHY_ATTENDANCE_MIN - attendance) / HEALTHY_ATTENDANCE_MIN, 0, 1) if attendance is not None else 0.5
    practice_deficit = _clip((HEALTHY_PRACTICE_QUESTIONS - practice) / HEALTHY_PRACTICE_QUESTIONS, 0, 1) if practice is not None else 0.5

    score = attendance_deficit * (MAX_ENGAGEMENT / 2) + practice_deficit * (MAX_ENGAGEMENT / 2)
    score = _clip(score, 0, MAX_ENGAGEMENT)
    reason = "LOW_ENGAGEMENT" if score >= 15 else None
    return score, reason


def trajectory_risk(patterns: list[str]) -> tuple[float, Optional[str]]:
    score = 0.0
    if "ACUTE_ATTENDANCE_DROP" in patterns:
        score += 15
    elif "CHRONIC_LOW_ATTENDANCE" in patterns:
        score += 8
    if "PRACTICE_COLLAPSE" in patterns:
        score += 10
    if "ZERO_PRACTICE_STREAK" in patterns:
        score += 5
    if "CRAMMING_PATTERN" in patterns:
        score += 5
    if "RECOVERY_TRAJECTORY" in patterns:
        score -= 10
    if "STABLE_HEALTHY_BEHAVIOR" in patterns:
        score -= 5
    score = _clip(score, 0, MAX_TRAJECTORY)
    reason = "NEGATIVE_TRAJECTORY" if score >= 15 else None
    return score, reason


def trusted_note_risk(trusted_note_analyses: list[dict]) -> tuple[float, Optional[str]]:
    """Raw note text never sets numeric risk directly — only the LLM's (or
    fallback's) *validated, structured* severity classification does, and
    only for notes that passed ownership-trust validation."""
    if not trusted_note_analyses:
        return 0.0, None
    severities = [n.get("severity", "unknown") for n in trusted_note_analyses if n.get("severity")]
    worst = max(severities, key=lambda s: SEVERITY_RISK.get(s, 0), default="unknown")
    score = SEVERITY_RISK.get(worst, 0)
    if any(n.get("follow_up_needed") for n in trusted_note_analyses):
        score = min(MAX_TRUSTED_NOTE, score + 3)
    reason = "SEVERE_NOTE_CONCERN" if score >= 10 else None
    return float(score), reason


def intervention_gap(f: dict, patterns: list[str]) -> tuple[float, Optional[str]]:
    if "NO_POST_QUIZ_INTERVENTION" in patterns:
        return float(MAX_INTERVENTION_GAP), "NO_DOCUMENTED_INTERVENTION"
    if f.get("last_note_follow_up_needed") and not f.get("completed_intervention_count", 0):
        return MAX_INTERVENTION_GAP / 2, "UNRESOLVED_FOLLOW_UP"
    return 0.0, None


def confidence_score(f: dict) -> float:
    confidence = 1.0
    flags = set(f.get("data_quality_flags", []))
    if "MISSING_ATTENDANCE" in flags:
        confidence -= 0.15
    if f.get("quiz1_score") is None:
        confidence -= 0.2
    if flags & {"ATTENDANCE_OUT_OF_RANGE", "NEGATIVE_PRACTICE", "QUIZ_SCORE_DATE_ANOMALY"}:
        confidence -= 0.1
    if "NOTE_OWNERSHIP_CONFLICT" in flags:
        confidence -= 0.1
    if f.get("n_metric_rows", 0) < 8:
        confidence -= 0.1
    return round(_clip(confidence, 0.3, 1.0), 2)


def urgency_score(f: dict, risk_level: str) -> float:
    days_left = f.get("days_until_quiz2")
    time_component = _clip((10 - days_left) / 10, 0, 1) * 40 if days_left is not None else 20
    if f.get("has_overdue_intervention"):
        contact_component = 30
    elif f.get("has_unresolved_intervention"):
        contact_component = 15
    else:
        contact_component = 0
    level_component = {"Critical": 10, "High": 7, "Medium": 3, "Low": 0}.get(risk_level, 0)
    return round(_clip(time_component + contact_component + level_component, 0, 100), 1)


def score_student(f: dict, pattern_codes: list[str], trusted_note_analyses: list[dict]) -> dict[str, Any]:
    perf, perf_reason = performance_risk(f)
    eng, eng_reason = engagement_risk(f)
    traj, traj_reason = trajectory_risk(pattern_codes)
    note_risk, note_reason = trusted_note_risk(trusted_note_analyses)
    gap_risk, gap_reason = intervention_gap(f, pattern_codes)

    risk = round(_clip(perf + eng + traj + note_risk + gap_risk, 0, 100), 1)
    level = risk_level_for(risk)
    confidence = confidence_score(f)
    urgency = urgency_score(f, level)
    priority = round(_clip(0.8 * risk + 0.2 * urgency, 0, 100), 1)

    reason_codes = [r for r in [perf_reason, eng_reason, traj_reason, note_reason, gap_reason] if r]

    return {
        "risk_score": risk,
        "risk_level": level,
        "confidence": confidence,
        "urgency_score": urgency,
        "priority_score": priority,
        "reason_codes": reason_codes,
        "components": {
            "performance_risk": round(perf, 1),
            "engagement_risk": round(eng, 1),
            "trajectory_risk": round(traj, 1),
            "trusted_note_risk": round(note_risk, 1),
            "intervention_gap": round(gap_risk, 1),
        },
    }
