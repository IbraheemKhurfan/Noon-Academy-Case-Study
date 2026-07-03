"""Turn a risk score into a concrete, assignable action.

Two-pass design: (1) deterministic templates decide *what* to do and *how
urgently* purely from `risk_level` — this always works, with or without an
LLM, and is what makes the system usable the moment `make demo` finishes.
(2) `src/llm.py` then rewrites the human-facing text (facilitator brief,
parent script, student message) to be warmer and note-aware. If the LLM is
unavailable, its own fallback templates are used instead, so the roster
never ships with empty message fields.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import Settings
from src.llm import build_student_context, get_llm_response

# --- tier -> action policy, per the case brief --------------------------
ACTION_POLICY = {
    "Critical": {
        "recommended_action": "parent_call_plus_tutoring",
        "sla": "Today",
        "human_effort": "High",
        "estimated_minutes": 20,
        "channel": "call",
    },
    "High": {
        "recommended_action": "parent_call_or_voice_note",
        "sla": "Within 24 hours",
        "human_effort": "Medium",
        "estimated_minutes": 10,
        "channel": "call",
    },
    "Medium": {
        "recommended_action": "student_checkin_plus_practice_plan",
        "sla": "Within 48 hours",
        "human_effort": "Low",
        "estimated_minutes": 3,
        "channel": "whatsapp",
    },
    "Low": {
        "recommended_action": "automated_motivation_message",
        "sla": "Automated today",
        "human_effort": "None",
        "estimated_minutes": 0,
        "channel": "automated",
    },
}


def _base_facilitator_brief(row: pd.Series, days_to_quiz2: int) -> str:
    quiz = row.get("quiz1_score")
    target = row.get("target_score")
    gap_txt = (
        f"scored {quiz:.0f} vs target {target:.0f}"
        if pd.notna(quiz) and pd.notna(target)
        else "has no recorded Quiz 1 score"
    )
    return (
        f"{row['student_name']} is {row['risk_level']} risk ({gap_txt}, "
        f"{days_to_quiz2} days to Quiz 2). Reasons: {', '.join(row['reason_codes']) or 'n/a'}."
    )


def _base_parent_script(row: pd.Series, days_to_quiz2: int) -> str:
    return (
        f"Hi, this is {row['facilitator_email'].split('@')[0]} from Boon Academy calling about "
        f"{row['student_name']}. We'd like to talk through how we can support {row['student_name']} "
        f"together before Quiz 2 in {days_to_quiz2} days."
    )


def _base_student_message(row: pd.Series) -> str:
    return (
        f"Hey {row['student_name']}, you've got this! Let's lock in a short daily practice "
        f"habit this week and head into Quiz 2 feeling ready."
    )


def _base_next_best_step(row: pd.Series) -> str:
    policy = ACTION_POLICY[row["risk_level"]]
    return f"{policy['recommended_action'].replace('_', ' ').title()} — {policy['sla']}"


def generate_actions(
    df: pd.DataFrame, settings: Settings, llm_log_path: Path
) -> pd.DataFrame:
    """Add action-plan and messaging columns to the scored roster."""
    df = df.copy()
    days_to_quiz2 = settings.quiz2_day - settings.current_day

    policy_frame = df["risk_level"].map(ACTION_POLICY).apply(pd.Series)
    df["recommended_action"] = policy_frame["recommended_action"]
    df["sla"] = policy_frame["sla"]
    df["human_effort"] = policy_frame["human_effort"]
    df["estimated_minutes"] = policy_frame["estimated_minutes"]
    df["channel"] = policy_frame["channel"]

    facilitator_briefs, parent_scripts, student_messages, next_steps = [], [], [], []

    for _, row in df.iterrows():
        base_brief = _base_facilitator_brief(row, days_to_quiz2)
        base_parent = _base_parent_script(row, days_to_quiz2)
        base_student = _base_student_message(row)
        base_next = _base_next_best_step(row)

        context = build_student_context(row.to_dict())
        llm_response = get_llm_response(context, settings, llm_log_path)

        # LLM output enriches the deterministic base; empty/whitespace
        # responses (shouldn't happen given pydantic validation, but data
        # is data) fall back to the template so a field is never blank.
        facilitator_briefs.append(llm_response.facilitator_brief.strip() or base_brief)
        parent_scripts.append(llm_response.parent_message_ar.strip() or base_parent)
        student_messages.append(llm_response.student_message_ar.strip() or base_student)
        next_steps.append(llm_response.next_step.strip() or base_next)

    df["facilitator_brief"] = facilitator_briefs
    df["parent_script"] = parent_scripts
    df["student_message"] = student_messages
    df["next_best_step"] = next_steps

    return df
