"""Load and clean the three source CSVs.

All paths come from `Settings.data_dir` (env `DATA_DIR`) — never a hardcoded
local path — so the same code runs unchanged on a laptop, CI, or a future
100-campus deployment pointed at a different data root.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.validate import (
    QualityReport,
    clip_attendance,
    dedupe_metadata,
    exclude_orphans,
    fill_missing_engagement,
    fix_negative_practice,
    normalize_columns,
    parse_dates,
    require_student_id,
)

METRICS_REQUIRED = {"student_id", "date", "session_attended_min", "practice_questions"}
NOTES_REQUIRED = {"note_id", "student_id", "facilitator_email", "date", "note_text"}
META_REQUIRED = {
    "student_id",
    "student_name",
    "campus_id",
    "facilitator_email",
    "grade",
    "parent_phone",
    "target_score",
    "learning_track",
}

# Quiz score columns vary by campus export ("quiz_score", "quiz_1_score",
# "quiz1_score", "last_quiz_score", ...). We match on intent (mentions both
# "quiz" and "score") rather than a fixed name list, and prefer a column
# that explicitly says "1" since Quiz 1 is the only quiz that has happened.
_QUIZ_COL_PATTERN = re.compile(r"quiz.*score|score.*quiz")


def detect_quiz_column(columns: list[str]) -> str | None:
    candidates = [c for c in columns if _QUIZ_COL_PATTERN.search(c)]
    if not candidates:
        return None
    explicitly_quiz1 = [c for c in candidates if "1" in c]
    return sorted(explicitly_quiz1 or candidates)[0]


def _ensure_columns(
    df: pd.DataFrame, required: set[str], name: str, report: QualityReport
) -> pd.DataFrame:
    """Add any missing required column as all-null rather than raising, so a
    partially-broken export still produces a (flagged) roster instead of a
    crash. Downstream fill/default logic treats an all-null column the same
    as scattered missing values."""
    df = df.copy()
    missing = sorted(required - set(df.columns))
    if missing:
        report.add(
            check=f"{name}_missing_columns",
            severity="error",
            count=len(missing),
            detail=f"{name} is missing required columns {missing}; filled as null and treated as missing data",
        )
        for col in missing:
            df[col] = pd.NA
    return df


def load_raw_data(
    data_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, QualityReport]:
    """Read, normalize, and repair the three source CSVs.

    Returns (metrics, notes, metadata, quality_report). The frames returned
    here are already clipped/filled/orphan-filtered — `src/features.py`
    can assume clean inputs and focus purely on feature logic.
    """
    report = QualityReport()

    metrics = normalize_columns(pd.read_csv(data_dir / "student_daily_metrics.csv"))
    notes = normalize_columns(pd.read_csv(data_dir / "facilitator_notes.csv"))
    meta = normalize_columns(pd.read_csv(data_dir / "student_metadata.csv"))

    metrics = _ensure_columns(metrics, METRICS_REQUIRED, "student_daily_metrics", report)
    notes = _ensure_columns(notes, NOTES_REQUIRED, "facilitator_notes", report)
    meta = _ensure_columns(meta, META_REQUIRED, "student_metadata", report)

    # Standardize whichever quiz-score column variant is present.
    quiz_col = detect_quiz_column(list(metrics.columns))
    if quiz_col is None:
        report.add(
            check="quiz_score_column_not_found",
            severity="error",
            count=1,
            detail="No quiz-score-like column found in student_daily_metrics.csv; all students treated as missing_quiz_score",
        )
        metrics["quiz_score"] = pd.NA
    else:
        metrics = metrics.rename(columns={quiz_col: "quiz_score"})

    metrics = parse_dates(metrics, "date", "student_daily_metrics", report)
    notes = parse_dates(notes, "date", "facilitator_notes", report)

    metrics = require_student_id(metrics, "student_daily_metrics", report)
    notes = require_student_id(notes, "facilitator_notes", report)
    meta = require_student_id(meta, "student_metadata", report)

    meta = dedupe_metadata(meta, report)

    metrics["student_id"] = metrics["student_id"].astype(str).str.strip()
    notes["student_id"] = notes["student_id"].astype(str).str.strip()
    meta["student_id"] = meta["student_id"].astype(str).str.strip()

    metrics["session_attended_min"] = pd.to_numeric(
        metrics["session_attended_min"], errors="coerce"
    )
    metrics["practice_questions"] = pd.to_numeric(
        metrics["practice_questions"], errors="coerce"
    )
    metrics["quiz_score"] = pd.to_numeric(metrics["quiz_score"], errors="coerce")
    meta["target_score"] = pd.to_numeric(meta["target_score"], errors="coerce")

    metrics = clip_attendance(metrics, report)
    metrics = fix_negative_practice(metrics, report)
    metrics = fill_missing_engagement(metrics, report)

    known_ids = set(meta["student_id"])
    metrics = exclude_orphans(metrics, known_ids, "student_daily_metrics", report)
    notes = exclude_orphans(notes, known_ids, "facilitator_notes", report)

    return metrics, notes, meta, report
