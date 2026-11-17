"""Keep the report plan current in the background, without the user asking.

- A questionnaire draft or edit redrafts the plan quietly (no chat message).
- Decipher programming marks the questionnaire final.
- New data starts the data stage as a visible chat task, because it cleans data.

Nothing here runs unless the project already has, or now gets, a questionnaire,
and a failure never affects the work that triggered it.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories.records import ArtifactRepository, ProjectRepository, TaskRepository
from app.services.storage import Storage

logger = logging.getLogger(__name__)
DATA_INTENT = "report_plan_data"


async def quiet_refresh(
    settings: Settings, session_factory: Any, storage: Storage, project_id: str, stage: str = ""
) -> None:
    """Redraft the plan with its own session; errors are logged only."""
    from app.services.report_plan_run import refresh_plan

    db: Session = session_factory()
    try:
        await refresh_plan(db, settings, project_id, stage=stage, storage=storage)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Background report plan refresh failed for %s", project_id, exc_info=True)
    finally:
        db.close()


def schedule_refresh(
    settings: Settings, session_factory: Any, storage: Storage, project_id: str, stage: str = ""
) -> Any:
    """Start a quiet refresh. Inline mode (tests) returns the coroutine to await."""
    job = quiet_refresh(settings, session_factory, storage, project_id, stage)
    if settings.run_tasks_inline:
        return job
    asyncio.create_task(job)
    return None


async def schedule_data_stage(
    settings: Settings, session_factory: Any, storage: Storage, db: Session, project_id: str
) -> str | None:
    """Queue the data stage as a chat task when the project has a report plan.

    Returns:
        The task id, or None when there is no plan to update.
    """
    if ArtifactRepository(db).latest_of_type(project_id, "report_plan") is None:
        return None
    conversations = ProjectRepository(db).conversations(project_id)
    if not conversations:
        return None
    conversation = sorted(conversations, key=lambda c: c.updated_at)[-1]
    task = TaskRepository(db).create(
        project_id,
        conversation.id,
        {
            "user_request": "New data arrived: clean it and update the report plan.",
            "forced_intent": DATA_INTENT,
        },
    )
    db.commit()
    from app.agents.orchestrator import Orchestrator

    orchestrator = Orchestrator(settings, session_factory, storage)
    if settings.run_tasks_inline:
        await orchestrator.run(task.id)
    else:
        asyncio.create_task(orchestrator.run(task.id))
    return task.id
