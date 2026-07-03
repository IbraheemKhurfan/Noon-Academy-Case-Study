"""Write every CSV/JSON artifact the pipeline produces.

Kept separate from `reporting.py` (which builds the narrative Markdown/HTML
documents) so the machine-readable outputs — the ones a facilitator tool or
CRM would actually ingest — have one obvious place to look.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.validate import QualityReport

RISK_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

ROSTER_COLUMNS = [
    "student_id",
    "student_name",
    "campus_id",
    "facilitator_email",
    "grade",
    "learning_track",
    "parent_phone",
    "quiz1_score",
    "target_score",
    "gap_to_target",
    "below_target",
    "recent_attendance_min",
    "recent_practice_questions",
    "has_post_quiz_intervention",
    "post_quiz_note_count",
    "risk_score",
    "risk_level",
    "reason_codes",
    "recommended_action",
    "sla",
    "human_effort",
    "facilitator_brief",
    "parent_script",
    "student_message",
    "next_best_step",
]


def _with_joined_reason_codes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["reason_codes"] = df["reason_codes"].apply(lambda codes: ";".join(codes or []))
    return df


def write_student_risk_roster(df: pd.DataFrame, output_dir: Path) -> Path:
    out = _with_joined_reason_codes(df)[ROSTER_COLUMNS]
    path = output_dir / "student_risk_roster.csv"
    out.to_csv(path, index=False)
    return path


def write_facilitator_worklists(df: pd.DataFrame, output_dir: Path) -> Path:
    """Same student-level data, re-sorted into each facilitator's queue: who
    to work on first, and how much of today's capacity it will consume."""
    out = _with_joined_reason_codes(df)[ROSTER_COLUMNS + ["estimated_minutes"]].copy()
    out["_risk_order"] = out["risk_level"].map(RISK_ORDER)
    out = out.sort_values(
        ["facilitator_email", "_risk_order", "risk_score"],
        ascending=[True, True, False],
    ).drop(columns="_risk_order")

    out["priority_rank_for_facilitator"] = out.groupby("facilitator_email").cumcount() + 1
    out["must_do_today"] = out["risk_level"].isin(["Critical", "High"])

    path = output_dir / "facilitator_worklists.csv"
    out.to_csv(path, index=False)
    return path


def write_intervention_actions(
    df: pd.DataFrame, output_dir: Path, current_date: pd.Timestamp
) -> Path:
    """One action-log row per student — the same shape a CRM/task queue
    would store, so this CSV can later be replaced by a real API write
    without changing anything upstream."""
    sla_offset_days = {
        "Today": 0,
        "Automated today": 0,
        "Within 24 hours": 1,
        "Within 48 hours": 2,
    }
    created_at = datetime.now(timezone.utc).isoformat()

    rows = []
    for i, row in enumerate(df.itertuples(), start=1):
        due_date = current_date + pd.Timedelta(days=sla_offset_days.get(row.sla, 0))
        message_draft = row.parent_script if row.channel in ("call", "whatsapp") else row.student_message
        rows.append(
            {
                "action_id": f"A{i:04d}",
                "student_id": row.student_id,
                "facilitator_email": row.facilitator_email,
                "risk_level": row.risk_level,
                "action_type": row.recommended_action,
                "due_date": due_date.date().isoformat(),
                "status": "recommended",
                "channel": row.channel,
                "message_draft": message_draft,
                "created_at": created_at,
            }
        )

    out = pd.DataFrame(rows)
    path = output_dir / "intervention_actions.csv"
    out.to_csv(path, index=False)
    return path


def write_data_quality_report(
    report: QualityReport, extra: dict, output_dir: Path
) -> Path:
    payload = report.as_dict()
    payload.update(extra)
    path = output_dir / "data_quality_report.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
