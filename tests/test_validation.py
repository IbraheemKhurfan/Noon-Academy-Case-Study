"""Validation must flag dirty data without crashing and without silently
inventing values (see src/validation.py for the reasoning)."""
from datetime import date

import pandas as pd

from src.validation import run_validation

QUIZ1 = date(2025, 10, 10)


def _meta(rows):
    return pd.DataFrame(rows)


def _metrics(rows):
    return pd.DataFrame(rows)


def _notes(rows):
    return pd.DataFrame(rows, columns=["note_id", "student_id", "facilitator_email", "date", "note_text"])


def base_meta():
    return _meta([
        {"student_id": "S1", "student_name": "A", "campus_id": "C1", "facilitator_email": "f1@x.com",
         "grade": 10, "parent_phone": "+966501111111", "target_score": 80, "learning_track": "Standard"},
        {"student_id": "S2", "student_name": "B", "campus_id": "C1", "facilitator_email": "f1@x.com",
         "grade": 10, "parent_phone": "not-a-phone@email.com", "target_score": 80, "learning_track": "Standard"},
    ])


def test_missing_attendance_remains_missing_not_zero():
    meta = base_meta()
    metrics = _metrics([
        {"student_id": "S1", "date": date(2025, 10, 1), "session_attended_min": None,
         "practice_questions": 5, "last_quiz_score": None},
        {"student_id": "S1", "date": date(2025, 10, 2), "session_attended_min": 60,
         "practice_questions": 5, "last_quiz_score": None},
    ])
    notes = _notes([])
    result = run_validation(meta, metrics, notes, QUIZ1)

    missing_row = result.metrics[result.metrics["date"] == date(2025, 10, 1)].iloc[0]
    assert pd.isna(missing_row["session_attended_min"])
    assert missing_row["session_attended_min"] != 0
    assert any(i.check == "missing_attendance" and i.count == 1 for i in result.issues)


def test_invalid_phone_is_flagged():
    meta = base_meta()
    metrics = _metrics([{"student_id": "S1", "date": date(2025, 10, 1), "session_attended_min": 60,
                          "practice_questions": 5, "last_quiz_score": None}])
    result = run_validation(meta, metrics, _notes([]), QUIZ1)

    s2 = result.metadata[result.metadata["student_id"] == "S2"].iloc[0]
    assert s2["phone_invalid"] is True or bool(s2["phone_invalid"]) is True
    assert any(i.check == "invalid_parent_phone" for i in result.issues)


def test_negative_practice_is_flagged():
    meta = base_meta()
    metrics = _metrics([
        {"student_id": "S1", "date": date(2025, 10, 1), "session_attended_min": 60,
         "practice_questions": -5, "last_quiz_score": None},
    ])
    result = run_validation(meta, metrics, _notes([]), QUIZ1)
    row = result.metrics.iloc[0]
    assert row["practice_invalid"] == True  # noqa: E712 — value is retained, only flagged
    assert row["practice_questions"] == -5
    assert any(i.check == "negative_practice" for i in result.issues)


def test_extreme_practice_value_is_retained_and_flagged():
    meta = base_meta()
    metrics = _metrics([
        {"student_id": "S1", "date": date(2025, 10, 1), "session_attended_min": 60,
         "practice_questions": 120, "last_quiz_score": None},
    ])
    result = run_validation(meta, metrics, _notes([]), QUIZ1)
    row = result.metrics.iloc[0]
    assert row["practice_questions"] == 120  # kept, not clipped
    assert row["practice_extreme"] == True  # noqa: E712
    assert any(i.check == "extreme_practice_value" for i in result.issues)


def test_orphan_record_does_not_crash_pipeline():
    meta = base_meta()
    metrics = _metrics([
        {"student_id": "S1", "date": date(2025, 10, 1), "session_attended_min": 60,
         "practice_questions": 5, "last_quiz_score": None},
        {"student_id": "S_GHOST", "date": date(2025, 10, 1), "session_attended_min": 60,
         "practice_questions": 5, "last_quiz_score": None},
    ])
    notes = _notes([("N1", "S_GHOST2", "f1@x.com", date(2025, 10, 1), "orphan note")])
    result = run_validation(meta, metrics, notes, QUIZ1)  # must not raise

    assert any(i.check == "orphan_metrics" for i in result.issues)
    assert any(i.check == "orphan_notes" for i in result.issues)
    orphan_note = result.notes[result.notes["student_id"] == "S_GHOST2"].iloc[0]
    assert orphan_note["trust_status"] == "orphan"


def test_facilitator_ownership_mismatch_is_flagged_but_retained():
    meta = base_meta()
    metrics = _metrics([{"student_id": "S1", "date": date(2025, 10, 1), "session_attended_min": 60,
                          "practice_questions": 5, "last_quiz_score": None}])
    notes = _notes([("N1", "S1", "someone_else@x.com", date(2025, 10, 11), "mismatched note")])
    result = run_validation(meta, metrics, notes, QUIZ1)

    assert len(result.notes) == 1  # retained, not dropped
    assert result.notes.iloc[0]["trust_status"] == "unverified_ownership"
    assert any(i.check == "facilitator_ownership_mismatch" for i in result.issues)
