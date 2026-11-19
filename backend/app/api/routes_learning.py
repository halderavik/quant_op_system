"""Ratings on artifacts and a read-only list of captured learning events."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.errors import AppError
from app.learning.capture import record_feedback
from app.models.tables import Artifact, LearningEvent, ProgrammingLesson

router = APIRouter()


class FeedbackIn(BaseModel):
    """A rating on the latest version of an artifact, with an optional reason."""

    rating: Literal["up", "down"]
    note: str = Field(default="", max_length=2000)


@router.post("/artifacts/{artifact_id}/feedback", status_code=201)
def add_feedback(artifact_id: str, body: FeedbackIn, db: Session = Depends(get_db)) -> dict:
    """Record a helpful or not helpful rating.

    Args:
        artifact_id: Artifact id.
        body: Rating and note.
        db: Session.

    Returns:
        The stored event id.
    """
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise AppError("Artifact not found", "not_found", 404)
    event = record_feedback(db, artifact, body.rating, body.note)
    db.commit()
    return {"id": event.id, "rating": body.rating}


@router.get("/projects/{project_id}/learning-events")
def list_learning_events(
    project_id: str, kind: str | None = None, limit: int = 200, db: Session = Depends(get_db)
) -> list[dict]:
    """List captured events for one project, newest first.

    Args:
        project_id: Project id.
        kind: Optional event kind filter.
        limit: Maximum rows, up to 1000.
        db: Session.

    Returns:
        Events.
    """
    query = select(LearningEvent).where(LearningEvent.project_id == project_id)
    if kind:
        query = query.where(LearningEvent.kind == kind)
    rows = db.scalars(
        query.order_by(LearningEvent.created_at.desc()).limit(max(1, min(limit, 1000)))
    ).all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "actor": row.actor,
            "artifact_id": row.artifact_id,
            "artifact_type": row.artifact_type,
            "from_version": row.from_version,
            "to_version": row.to_version,
            "instruction": row.instruction,
            "context": row.context,
            "payload": row.payload,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


class LessonStatusIn(BaseModel):
    """Turn a learned programming rule on or off."""

    status: Literal["active", "disabled"]


@router.get("/learning/programming-lessons")
def list_programming_lessons(limit: int = 200, db: Session = Depends(get_db)) -> list[dict]:
    """Rules learned from corrected survey logic, most-confirmed first.

    Args:
        limit: Maximum rows, up to 1000.
        db: Session.

    Returns:
        Lessons with their rule, example instruction, and how often they were confirmed.
    """
    rows = db.scalars(
        select(ProgrammingLesson)
        .order_by(ProgrammingLesson.support.desc(), ProgrammingLesson.updated_at.desc())
        .limit(max(1, min(limit, 1000)))
    ).all()
    return [
        {
            "id": row.id,
            "status": row.status,
            "stage": row.stage,
            "rule": row.rule,
            "field": row.field,
            "question_type": row.question_type,
            "example_instruction": row.example_instruction,
            "example_before": row.example_before,
            "example_after": row.example_after,
            "support": row.support,
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]


@router.patch("/learning/programming-lessons/{lesson_id}")
def set_programming_lesson(
    lesson_id: str, body: LessonStatusIn, db: Session = Depends(get_db)
) -> dict:
    """Switch a learned rule off (or back on) when it is wrong.

    Args:
        lesson_id: Lesson id.
        body: New status.
        db: Session.

    Returns:
        The lesson id and status.
    """
    lesson = db.get(ProgrammingLesson, lesson_id)
    if lesson is None:
        raise AppError("Lesson not found", "not_found", 404)
    lesson.status = body.status
    db.commit()
    return {"id": lesson.id, "status": lesson.status}


@router.get("/learning/quality-trend")
def learning_quality_trend(limit: int = 200, db: Session = Depends(get_db)) -> list[dict]:
    """Per-survey counts over time: parts re-read on import and corrections before programming.

    Args:
        limit: Most recent measurements to return, up to 1000.
        db: Session.

    Returns:
        Measurements, oldest first.
    """
    from app.learning.lessons import quality_trend

    return quality_trend(db, max(1, min(limit, 1000)))
