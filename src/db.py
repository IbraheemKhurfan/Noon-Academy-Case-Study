"""SQLite persistence layer: table models, session helpers, password hashing,
and the small set of query helpers the pipeline and the Streamlit app share.

Keeping every table access behind functions here (instead of scattering raw
SQLAlchemy queries through app.py) is what lets app.py stay a thin UI layer.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from src.config import SETTINGS


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)  # admin | facilitator
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    has_seen_onboarding: Mapped[bool] = mapped_column(Boolean, default=False)


class Campus(Base):
    __tablename__ = "campuses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campus_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    student_name: Mapped[str] = mapped_column(String)
    campus_id: Mapped[str] = mapped_column(String, index=True)
    facilitator_email: Mapped[str] = mapped_column(String, index=True)
    grade: Mapped[int] = mapped_column(Integer)
    learning_track: Mapped[str] = mapped_column(String)
    target_score: Mapped[float] = mapped_column(Float)
    parent_phone: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[date] = mapped_column(Date)
    attendance_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    practice_questions: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quiz_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class FacilitatorNote(Base):
    __tablename__ = "facilitator_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    facilitator_email: Mapped[str] = mapped_column(String)
    date: Mapped[date] = mapped_column(Date)
    note_text: Mapped[str] = mapped_column(Text)
    trust_status: Mapped[str] = mapped_column(String, default="trusted")
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_barrier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ai_severity: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ai_follow_up_needed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)


class RiskSnapshot(Base):
    __tablename__ = "risk_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    risk_score: Mapped[float] = mapped_column(Float)
    priority_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    reason_codes: Mapped[str] = mapped_column(Text)  # json list
    patterns: Mapped[str] = mapped_column(Text)  # json list
    recommended_action: Mapped[str] = mapped_column(String)


class Intervention(Base):
    __tablename__ = "interventions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    facilitator_email: Mapped[str] = mapped_column(String, index=True)
    action_type: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="recommended")
    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # "system" = owned by the rule-based recommendation engine — main.py's
    # _upsert_recommended_interventions() is free to refresh its action_type/
    # priority/due_date on every recompute. "manual" = a facilitator logged
    # this themselves (extra/self-initiated work, a booking, a rescheduled
    # call) and it must never be silently overwritten by the pipeline.
    source: Mapped[str] = mapped_column(String, default="system")
    # A facilitator's own edit to a priority card's displayed action/due
    # date/explanation — never the risk or priority SCORE itself, which
    # stays deterministic and non-editable by design. Once True, the
    # pipeline's auto-refresh (_upsert_recommended_interventions) leaves
    # action_type/priority/due_date alone for this row permanently.
    facilitator_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    facilitator_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AvailabilitySlot(Base):
    __tablename__ = "availability_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    facilitator_email: Mapped[str] = mapped_column(String, index=True)
    topic: Mapped[str] = mapped_column(String)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    # Not unique: a facilitator can offer several time options under one
    # shared link, so multiple slot rows intentionally carry the same token.
    booking_token: Mapped[str] = mapped_column(String, index=True)
    student_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open|booked|cancelled|completed
    # The single manual Intervention row this whole batch of time options is
    # tracked against — created once, up front, so a booking shows up in
    # Actions/My Day immediately rather than only after someone confirms a
    # time via the public link.
    intervention_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ChatSession(Base):
    """One saved AI-chat conversation ('tab') per facilitator/admin."""

    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_email: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String)  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Notification(Base):
    """Outbox for the dry-run parent-notification workflow (section 23)."""

    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[str] = mapped_column(String, index=True)
    facilitator_email: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)  # email|whatsapp
    sections: Mapped[str] = mapped_column(Text)  # json list of section keys
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft|simulated_sent|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = {"check_same_thread": False} if SETTINGS.database_url.startswith("sqlite") else {}
        _engine = create_engine(SETTINGS.database_url, connect_args=connect_args)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def _migrate_add_missing_columns() -> None:
    """`Base.metadata.create_all` only creates missing TABLES, never adds a
    column to a table that already exists — so a DB created before the
    `source` column existed would otherwise crash every query that touches
    it. Cheap enough (a handful of PRAGMA calls) to run on every startup."""
    engine = get_engine()
    with engine.begin() as conn:
        existing_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(interventions)").fetchall()}
        if existing_cols and "source" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE interventions ADD COLUMN source VARCHAR DEFAULT 'system'")
        if existing_cols and "facilitator_overridden" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE interventions ADD COLUMN facilitator_overridden BOOLEAN DEFAULT 0")
        if existing_cols and "facilitator_note" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE interventions ADD COLUMN facilitator_note TEXT")

        slot_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(availability_slots)").fetchall()}
        if slot_cols and "intervention_id" not in slot_cols:
            conn.exec_driver_sql("ALTER TABLE availability_slots ADD COLUMN intervention_id INTEGER")


def init_db() -> None:
    Base.metadata.create_all(get_engine())
    _migrate_add_missing_columns()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --- Password hashing (stdlib pbkdf2, no extra dependency needed) ---------

def hash_password(password: str, iterations: int = 200_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return f"pbkdf2${iterations}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, iterations, salt, digest_hex = encoded.split("$")
        expected = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return secrets.compare_digest(expected.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


# --- Query helpers shared by main.py (pipeline) and app.py (UI) ----------

def get_user_by_email(session: Session, email: str) -> Optional[User]:
    return session.scalar(select(User).where(User.email == email.strip().lower()))


def mark_onboarding_seen(email: str) -> None:
    with session_scope() as session:
        user = get_user_by_email(session, email)
        if user is not None:
            user.has_seen_onboarding = True


def all_students(session: Session) -> list[Student]:
    return list(session.scalars(select(Student).where(Student.active == True)))  # noqa: E712


def students_for_facilitator(session: Session, facilitator_email: str) -> list[Student]:
    return list(
        session.scalars(
            select(Student).where(Student.facilitator_email == facilitator_email, Student.active == True)  # noqa: E712
        )
    )


def get_student(session: Session, student_id: str) -> Optional[Student]:
    return session.scalar(select(Student).where(Student.student_id == student_id))


def daily_metrics_for(session: Session, student_id: str) -> list[DailyMetric]:
    return list(
        session.scalars(
            select(DailyMetric).where(DailyMetric.student_id == student_id).order_by(DailyMetric.date)
        )
    )


def notes_for(session: Session, student_id: str) -> list[FacilitatorNote]:
    return list(
        session.scalars(
            select(FacilitatorNote).where(FacilitatorNote.student_id == student_id).order_by(FacilitatorNote.date)
        )
    )


def latest_risk_snapshot(session: Session, student_id: str) -> Optional[RiskSnapshot]:
    return session.scalar(
        select(RiskSnapshot)
        .where(RiskSnapshot.student_id == student_id)
        .order_by(RiskSnapshot.as_of_date.desc(), RiskSnapshot.id.desc())
    )


def all_latest_risk_snapshots(session: Session) -> dict[str, RiskSnapshot]:
    latest: dict[str, RiskSnapshot] = {}
    for snap in session.scalars(select(RiskSnapshot).order_by(RiskSnapshot.id)):
        latest[snap.student_id] = snap
    return latest


def interventions_for(session: Session, student_id: str) -> list[Intervention]:
    return list(
        session.scalars(
            select(Intervention).where(Intervention.student_id == student_id).order_by(Intervention.created_at)
        )
    )


def interventions_for_facilitator(session: Session, facilitator_email: str) -> list[Intervention]:
    return list(
        session.scalars(
            select(Intervention)
            .where(Intervention.facilitator_email == facilitator_email)
            .order_by(Intervention.due_date)
        )
    )


def all_interventions(session: Session) -> list[Intervention]:
    return list(session.scalars(select(Intervention)))


def all_campuses(session: Session) -> list[Campus]:
    return list(session.scalars(select(Campus)))


def all_users(session: Session) -> list[User]:
    return list(session.scalars(select(User)))


def chat_sessions_for(session: Session, user_email: str) -> list[ChatSession]:
    return list(
        session.scalars(
            select(ChatSession).where(ChatSession.user_email == user_email).order_by(ChatSession.id.desc())
        )
    )


def chat_messages_for(session: Session, session_id: int) -> list[ChatMessage]:
    return list(
        session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
        )
    )
