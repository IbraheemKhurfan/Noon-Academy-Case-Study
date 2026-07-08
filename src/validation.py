"""Data-quality checks. Runs before any feature/risk logic touches the data.

Guiding rule for this whole module: flag problems, never silently "fix" them
by guessing a value. A pipeline that crashes on dirty data is unusable in
production, but one that quietly invents numbers is worse — it hides the
problem instead of surfacing it to a human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

ATTENDANCE_MIN = 0
ATTENDANCE_MAX = 90
# A genuinely intense practice day tops out well under this. Anything beyond
# it is kept (not deleted/clipped) but flagged as an anomaly — it may be a
# real cramming burst or a data-entry error, and only downstream context
# (the CRAMMING_PATTERN detector) can tell the two apart.
EXTREME_PRACTICE_THRESHOLD = 60
PHONE_PATTERN = re.compile(r"^\+?\d[\d\-\s]{6,}$")

REQUIRED_META_COLS = [
    "student_id", "student_name", "campus_id", "facilitator_email",
    "grade", "parent_phone", "target_score", "learning_track",
]
REQUIRED_METRIC_COLS = [
    "student_id", "date", "session_attended_min", "practice_questions", "last_quiz_score",
]
REQUIRED_NOTE_COLS = ["note_id", "student_id", "facilitator_email", "date", "note_text"]


@dataclass
class Issue:
    check: str
    severity: str  # info | warning | error
    count: int
    description: str
    sample_student_ids: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    metadata: pd.DataFrame
    metrics: pd.DataFrame
    notes: pd.DataFrame
    issues: list[Issue]
    quality_flags: dict[str, list[str]]  # student_id -> list of flag codes

    def to_report_dict(self, row_counts: dict[str, int]) -> dict[str, Any]:
        return {
            "row_counts": row_counts,
            "total_issue_checks": len(self.issues),
            "total_flagged_rows": sum(i.count for i in self.issues),
            "students_with_quality_flags": sum(1 for flags in self.quality_flags.values() if flags),
            "checks": [
                {
                    "check": i.check,
                    "severity": i.severity,
                    "count": i.count,
                    "description": i.description,
                    "sample_student_ids": i.sample_student_ids[:10],
                }
                for i in self.issues
            ],
        }


def _sample_ids(series: pd.Series, n: int = 10) -> list[str]:
    return sorted(set(series.dropna().astype(str).tolist()))[:n]


def _check_required_columns(df: pd.DataFrame, required: list[str], label: str, issues: list[Issue]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        issues.append(Issue(f"{label}_missing_columns", "error", len(missing),
                             f"{label} is missing required columns: {missing}"))


def flag_phone_column(meta: pd.DataFrame) -> pd.DataFrame:
    meta = meta.copy()
    meta["phone_invalid"] = ~meta["parent_phone"].astype(str).str.match(PHONE_PATTERN)
    return meta


def annotate_metric_flags(metrics: pd.DataFrame, quiz1_date: date) -> pd.DataFrame:
    """Adds the same anomaly-flag columns validate_metrics computes, reusable
    by the live app recompute path (DB-sourced data) so a manually-entered or
    CSV-uploaded row gets the same scrutiny as the original CSV import."""
    metrics = metrics.copy()
    metrics["attendance_invalid"] = metrics["session_attended_min"].notna() & (
        (metrics["session_attended_min"] < ATTENDANCE_MIN) | (metrics["session_attended_min"] > ATTENDANCE_MAX)
    )
    metrics["practice_invalid"] = metrics["practice_questions"] < 0
    metrics["practice_extreme"] = metrics["practice_questions"] > EXTREME_PRACTICE_THRESHOLD
    metrics["quiz_score_date_anomaly"] = metrics["last_quiz_score"].notna() & (metrics["date"] < quiz1_date)
    return metrics


def validate_metadata(meta: pd.DataFrame, issues: list[Issue]) -> pd.DataFrame:
    _check_required_columns(meta, REQUIRED_META_COLS, "student_metadata", issues)
    meta = meta.copy()

    missing_id = meta["student_id"].isna() | (meta["student_id"].astype(str).str.strip() == "")
    if missing_id.any():
        issues.append(Issue("missing_student_id", "error", int(missing_id.sum()),
                             "Rows in student_metadata with no student_id (dropped from downstream analysis)."))
    meta = meta[~missing_id]

    dup_mask = meta["student_id"].duplicated(keep=False)
    if dup_mask.any():
        issues.append(Issue("duplicate_student_metadata", "warning", int(dup_mask.sum()),
                             "student_id appears more than once in student_metadata.",
                             _sample_ids(meta.loc[dup_mask, "student_id"])))
        meta = meta.drop_duplicates(subset="student_id", keep="first")

    meta = flag_phone_column(meta)
    if meta["phone_invalid"].any():
        issues.append(Issue("invalid_parent_phone", "warning", int(meta["phone_invalid"].sum()),
                             "parent_phone does not look like a phone number (e.g. contains an email address).",
                             _sample_ids(meta.loc[meta["phone_invalid"], "student_id"])))
    return meta


def validate_metrics(metrics: pd.DataFrame, valid_student_ids: set[str], quiz1_date: date,
                      issues: list[Issue]) -> pd.DataFrame:
    _check_required_columns(metrics, REQUIRED_METRIC_COLS, "student_daily_metrics", issues)
    metrics = metrics.copy()

    bad_dates = metrics["date"].isna()
    if bad_dates.any():
        issues.append(Issue("unparseable_date", "error", int(bad_dates.sum()),
                             "student_daily_metrics rows with a date that could not be parsed (dropped)."))
    metrics = metrics[~bad_dates]

    orphan = ~metrics["student_id"].isin(valid_student_ids)
    if orphan.any():
        issues.append(Issue("orphan_metrics", "warning", int(orphan.sum()),
                             "Daily metric rows reference a student_id not present in student_metadata.",
                             _sample_ids(metrics.loc[orphan, "student_id"])))

    # Missing attendance is left as NaN, never coerced to 0 — a student who
    # was not recorded is not the same as a student who attended 0 minutes,
    # and silently zeroing it would fabricate a worse (or better) signal
    # than we actually have.
    missing_attendance = metrics["session_attended_min"].isna()
    if missing_attendance.any():
        issues.append(Issue("missing_attendance", "info", int(missing_attendance.sum()),
                             "session_attended_min is missing (kept as missing, not treated as zero).",
                             _sample_ids(metrics.loc[missing_attendance, "student_id"])))

    metrics = annotate_metric_flags(metrics, quiz1_date)

    if metrics["attendance_invalid"].any():
        issues.append(Issue("attendance_out_of_range", "warning", int(metrics["attendance_invalid"].sum()),
                             f"session_attended_min outside the valid 0-{ATTENDANCE_MAX} minute range.",
                             _sample_ids(metrics.loc[metrics["attendance_invalid"], "student_id"])))

    if metrics["practice_invalid"].any():
        issues.append(Issue("negative_practice", "warning", int(metrics["practice_invalid"].sum()),
                             "practice_questions is negative.",
                             _sample_ids(metrics.loc[metrics["practice_invalid"], "student_id"])))

    if metrics["practice_extreme"].any():
        issues.append(Issue("extreme_practice_value", "info", int(metrics["practice_extreme"].sum()),
                             f"practice_questions above {EXTREME_PRACTICE_THRESHOLD} in a single day — kept, "
                             "flagged as an anomaly (may be a real cramming burst).",
                             _sample_ids(metrics.loc[metrics["practice_extreme"], "student_id"])))

    # A quiz score should only appear on/after Quiz 1's date. One recorded
    # earlier is a real anomaly in this dataset, not a hypothetical.
    if metrics["quiz_score_date_anomaly"].any():
        issues.append(Issue("unexpected_quiz_score_date", "warning", int(metrics["quiz_score_date_anomaly"].sum()),
                             f"A quiz score is recorded before Quiz 1's date ({quiz1_date}).",
                             _sample_ids(metrics.loc[metrics["quiz_score_date_anomaly"], "student_id"])))

    return metrics


def validate_notes(notes: pd.DataFrame, meta: pd.DataFrame, issues: list[Issue]) -> pd.DataFrame:
    _check_required_columns(notes, REQUIRED_NOTE_COLS, "facilitator_notes", issues)
    notes = notes.copy()

    dup_note_id = notes["note_id"].duplicated(keep=False)
    if dup_note_id.any():
        issues.append(Issue("duplicate_note_id", "warning", int(dup_note_id.sum()),
                             "note_id is not unique."))

    valid_ids = set(meta["student_id"])
    orphan = ~notes["student_id"].isin(valid_ids)
    if orphan.any():
        issues.append(Issue("orphan_notes", "warning", int(orphan.sum()),
                             "Note references a student_id not present in student_metadata (excluded downstream).",
                             _sample_ids(notes.loc[orphan, "student_id"])))

    owner_map = meta.set_index("student_id")["facilitator_email"]
    notes["expected_facilitator"] = notes["student_id"].map(owner_map)
    mismatch = notes["facilitator_email"] != notes["expected_facilitator"]

    notes["trust_status"] = "trusted"
    notes.loc[orphan, "trust_status"] = "orphan"
    notes.loc[mismatch & ~orphan, "trust_status"] = "unverified_ownership"

    n_mismatch = int((mismatch & ~orphan).sum())
    if n_mismatch:
        issues.append(Issue("facilitator_ownership_mismatch", "warning", n_mismatch,
                             "Note's facilitator_email does not match the student's assigned facilitator in "
                             "student_metadata. Retained, but excluded from parent communication and "
                             "qualitative risk contribution until trusted.",
                             _sample_ids(notes.loc[mismatch & ~orphan, "student_id"])))
    return notes


def build_quality_flags(meta: pd.DataFrame, metrics: pd.DataFrame, notes: pd.DataFrame) -> dict[str, list[str]]:
    """Roll every per-row flag up into a per-student list, consumed by
    features.py (confidence) and patterns.py (DATA_QUALITY_RISK)."""
    flags: dict[str, list[str]] = {sid: [] for sid in meta["student_id"]}

    def add(student_ids, code: str) -> None:
        for sid in student_ids:
            if sid in flags:
                flags[sid].append(code)

    add(meta.loc[meta["phone_invalid"], "student_id"], "INVALID_PHONE")
    add(metrics.loc[metrics["session_attended_min"].isna(), "student_id"].unique(), "MISSING_ATTENDANCE")
    add(metrics.loc[metrics["attendance_invalid"], "student_id"].unique(), "ATTENDANCE_OUT_OF_RANGE")
    add(metrics.loc[metrics["practice_invalid"], "student_id"].unique(), "NEGATIVE_PRACTICE")
    add(metrics.loc[metrics["practice_extreme"], "student_id"].unique(), "EXTREME_PRACTICE")
    add(metrics.loc[metrics["quiz_score_date_anomaly"], "student_id"].unique(), "QUIZ_SCORE_DATE_ANOMALY")
    add(notes.loc[notes["trust_status"] == "unverified_ownership", "student_id"].unique(), "NOTE_OWNERSHIP_CONFLICT")
    return flags


def run_validation(meta: pd.DataFrame, metrics: pd.DataFrame, notes: pd.DataFrame, quiz1_date: date) -> ValidationResult:
    issues: list[Issue] = []
    clean_meta = validate_metadata(meta, issues)
    clean_metrics = validate_metrics(metrics, set(clean_meta["student_id"]), quiz1_date, issues)
    clean_notes = validate_notes(notes, clean_meta, issues)
    quality_flags = build_quality_flags(clean_meta, clean_metrics, clean_notes)
    return ValidationResult(clean_meta, clean_metrics, clean_notes, issues, quality_flags)
