"""Pipeline entry point: CSV in, prioritized worklist out.

Run with `make demo` or `python main.py`. Every stage is a thin call into
`src/` so this file reads as the whole story end to end: ingest -> validate
-> features -> risk -> actions (+ LLM) -> outputs -> report.
"""

from __future__ import annotations

import pandas as pd

from src.config import settings
from src.actions import generate_actions
from src.features import build_features
from src.ingest import load_raw_data
from src.outputs import (
    write_data_quality_report,
    write_facilitator_worklists,
    write_intervention_actions,
    write_student_risk_roster,
)
from src.reporting import build_executive_summary_md, build_facilitator_dashboard_html, compute_summary
from src.risk import compute_risk


def run_pipeline() -> dict:
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    metrics, notes, meta, quality_report = load_raw_data(settings.data_dir)
    features_df = build_features(metrics, notes, meta, settings, quality_report)
    scored_df = compute_risk(features_df)

    llm_log_path = settings.output_dir / "llm_messages.jsonl"
    llm_log_path.write_text("", encoding="utf-8")  # fresh log each run
    final_df = generate_actions(scored_df, settings, llm_log_path)

    min_date = metrics["date"].min()
    current_date = min_date + pd.Timedelta(days=settings.current_day - 1)

    roster_path = write_student_risk_roster(final_df, settings.output_dir)
    worklist_path = write_facilitator_worklists(final_df, settings.output_dir)
    actions_path = write_intervention_actions(final_df, settings.output_dir, current_date)

    summary = compute_summary(final_df, settings)
    quality_path = write_data_quality_report(
        quality_report, {"students_scored": len(final_df)}, settings.output_dir
    )

    exec_summary_md = build_executive_summary_md(final_df, summary, quality_report.as_dict())
    (settings.output_dir / "executive_summary.md").write_text(exec_summary_md, encoding="utf-8")

    dashboard_html = build_facilitator_dashboard_html(summary)
    (settings.output_dir / "facilitator_dashboard.html").write_text(dashboard_html, encoding="utf-8")

    return {
        "summary": summary,
        "paths": {
            "student_risk_roster.csv": roster_path,
            "facilitator_worklists.csv": worklist_path,
            "intervention_actions.csv": actions_path,
            "data_quality_report.json": quality_path,
            "executive_summary.md": settings.output_dir / "executive_summary.md",
            "facilitator_dashboard.html": settings.output_dir / "facilitator_dashboard.html",
            "llm_messages.jsonl": llm_log_path,
        },
    }


def print_summary(result: dict) -> None:
    s = result["summary"]
    print("=" * 60)
    print("BOON ACADEMY INTERVENTION COMMAND CENTER — Day", s["current_day"])
    print("=" * 60)
    print(f"Total students:            {s['total_students']}")
    print(f"Campuses:                  {len(s['campuses'])}")
    print(f"Facilitators:              {len(s['facilitators'])}")
    print(f"Students below target:     {s['below_target_count']}")
    print(f"Baseline intervention rate:{s['baseline_intervention_rate']:.0%}")
    print(f"System coverage (human):   {s['system_human_touch_rate']:.0%}")
    print(f"System coverage (full):    {s['system_full_coverage_rate']:.0%}")
    print("-" * 60)
    print("Risk distribution:")
    for level in ("Critical", "High", "Medium", "Low"):
        print(f"  {level:<10} {s['risk_counts'][level]}")
    print("-" * 60)
    print(f"Recommended interventions: {s['total_students']} (every student has an assigned action)")
    print(f"  of which human-touch:    {s['human_touch_interventions']}")
    print(f"Estimated facilitator time:{s['total_estimated_minutes']} minutes")
    print("-" * 60)
    print("Output files:")
    for name, path in result["paths"].items():
        print(f"  {path}")
    print("=" * 60)
    print("Next step: streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    result = run_pipeline()
    print_summary(result)
