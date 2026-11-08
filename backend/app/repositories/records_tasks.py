"""Task rows and durable events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Task, TaskEvent
from app.util import new_id


def _now() -> datetime:
    """Return the current UTC time.

    Returns:
        Timezone-aware timestamp.
    """
    return datetime.now(timezone.utc)


class TaskRepository:
    """Task rows and durable events."""

    def __init__(self, db: Session) -> None:
        """Bind a session.

        Args:
            db: SQLAlchemy session.
        """
        self.db = db

    def create(self, project_id: str, conversation_id: str, contract: dict[str, Any]) -> Task:
        """Insert a queued task.

        Args:
            project_id: Project id.
            conversation_id: Conversation id.
            contract: Initial contract.

        Returns:
            Task.
        """
        task = Task(
            id=new_id(),
            project_id=project_id,
            conversation_id=conversation_id,
            status="queued",
            contract=contract,
            repair_count=0,
            created_at=_now(),
            updated_at=_now(),
        )
        self.db.add(task)
        self.db.flush()
        return task

    def get(self, task_id: str) -> Task:
        """Return a task.

        Args:
            task_id: Task id.

        Returns:
            Task.
        """
        row = self.db.get(Task, task_id)
        if row is None:
            raise AppError("Task not found", "not_found", 404)
        return row

    def add_event(self, task_id: str, event_type: str, payload: dict[str, Any]) -> TaskEvent:
        """Append a sequenced event.

        Args:
            task_id: Task id.
            event_type: Event name.
            payload: JSON payload. Do not put respondent text here.

        Returns:
            Event.
        """
        existing = list(self.db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id)))
        event = TaskEvent(
            id=new_id(),
            task_id=task_id,
            sequence=len(existing) + 1,
            event_type=event_type,
            payload=payload,
            created_at=_now(),
        )
        self.db.add(event)
        self.db.flush()
        return event

    def events(self, task_id: str) -> list[TaskEvent]:
        """Return events in order.

        Args:
            task_id: Task id.

        Returns:
            Events.
        """
        return list(
            self.db.scalars(
                select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.sequence)
            )
        )
