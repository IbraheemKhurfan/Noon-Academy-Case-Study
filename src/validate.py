"""Data-quality checks and repairs.

Design decision: this pipeline must never crash on messy operational data —
a facilitator worklist that fails to generate on Day 14 is worse than one
built on imperfect data. Every function here either repairs a value with a
documented, conservative default (e.g. missing attendance -> 0, which is the
worst-case assumption and therefore fails safe toward "flag this student")
or records the problem in `issues` so it surfaces in
`outputs/data_quality_report.json` instead of failing silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Session length in minutes; used to clip clearly-impossible attendance values.
MAX_SESSION_MINUTES = 90


@dataclass
class QualityIssue:
    check: str
    severity: str  # "info" | "warning" | "error"
    count: int
    detail: str


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)

    def add(self, check: str, severity: str, count: int, detail: str) -> None:
        # Zero-count issues aren't worth reporting — keeps the report signal-only.
        if count > 0:
            self.issues.append(QualityIssue(check, severity, count, detail))

    def as_dict(self) -> dict:
        return {
            "total_issues": len(self.issues),
            "issues": [
                {
                    "check": i.check,
                    "severity": i.severity,
                    "count": i.count,
                    "detail": i.detail,
                }
                for i in self.issues
            ],
        }


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase/snake-case every column name so downstream code can rely on
    one naming convention regardless of how the source CSV was authored."""
    df = df.copy()
    df.columns = [
        str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns
    ]
    return df


def require_columns(
    df: pd.DataFrame, required: set[str], name: str, report: QualityReport
) -> None:
    missing = required - set(df.columns)
    if missing:
        report.add(
            check=f"{name}_missing_columns",
            severity="error",
            count=len(missing),
            detail=f"{name} is missing required columns: {sorted(missing)}",
        )


def parse_dates(
    df: pd.DataFrame, col: str, name: str, report: QualityReport
) -> pd.DataFrame:
    """Parse a date column, dropping unparseable rows rather than crashing."""
    df = df.copy()
    parsed = pd.to_datetime(df[col], errors="coerce")
    bad = parsed.isna() & df[col].notna()
    if bad.any():
        report.add(
            check=f"{name}_unparseable_dates",
            severity="warning",
            count=int(bad.sum()),
            detail=f"{name}.{col} had values that could not be parsed as dates; those rows were dropped",
        )
    df[col] = parsed
    return df[parsed.notna()]


def require_student_id(
    df: pd.DataFrame, name: str, report: QualityReport
) -> pd.DataFrame:
    """Drop rows with a null/blank student_id — they can't be attributed to anyone."""
    missing = df["student_id"].isna() | (df["student_id"].astype(str).str.strip() == "")
    if missing.any():
        report.add(
            check=f"{name}_missing_student_id",
            severity="error",
            count=int(missing.sum()),
            detail=f"{name} had rows with no student_id; those rows were dropped",
        )
    return df[~missing]


def dedupe_metadata(df: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    """student_metadata.csv must have one row per student. Keep the first
    occurrence and report the rest so a roster is never silently doubled."""
    dupe_mask = df["student_id"].duplicated(keep="first")
    if dupe_mask.any():
        report.add(
            check="metadata_duplicate_student_id",
            severity="warning",
            count=int(dupe_mask.sum()),
            detail="student_metadata.csv had duplicate student_id rows; kept the first occurrence of each",
        )
    return df[~dupe_mask]


def clip_attendance(df: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    """Attendance must fall within a single 90-minute session. Values outside
    [0, 90] are almost certainly data-entry errors, so we clip rather than
    drop — the row still carries a usable (if approximate) signal."""
    df = df.copy()
    col = df["session_attended_min"]
    out_of_range = (col < 0) | (col > MAX_SESSION_MINUTES)
    if out_of_range.any():
        report.add(
            check="attendance_out_of_range",
            severity="warning",
            count=int(out_of_range.sum()),
            detail=f"session_attended_min had values outside [0, {MAX_SESSION_MINUTES}]; clipped to range",
        )
    df["session_attended_min"] = col.clip(lower=0, upper=MAX_SESSION_MINUTES)
    return df


def fix_negative_practice(df: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    """A negative question count is impossible; treat it as a logging error and zero it."""
    df = df.copy()
    col = df["practice_questions"]
    negative = col < 0
    if negative.any():
        report.add(
            check="negative_practice_questions",
            severity="warning",
            count=int(negative.sum()),
            detail="practice_questions had negative values; set to 0",
        )
    df["practice_questions"] = col.clip(lower=0)
    return df


def fill_missing_engagement(df: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    """Missing attendance/practice rows are filled with 0 for risk scoring —
    a blank day for a struggling student should read as "did not engage",
    not be silently excluded, since that would understate risk."""
    df = df.copy()
    missing_attendance = df["session_attended_min"].isna()
    if missing_attendance.any():
        report.add(
            check="missing_attendance_filled_zero",
            severity="info",
            count=int(missing_attendance.sum()),
            detail="session_attended_min was missing; filled with 0 for risk scoring",
        )
    df["session_attended_min"] = df["session_attended_min"].fillna(0)

    missing_practice = df["practice_questions"].isna()
    if missing_practice.any():
        report.add(
            check="missing_practice_filled_zero",
            severity="info",
            count=int(missing_practice.sum()),
            detail="practice_questions was missing; filled with 0 for risk scoring",
        )
    df["practice_questions"] = df["practice_questions"].fillna(0)
    return df


def exclude_orphans(
    df: pd.DataFrame, known_student_ids: set[str], name: str, report: QualityReport
) -> pd.DataFrame:
    """Rows referencing a student_id absent from metadata can't be joined
    into the roster (no facilitator, campus, or target to act on) — report
    and drop them rather than producing an incomplete roster row."""
    orphan_mask = ~df["student_id"].isin(known_student_ids)
    if orphan_mask.any():
        report.add(
            check=f"{name}_orphan_rows_excluded",
            severity="warning",
            count=int(orphan_mask.sum()),
            detail=f"{name} had rows for student_id values not present in student_metadata.csv; excluded from roster",
        )
    return df[~orphan_mask]
