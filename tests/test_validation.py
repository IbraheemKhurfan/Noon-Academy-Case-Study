"""Tests for the messy-data handling in src/validate.py.

The pipeline's core promise is that it never crashes on dirty operational
data — these tests exercise the repair functions directly with synthetic
frames that mimic the kinds of problems a real campus export has (missing
attendance, negative practice counts, duplicate metadata rows).
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
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_missing_attendance_is_filled_with_zero_and_reported():
    df = pd.DataFrame({"session_attended_min": [80.0, None, 45.0], "practice_questions": [10, 5, 0]})
    report = QualityReport()

    result = fill_missing_engagement(df, report)

    assert result["session_attended_min"].isna().sum() == 0
    assert result.loc[1, "session_attended_min"] == 0
    assert any(i.check == "missing_attendance_filled_zero" and i.count == 1 for i in report.issues)


def test_negative_practice_questions_are_zeroed_and_reported():
    df = pd.DataFrame({"practice_questions": [10, -5, 0]})
    report = QualityReport()

    result = fix_negative_practice(df, report)

    assert (result["practice_questions"] >= 0).all()
    assert result.loc[1, "practice_questions"] == 0
    assert any(i.check == "negative_practice_questions" and i.count == 1 for i in report.issues)


def test_attendance_is_clipped_to_the_90_minute_session_window():
    df = pd.DataFrame({"session_attended_min": [-10, 45, 150]})
    report = QualityReport()

    result = clip_attendance(df, report)

    assert result["session_attended_min"].tolist() == [0, 45, 90]
    assert any(i.check == "attendance_out_of_range" and i.count == 2 for i in report.issues)


def test_duplicate_metadata_rows_are_deduped_and_reported():
    df = pd.DataFrame(
        {
            "student_id": ["S1", "S1", "S2"],
            "student_name": ["First Entry", "Duplicate Entry", "Other Student"],
        }
    )
    report = QualityReport()

    result = dedupe_metadata(df, report)

    assert len(result) == 2
    assert result.loc[result["student_id"] == "S1", "student_name"].iloc[0] == "First Entry"
    assert any(i.check == "metadata_duplicate_student_id" for i in report.issues)


def test_orphan_rows_without_metadata_are_excluded_and_reported():
    df = pd.DataFrame({"student_id": ["S1", "S99"], "value": [1, 2]})
    report = QualityReport()

    result = exclude_orphans(df, known_student_ids={"S1"}, name="test_source", report=report)

    assert result["student_id"].tolist() == ["S1"]
    assert any(i.check == "test_source_orphan_rows_excluded" and i.count == 1 for i in report.issues)


def test_no_hardcoded_local_filesystem_paths_in_source():
    """All I/O must be driven by DATA_DIR/OUTPUT_DIR env vars (see
    src/config.py) — never a machine-specific absolute path baked into the
    pipeline. This guards against a regression like `Path("/Users/...")`
    sneaking into ingest/outputs code."""
    suspicious = re.compile(r"[\"'](/Users/|/home/|/tmp/|[A-Za-z]:\\\\)")
    source_files = list((REPO_ROOT / "src").glob("*.py")) + [
        REPO_ROOT / "main.py",
        REPO_ROOT / "app.py",
    ]

    offenders = []
    for path in source_files:
        text = path.read_text(encoding="utf-8")
        if suspicious.search(text):
            offenders.append(path.name)

    assert not offenders, f"Hardcoded local paths found in: {offenders}"
