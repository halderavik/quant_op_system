"""Ratings on artifacts and a read-only list of captured learning events."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.errors import AppError
from app.learning.capture import record_feedback
from app.models.tables import Artifact, LearningEvent

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
