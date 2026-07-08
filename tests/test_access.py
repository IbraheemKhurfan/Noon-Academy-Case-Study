"""Role filtering: a facilitator must only ever see their assigned
students; an admin sees everyone. Uses an isolated in-memory SQLite DB —
not the app's real database — so this test never touches boon.db."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db import Base, Student, all_students, students_for_facilitator


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_students(session):
    session.add_all([
        Student(student_id="S1", student_name="A", campus_id="C1", facilitator_email="f1@x.com",
                grade=10, learning_track="Standard", target_score=80, parent_phone="+1", active=True),
        Student(student_id="S2", student_name="B", campus_id="C1", facilitator_email="f2@x.com",
                grade=10, learning_track="Standard", target_score=80, parent_phone="+1", active=True),
        Student(student_id="S3", student_name="C", campus_id="C1", facilitator_email="f1@x.com",
                grade=11, learning_track="Remedial", target_score=70, parent_phone="+1", active=True),
    ])
    session.commit()


def test_facilitator_sees_only_assigned_students():
    session = make_session()
    seed_students(session)
    result = students_for_facilitator(session, "f1@x.com")
    assert {s.student_id for s in result} == {"S1", "S3"}


def test_facilitator_does_not_see_other_facilitators_students():
    session = make_session()
    seed_students(session)
    result = students_for_facilitator(session, "f2@x.com")
    assert {s.student_id for s in result} == {"S2"}
    assert "S1" not in {s.student_id for s in result}


def test_admin_sees_all_students():
    session = make_session()
    seed_students(session)
    result = all_students(session)
    assert {s.student_id for s in result} == {"S1", "S2", "S3"}
