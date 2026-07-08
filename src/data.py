"""Raw CSV ingest. Reads the three source files from DATA_DIR and normalizes
column names only — no validation or business logic happens here, that is
src/validation.py's job so the two concerns stay separately testable."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# A few reasonable variants are accepted for the quiz score column so the
# pipeline does not break on a harmless header rename.
QUIZ_SCORE_ALIASES = ["last_quiz_score", "quiz1_score", "quiz_score", "quiz1", "score"]
ATTENDANCE_ALIASES = ["session_attended_min", "attendance_min", "attended_min"]


def _first_present(columns: list[str], aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in columns:
            return alias
    return None


def load_daily_metrics(data_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(data_dir / "student_daily_metrics.csv", dtype={"student_id": str})
    quiz_col = _first_present(list(df.columns), QUIZ_SCORE_ALIASES)
    attendance_col = _first_present(list(df.columns), ATTENDANCE_ALIASES)
    if quiz_col and quiz_col != "last_quiz_score":
        df = df.rename(columns={quiz_col: "last_quiz_score"})
    if attendance_col and attendance_col != "session_attended_min":
        df = df.rename(columns={attendance_col: "session_attended_min"})
    if "last_quiz_score" not in df.columns:
        df["last_quiz_score"] = pd.NA
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


def load_student_metadata(data_dir: Path) -> pd.DataFrame:
    return pd.read_csv(data_dir / "student_metadata.csv", dtype={"student_id": str, "campus_id": str})


def load_facilitator_notes(data_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(data_dir / "facilitator_notes.csv", dtype={"student_id": str})
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df
