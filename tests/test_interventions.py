"""Coverage math: a recommendation is not an intervention, a generated
message is not an intervention, and a no-answer call is an attempt, not a
success (see src/outputs.py's module docstring for the reasoning)."""
from datetime import date

import pandas as pd

from src.outputs import coverage_metrics


def risk_df(n_needing=4):
    rows = []
    for i in range(n_needing):
        rows.append({"student_id": f"S{i}", "risk_level": "High", "below_target": True})
    return pd.DataFrame(rows)


def test_recommendation_alone_does_not_count_as_successful_interaction():
    interventions = pd.DataFrame([
        {"student_id": "S0", "status": "recommended", "due_date": date(2025, 10, 20)},
    ])
    result = coverage_metrics(risk_df(1), interventions, date(2025, 10, 14), 0.8)
    assert result["successful_interaction_rate"] == 0.0
    assert result["recommendation_coverage"] == 100.0  # recommendation coverage != success


def test_no_answer_counts_as_attempt_not_success():
    interventions = pd.DataFrame([
        {"student_id": "S0", "status": "no_answer", "due_date": date(2025, 10, 20)},
    ])
    result = coverage_metrics(risk_df(1), interventions, date(2025, 10, 14), 0.8)
    assert result["contact_attempt_rate"] == 100.0
    assert result["successful_interaction_rate"] == 0.0


def test_completed_intervention_counts_as_successful_and_completed():
    interventions = pd.DataFrame([
        {"student_id": "S0", "status": "completed", "due_date": date(2025, 10, 20)},
    ])
    result = coverage_metrics(risk_df(1), interventions, date(2025, 10, 14), 0.8)
    assert result["successful_interaction_rate"] == 100.0
    assert result["completed_intervention_rate"] == 100.0


def test_interaction_rate_calculated_correctly_across_mixed_students():
    interventions = pd.DataFrame([
        {"student_id": "S0", "status": "completed", "due_date": date(2025, 10, 20)},
        {"student_id": "S1", "status": "no_answer", "due_date": date(2025, 10, 20)},
        {"student_id": "S2", "status": "recommended", "due_date": date(2025, 10, 20)},
        # S3 has no intervention row at all.
    ])
    result = coverage_metrics(risk_df(4), interventions, date(2025, 10, 14), 0.8)
    assert result["students_needing_intervention"] == 4
    assert result["successful_interaction_rate"] == 25.0  # only S0 of 4
    assert result["contact_attempt_rate"] == 50.0  # S0 (completed) + S1 (no_answer)
    assert result["recommendation_coverage"] == 75.0  # S0, S1, S2 have a row; S3 doesn't


def test_overdue_intervention_rate():
    interventions = pd.DataFrame([
        {"student_id": "S0", "status": "recommended", "due_date": date(2025, 10, 10)},  # overdue
    ])
    result = coverage_metrics(risk_df(1), interventions, date(2025, 10, 14), 0.8)
    assert result["overdue_intervention_rate"] == 100.0
