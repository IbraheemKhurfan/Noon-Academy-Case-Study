"""Maps detected patterns + risk level to a single practical recommended
action. Purely rule-based — the LLM is never involved in deciding *what* to
do, only in *how to phrase* the communication once an action is chosen.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

ACTION_META = {
    "PARENT_CALL": {"sla_hours": 24, "effort_min": 15,
                     "label": "Call the parent",
                     "next_step": "Call the parent today; if unreachable, send WhatsApp and try again within 24h."},
    "STUDENT_CHECK_IN": {"sla_hours": 48, "effort_min": 10,
                          "label": "Student check-in",
                          "next_step": "Have a short 1:1 chat before/after the next session to understand the barrier."},
    "MOTIVATIONAL_MESSAGE": {"sla_hours": 48, "effort_min": 5,
                              "label": "Send a motivational message",
                              "next_step": "Send a short motivational nudge; no heavy intervention needed."},
    "PRACTICE_PLAN": {"sla_hours": 48, "effort_min": 15,
                       "label": "Build a practice plan",
                       "next_step": "Agree on a small daily practice target (e.g. 10 questions) and check in tomorrow."},
    "ONE_TO_ONE_TUTORING": {"sla_hours": 72, "effort_min": 45,
                             "label": "Book 1-on-1 tutoring",
                             "next_step": "Book a focused tutoring slot on the weak topic before Quiz 2."},
    "STUDY_PLANNING": {"sla_hours": 72, "effort_min": 20,
                        "label": "Build a study plan",
                        "next_step": "Help spread practice across the remaining days instead of one burst."},
    "ATTENDANCE_FOLLOW_UP": {"sla_hours": 24, "effort_min": 10,
                              "label": "Attendance follow-up",
                              "next_step": "Confirm attendance for the next session and note the reason for the gap."},
    "DATA_REVIEW": {"sla_hours": 48, "effort_min": 10,
                     "label": "Review the data",
                     "next_step": "Verify the missing/odd data point with the facilitator before acting on it."},
    "MONITOR_ONLY": {"sla_hours": 168, "effort_min": 2,
                      "label": "Monitor only",
                      "next_step": "No action needed now — keep monitoring."},
    "POSITIVE_REINFORCEMENT": {"sla_hours": 72, "effort_min": 5,
                                "label": "Positive reinforcement",
                                "next_step": "Acknowledge the improvement; keep momentum with light encouragement."},
}

# A parent call is disruptive and should be reserved for genuinely severe
# situations, not handed out to every student below target (section 21).
PARENT_CALL_PATTERNS = {"ACUTE_ATTENDANCE_DROP", "CHRONIC_LOW_ATTENDANCE", "NO_POST_QUIZ_INTERVENTION", "UNRESOLVED_FOLLOW_UP"}


def qualifies_for_parent_call(pattern_codes: set[str], risk_level: str, f: dict) -> bool:
    if risk_level == "Critical" and (pattern_codes & PARENT_CALL_PATTERNS or f.get("zero_attendance_streak", 0) >= 2
                                      or f.get("has_overdue_intervention")):
        return True
    if risk_level == "High" and "ACUTE_ATTENDANCE_DROP" in pattern_codes:
        return True
    return False


def _pick_primary_pattern(patterns: list[dict], code: str) -> dict | None:
    return next((p for p in patterns if p["code"] == code), None)


def recommend_action(f: dict, patterns: list[dict], risk_level: str, as_of: date) -> dict[str, Any]:
    codes = {p["code"] for p in patterns}
    parent_call_ok = qualifies_for_parent_call(codes, risk_level, f)

    action_type = "MONITOR_ONLY"
    primary_pattern = None

    if ("ACUTE_ATTENDANCE_DROP" in codes or "CHRONIC_LOW_ATTENDANCE" in codes):
        primary_pattern = _pick_primary_pattern(patterns, "ACUTE_ATTENDANCE_DROP") or _pick_primary_pattern(patterns, "CHRONIC_LOW_ATTENDANCE")
        action_type = "PARENT_CALL" if parent_call_ok else "ATTENDANCE_FOLLOW_UP"
    elif "ATTENDING_BUT_NOT_PRACTICING" in codes:
        primary_pattern = _pick_primary_pattern(patterns, "ATTENDING_BUT_NOT_PRACTICING")
        action_type = "STUDENT_CHECK_IN"
    elif "PRACTICE_COLLAPSE" in codes or "ZERO_PRACTICE_STREAK" in codes:
        primary_pattern = _pick_primary_pattern(patterns, "PRACTICE_COLLAPSE") or _pick_primary_pattern(patterns, "ZERO_PRACTICE_STREAK")
        action_type = "PRACTICE_PLAN"
    elif "CRAMMING_PATTERN" in codes:
        primary_pattern = _pick_primary_pattern(patterns, "CRAMMING_PATTERN")
        action_type = "STUDY_PLANNING"
    elif "POSSIBLE_MISSED_ASSESSMENT" in codes:
        primary_pattern = _pick_primary_pattern(patterns, "POSSIBLE_MISSED_ASSESSMENT")
        action_type = "DATA_REVIEW"
    elif "NO_POST_QUIZ_INTERVENTION" in codes and risk_level in ("Critical", "High"):
        primary_pattern = _pick_primary_pattern(patterns, "NO_POST_QUIZ_INTERVENTION")
        action_type = "ONE_TO_ONE_TUTORING" if risk_level == "Critical" else ("PARENT_CALL" if parent_call_ok else "STUDENT_CHECK_IN")
    elif "UNRESOLVED_FOLLOW_UP" in codes:
        primary_pattern = _pick_primary_pattern(patterns, "UNRESOLVED_FOLLOW_UP")
        action_type = "PARENT_CALL" if parent_call_ok else "STUDENT_CHECK_IN"
    elif "RECOVERY_TRAJECTORY" in codes:
        primary_pattern = _pick_primary_pattern(patterns, "RECOVERY_TRAJECTORY")
        action_type = "POSITIVE_REINFORCEMENT"
    elif "DATA_QUALITY_RISK" in codes and risk_level in ("Critical", "High"):
        primary_pattern = _pick_primary_pattern(patterns, "DATA_QUALITY_RISK")
        action_type = "DATA_REVIEW"
    elif "FAILING_QUIZ_SCORE" in codes and risk_level in ("Critical", "High", "Medium"):
        # A failing score needs real academic help, not just encouragement —
        # a motivational message doesn't close a skills gap. Checked ahead of
        # the generic below-target fallback so a failing student never lands
        # on a plain "send a nice message" recommendation.
        primary_pattern = _pick_primary_pattern(patterns, "FAILING_QUIZ_SCORE")
        action_type = "ONE_TO_ONE_TUTORING" if risk_level in ("Critical", "High") else "PRACTICE_PLAN"
    elif f.get("below_target") and risk_level in ("Medium", "Low"):
        primary_pattern = _pick_primary_pattern(patterns, "STABLE_HEALTHY_BEHAVIOR") or _pick_primary_pattern(patterns, "LARGE_TARGET_GAP")
        action_type = "MOTIVATIONAL_MESSAGE"

    meta = ACTION_META[action_type]
    # An SLA counts from *now*, so a 24h SLA means "by the end of today," not
    # tomorrow — the previous version always added at least one full day,
    # which meant nothing was ever due today and the Actions page's "Due
    # Today" tab (and the My Day KPI) stayed empty even on Day 14 itself.
    days_offset = max(0, -(-meta["sla_hours"] // 24) - 1)
    due_date = as_of + timedelta(days=days_offset)

    brief_lead = primary_pattern["explanation"] if primary_pattern else \
        "No acute concern detected; behavior looks stable relative to peers."
    brief = f"{brief_lead} Recommended: {meta['label']}."

    return {
        "action_type": action_type,
        "priority": risk_level,
        "due_date": due_date,
        "sla_hours": meta["sla_hours"],
        "estimated_minutes": meta["effort_min"],
        "brief": brief,
        "next_step": meta["next_step"],
    }
