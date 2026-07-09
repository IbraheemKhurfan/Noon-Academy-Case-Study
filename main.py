"""Pipeline entrypoint: DATA -> DETECT -> PRIORITIZE -> RECOMMEND -> OUTPUTS.

Run directly (`python main.py`, or `make pipeline` / `make demo`) to do a
full run against the CSVs in DATA_DIR. app.py imports `recompute_all` from
this module and calls it after any facilitator action (new note, new
metric, completed intervention) so risk/priority/patterns always reflect
the latest data — the case study requires that a new note can change a
student's priority, so recompute has to be cheap and idempotent, not a
one-time batch job.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select

from src import actions as actions_mod
from src import data as data_mod
from src import features as features_mod
from src import llm as llm_mod
from src import outputs as outputs_mod
from src import patterns as patterns_mod
from src import reports as reports_mod
from src import scoring as scoring_mod
from src import validation as validation_mod
from src.config import SETTINGS, TARGET_COVERAGE
from src.db import (
    DailyMetric,
    FacilitatorNote,
    Intervention,
    RiskSnapshot,
    Student,
    User,
    Campus,
    hash_password,
    init_db,
    session_scope,
)

N_SAMPLE_MESSAGES = 10
N_SAMPLE_BRIEFS = 5
N_SAMPLE_PARENT_REPORTS = 20


# --- DB seeding from CSVs (idempotent upsert-by-natural-key) --------------

def seed_campuses_and_users(session, meta: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    existing_campuses = {c.campus_id for c in session.scalars(select(Campus))}
    for cid in sorted(meta["campus_id"].unique()):
        if cid not in existing_campuses:
            session.add(Campus(campus_id=cid, name=f"Campus {cid}"))

    existing_users = {u.email for u in session.scalars(select(User))}

    if SETTINGS.seed_admin_email not in existing_users:
        admin_password = SETTINGS.seed_admin_password or secrets.token_urlsafe(9)
        session.add(User(email=SETTINGS.seed_admin_email, password_hash=hash_password(admin_password),
                          display_name="Admin", role="admin", active=True))
        if not SETTINGS.seed_admin_password:
            notes.append(f"Generated admin password (SEED_ADMIN_PASSWORD not set): {admin_password}")

    facilitator_password = SETTINGS.seed_facilitator_password or secrets.token_urlsafe(9)
    new_facilitators = [e for e in sorted(meta["facilitator_email"].unique()) if e not in existing_users]
    for email in new_facilitators:
        name = email.split("@")[0].replace(".", " ").replace("_", " ").title()
        session.add(User(email=email, password_hash=hash_password(facilitator_password),
                          display_name=name, role="facilitator", active=True))
    if new_facilitators and not SETTINGS.seed_facilitator_password:
        notes.append(f"Generated facilitator password (SEED_FACILITATOR_PASSWORD not set): {facilitator_password}")
    return notes


def upsert_students(session, meta: pd.DataFrame) -> None:
    existing = {s.student_id: s for s in session.scalars(select(Student))}
    for _, row in meta.iterrows():
        s = existing.get(row["student_id"])
        if s is None:
            s = Student(student_id=row["student_id"])
            session.add(s)
        s.student_name = row["student_name"]
        s.campus_id = row["campus_id"]
        s.facilitator_email = row["facilitator_email"]
        s.grade = int(row["grade"])
        s.learning_track = row["learning_track"]
        s.target_score = float(row["target_score"])
        s.parent_phone = row["parent_phone"]
        s.active = True


def upsert_daily_metrics(session, metrics: pd.DataFrame) -> None:
    existing = {(m.student_id, m.date): m for m in session.scalars(select(DailyMetric))}
    for _, row in metrics.iterrows():
        key = (row["student_id"], row["date"])
        m = existing.get(key)
        if m is None:
            m = DailyMetric(student_id=row["student_id"], date=row["date"])
            session.add(m)
        m.attendance_min = None if pd.isna(row["session_attended_min"]) else float(row["session_attended_min"])
        m.practice_questions = None if pd.isna(row["practice_questions"]) else float(row["practice_questions"])
        m.quiz_score = None if pd.isna(row["last_quiz_score"]) else float(row["last_quiz_score"])


def upsert_notes(session, notes: pd.DataFrame) -> None:
    """Upserts note text/trust_status only — never touches ai_* fields here,
    so re-running the pipeline never throws away existing LLM analysis."""
    existing = {n.note_id: n for n in session.scalars(select(FacilitatorNote))}
    for _, row in notes.iterrows():
        n = existing.get(row["note_id"])
        if n is None:
            n = FacilitatorNote(note_id=row["note_id"])
            session.add(n)
        n.student_id = row["student_id"]
        n.facilitator_email = row["facilitator_email"]
        n.date = row["date"]
        n.note_text = row["note_text"]
        n.trust_status = row["trust_status"]


def seed_from_csv() -> tuple[dict, list[str]]:
    init_db()
    meta_raw = data_mod.load_student_metadata(SETTINGS.data_dir)
    metrics_raw = data_mod.load_daily_metrics(SETTINGS.data_dir)
    notes_raw = data_mod.load_facilitator_notes(SETTINGS.data_dir)

    result = validation_mod.run_validation(meta_raw, metrics_raw, notes_raw, SETTINGS.quiz1_date)
    row_counts = {"student_metadata": len(meta_raw), "daily_metrics": len(metrics_raw), "facilitator_notes": len(notes_raw)}
    quality_report = result.to_report_dict(row_counts)
    outputs_mod.write_json(SETTINGS.output_dir / "data_quality_report.json", quality_report)

    seed_notes: list[str] = []
    with session_scope() as session:
        seed_notes = seed_campuses_and_users(session, result.metadata)
        upsert_students(session, result.metadata)
        upsert_daily_metrics(session, result.metrics)
        upsert_notes(session, result.notes)

    return quality_report, seed_notes


# --- Live recompute: DB state -> features -> patterns -> risk -> actions -

def _analyze_pending_notes(session) -> list[dict]:
    students = {s.student_id: s for s in session.scalars(select(Student))}
    pending = list(session.scalars(
        select(FacilitatorNote).where(FacilitatorNote.trust_status == "trusted", FacilitatorNote.ai_summary.is_(None))
    ))
    logs = []
    for note in pending:
        student = students.get(note.student_id)
        context = {"student_id": note.student_id,
                   "grade": student.grade if student else None,
                   "learning_track": student.learning_track if student else None}
        result, log = llm_mod.analyze_note(note.note_id, note.note_text, context)
        note.ai_summary = result["summary"]
        note.ai_barrier = result["barrier_type"]
        note.ai_severity = result["severity"]
        note.ai_follow_up_needed = bool(result["follow_up_needed"])
        logs.append(log.to_dict())
    return logs


def _load_live_tables(session) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    meta = pd.DataFrame([{
        "student_id": s.student_id, "student_name": s.student_name, "campus_id": s.campus_id,
        "facilitator_email": s.facilitator_email, "grade": s.grade, "learning_track": s.learning_track,
        "target_score": s.target_score, "parent_phone": s.parent_phone,
    } for s in session.scalars(select(Student))])

    metrics = pd.DataFrame([{
        "student_id": m.student_id, "date": m.date, "session_attended_min": m.attendance_min,
        "practice_questions": m.practice_questions, "last_quiz_score": m.quiz_score,
    } for m in session.scalars(select(DailyMetric))])

    notes = pd.DataFrame([{
        "student_id": n.student_id, "note_id": n.note_id, "date": n.date, "trust_status": n.trust_status,
        "facilitator_email": n.facilitator_email, "note_text": n.note_text, "ai_summary": n.ai_summary,
        "ai_barrier": n.ai_barrier, "ai_severity": n.ai_severity, "ai_follow_up_needed": n.ai_follow_up_needed,
    } for n in session.scalars(select(FacilitatorNote))])

    interventions = pd.DataFrame([{
        "id": i.id, "student_id": i.student_id, "facilitator_email": i.facilitator_email,
        "action_type": i.action_type, "priority": i.priority, "due_date": i.due_date, "status": i.status,
        "outcome": i.outcome, "created_at": i.created_at, "completed_at": i.completed_at,
        "source": i.source, "facilitator_overridden": i.facilitator_overridden,
        "facilitator_note": i.facilitator_note,
    } for i in session.scalars(select(Intervention))])

    return meta, metrics, notes, interventions


def _upsert_risk_snapshots(session, risk_df: pd.DataFrame) -> None:
    as_of = SETTINGS.as_of_date
    session.query(RiskSnapshot).filter(RiskSnapshot.as_of_date == as_of).delete()
    for _, row in risk_df.iterrows():
        session.add(RiskSnapshot(
            student_id=row["student_id"], as_of_date=as_of, risk_score=row["risk_score"],
            priority_score=row["priority_score"], risk_level=row["risk_level"], confidence=row["confidence"],
            reason_codes=json.dumps(row["reason_codes"]),
            patterns=json.dumps(row["patterns"]),
            recommended_action=row["recommended_action"],
        ))


def _upsert_recommended_interventions(session, risk_df: pd.DataFrame) -> None:
    """Refreshes the one open (untouched-or-in-progress) *system* intervention
    per student. Deliberately does NOT spawn a new "recommended" row for a
    student who already has ANY system intervention on record — even a
    completed one — because recompute_all() runs after every single
    facilitator click (Start, Complete, message sent, ...). Keying only off
    "is it still open" meant that the instant a facilitator resolved
    something (completed/message_sent/booked — none of which count as
    "open"), the very next recompute silently created a fresh "recommended"
    duplicate, which made every action button look like it had no effect.

    Only rows with source="system" are considered here — a facilitator's own
    manually-logged actions (an ad-hoc call, a booked session, an edited
    reschedule) are never read or rewritten by this function, so the
    recommendation engine can never silently clobber something a human
    typed in. Same protection for a system row a facilitator explicitly
    edited (facilitator_overridden=True): its action_type/priority/due_date
    are frozen at whatever the facilitator set, permanently — only status
    changes (Start/Complete/...) still apply on top of it."""
    open_by_student: dict[str, Intervention] = {}
    has_any_by_student: set[str] = set()
    for iv in session.scalars(select(Intervention).where(Intervention.source == "system")):
        has_any_by_student.add(iv.student_id)
        if iv.status in outputs_mod.OPEN_STATUSES:
            open_by_student.setdefault(iv.student_id, iv)

    for _, row in risk_df.iterrows():
        if row["recommended_action"] == "MONITOR_ONLY":
            continue
        sid = row["student_id"]
        open_iv = open_by_student.get(sid)
        if open_iv is not None:
            if not open_iv.facilitator_overridden:
                open_iv.action_type = row["recommended_action"]
                open_iv.priority = row["risk_level"]
                open_iv.due_date = row["due_date"]
        elif sid not in has_any_by_student:
            session.add(Intervention(
                student_id=sid, facilitator_email=row["facilitator_email"],
                action_type=row["recommended_action"], priority=row["risk_level"],
                due_date=row["due_date"], status="recommended", source="system",
            ))


def recompute_all() -> dict:
    """The shared core: read current DB state, recompute features -> patterns
    -> risk -> priority -> recommended action, persist snapshots, return the
    resulting tables. Cheap enough (a few hundred students) to call after
    every single facilitator action."""
    init_db()

    with session_scope() as session:
        llm_logs = _analyze_pending_notes(session)

    with session_scope() as session:
        meta, metrics, notes, interventions = _load_live_tables(session)

    meta = validation_mod.flag_phone_column(meta)
    metrics = validation_mod.annotate_metric_flags(metrics, SETTINGS.quiz1_date)
    quality_flags = validation_mod.build_quality_flags(meta, metrics, notes)

    features_df = features_mod.build_features_table(
        meta, metrics, SETTINGS.quiz1_date, SETTINGS.quiz2_date, SETTINGS.as_of_date, quality_flags,
    )
    features_df = features_mod.attach_note_features(features_df, notes, SETTINGS.quiz1_date, SETTINGS.as_of_date)
    features_df = features_mod.attach_intervention_features(features_df, interventions)

    trusted_notes = notes[notes["trust_status"] == "trusted"]

    rows = []
    for f in features_df.to_dict(orient="records"):
        student_trusted_notes = trusted_notes[trusted_notes["student_id"] == f["student_id"]]
        trusted_note_analyses = [
            {"severity": r["ai_severity"] or "unknown", "follow_up_needed": bool(r["ai_follow_up_needed"])}
            for _, r in student_trusted_notes.iterrows() if r["ai_severity"] is not None
        ]
        detected_patterns = patterns_mod.detect_patterns(f)
        pattern_codes = [p["code"] for p in detected_patterns]
        score = scoring_mod.score_student(f, pattern_codes, trusted_note_analyses)
        action = actions_mod.recommend_action(f, detected_patterns, score["risk_level"], SETTINGS.as_of_date)

        rows.append({
            **f,
            **score,
            "pattern_codes": pattern_codes,
            "patterns": detected_patterns,
            "recommended_action": action["action_type"],
            "action_priority": action["priority"],
            "due_date": action["due_date"],
            "estimated_minutes": action["estimated_minutes"],
            "next_step": action["next_step"],
            "action_brief": action["brief"],
        })

    risk_df = pd.DataFrame(rows)

    with session_scope() as session:
        _upsert_risk_snapshots(session, risk_df)
        _upsert_recommended_interventions(session, risk_df)

    with session_scope() as session:
        _, _, notes_after, interventions_after = _load_live_tables(session)

    return {
        "risk_df": risk_df,
        "notes_df": notes_after,
        "interventions_df": interventions_after,
        "meta_df": meta,
        "metrics_df": metrics,
        "llm_logs": llm_logs,
    }


# --- Stats + sample generation for the full pipeline run ------------------

def _build_stats(risk_df: pd.DataFrame, quality_report: dict, interventions_df: pd.DataFrame,
                  llm_logs: list[dict]) -> dict:
    coverage = outputs_mod.coverage_metrics(risk_df, interventions_df, SETTINGS.as_of_date, TARGET_COVERAGE)
    risk_counts = risk_df["risk_level"].value_counts().to_dict()
    below_target = risk_df["below_target"].fillna(False)
    needing = risk_df[outputs_mod.needs_intervention_mask(risk_df)]
    post_quiz_activity_pct = (
        100 * needing["has_post_quiz1_activity"].mean() if len(needing) else 0.0
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_day": (SETTINGS.as_of_date - SETTINGS.quiz1_date).days + 10,
        "days_until_quiz2": SETTINGS.days_until_quiz2,
        "total_students": len(risk_df),
        "total_campuses": risk_df["campus_id"].nunique(),
        "total_facilitators": risk_df["facilitator_email"].nunique(),
        "below_target_count": int(below_target.sum()),
        "below_target_pct": 100 * below_target.mean() if len(risk_df) else 0.0,
        "post_quiz_activity_pct": post_quiz_activity_pct,
        "risk_counts": {k: int(v) for k, v in risk_counts.items()},
        "recommended_action_count": int((risk_df["recommended_action"] != "MONITOR_ONLY").sum()),
        "llm_success_count": sum(1 for l in llm_logs if l["status"] == "success"),
        "llm_fallback_count": sum(1 for l in llm_logs if l["status"] in ("fallback", "disabled")),
        "data_quality_issue_count": quality_report["total_issue_checks"],
        "students_with_quality_flags": quality_report["students_with_quality_flags"],
        **coverage,
    }


def _generate_llm_samples(risk_df: pd.DataFrame) -> list[dict]:
    """Exercises the messaging/brief LLM paths during the pipeline run so
    llm_messages.jsonl contains real generated content, not just note
    analyses. Capped to keep a from-scratch run fast and inexpensive."""
    logs = []
    top_priority = risk_df.sort_values("priority_score", ascending=False).head(N_SAMPLE_MESSAGES)
    for _, row in top_priority.iterrows():
        positive_fact = None
        if row.get("attendance_trend") is not None and row["attendance_trend"] >= 0:
            positive_fact = "لاحظنا التزامك بالحضور هذا الأسبوع"
        text, log = llm_mod.generate_motivational_message({
            "student_id": row["student_id"], "first_name": row["student_name"].split()[0],
            "positive_fact": positive_fact, "next_step": row["next_step"],
        })
        logs.append({**log.to_dict(), "content": text})

    parent_call_candidates = risk_df[risk_df["recommended_action"] == "PARENT_CALL"].sort_values(
        "priority_score", ascending=False).head(N_SAMPLE_BRIEFS)
    for _, row in parent_call_candidates.iterrows():
        brief, log = llm_mod.generate_parent_call_brief({
            "student_id": row["student_id"], "first_name": row["student_name"].split()[0],
            "concern": row["action_brief"], "supporting_data": "; ".join(row["reason_codes"]),
            "recommended_action": row["next_step"], "positive_fact": None,
        })
        logs.append({**log.to_dict(), "content": brief})
    return logs


def _generate_sample_parent_reports(risk_df: pd.DataFrame, metrics_df: pd.DataFrame) -> list[dict]:
    logs = []
    top = risk_df.sort_values("priority_score", ascending=False).head(N_SAMPLE_PARENT_REPORTS)
    for _, row in top.iterrows():
        peer_group_rows = risk_df[risk_df["peer_group"] == row["peer_group"]]
        peer_avgs = {
            "quiz": peer_group_rows["quiz1_score"].mean(),
            "attendance": peer_group_rows["recent_attendance"].mean(),
            "practice": peer_group_rows["recent_practice"].mean(),
        }
        student_metrics = metrics_df[metrics_df["student_id"] == row["student_id"]]
        trusted_summary = "; ".join(
            [n for n in [row.get("last_note_follow_up_needed") and "Follow-up still needed per latest note." or None] if n]
        ) or "See facilitator notes tab for detail."
        summary_text, log = llm_mod.generate_parent_report_summary({
            "student_id": row["student_id"], "first_name": row["student_name"].split()[0],
            "quiz1_score": row["quiz1_score"], "target_score": row["target_score"],
            "overall_status": reports_mod.overall_status_for(row["risk_level"], set(row["pattern_codes"])),
            "peer_quiz_avg": peer_avgs["quiz"], "peer_attendance_avg": peer_avgs["attendance"],
            "peer_practice_avg": peer_avgs["practice"],
        })
        logs.append({**log.to_dict()})
        ctx = reports_mod.assemble_parent_context(
            row.to_dict(), student_metrics, peer_avgs, trusted_summary, summary_text,
            datetime.now(timezone.utc).isoformat(),
        )
        html = reports_mod.build_parent_report_html(ctx)
        path = SETTINGS.output_dir / "parent_reports" / f"{row['student_id']}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html)
    return logs


def run_pipeline(generate_llm_samples: bool = True) -> dict:
    quality_report, seed_notes = seed_from_csv()
    for note in seed_notes:
        print(f"[seed] {note}")

    live = recompute_all()
    risk_df, notes_df, interventions_df = live["risk_df"], live["notes_df"], live["interventions_df"]
    llm_logs = list(live["llm_logs"])

    if generate_llm_samples:
        llm_logs += _generate_llm_samples(risk_df)
        llm_logs += _generate_sample_parent_reports(risk_df, live["metrics_df"])

    stats = _build_stats(risk_df, quality_report, interventions_df, llm_logs)

    out = SETTINGS.output_dir
    outputs_mod.write_csv(outputs_mod.build_risk_roster_df(risk_df), out / "student_risk_roster.csv")
    outputs_mod.write_csv(interventions_df, out / "intervention_actions.csv")
    outputs_mod.write_csv(reports_mod.build_pattern_summary_df(risk_df), out / "pattern_summary.csv")
    outputs_mod.write_jsonl(llm_logs, out / "llm_messages.jsonl")
    (out / "executive_summary.md").write_text(reports_mod.build_executive_summary_md(stats))
    (out / "facilitator_dashboard.html").write_text(reports_mod.build_facilitator_dashboard_html(stats, risk_df))

    output_paths = [
        "data_quality_report.json", "student_risk_roster.csv",
        "intervention_actions.csv", "pattern_summary.csv", "llm_messages.jsonl",
        "executive_summary.md", "facilitator_dashboard.html", "run_summary.json", "parent_reports/",
    ]
    outputs_mod.write_json(out / "run_summary.json", {
        "generated_at": stats["generated_at"],
        "config": {
            "data_dir": str(SETTINGS.data_dir), "output_dir": str(SETTINGS.output_dir),
            "as_of_date": str(SETTINGS.as_of_date), "quiz1_date": str(SETTINGS.quiz1_date),
            "quiz2_date": str(SETTINGS.quiz2_date), "llm_enabled": SETTINGS.llm_enabled,
            "openai_model": SETTINGS.openai_model, "notification_mode": SETTINGS.notification_mode,
        },
        "stats": stats,
        "output_files": output_paths,
    })

    outputs_mod.print_console_summary(stats, output_paths)
    return {"risk_df": risk_df, "stats": stats}


if __name__ == "__main__":
    run_pipeline()
