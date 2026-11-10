"""HTTP routes for projects, chat, artifacts, files, and datasets."""

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.model_router import ModelRouter
from app.agents.orchestrator import Orchestrator
from app.api.deps import get_db
from app.api.routes_jobs import router as jobs_router
from app.api.routes_library import router as library_router
from app.errors import AppError
from app.repositories.records import (
    ProjectRepository,
    TaskRepository,
)
from app.sandbox.runner import docker_available
from app.schemas.project import MessageIn, ProjectCreate, ProjectUpdate

router = APIRouter()
router.include_router(library_router)
router.include_router(jobs_router)


@router.get("/artifacts/{artifact_id}/tables/{table_id}")
def crosstab_table(
    artifact_id: str, table_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Return one computed table for the panel.

    Args:
        artifact_id: Crosstab artifact id.
        table_id: Table id inside that book.
        request: Current request.
        db: Session.

    Returns:
        Columns and cells for that table.
    """
    from app.models import Artifact
    from app.repositories.records import ArtifactRepository
    from app.services.tabbook_store import read_stored_table

    revision = ArtifactRepository(db).latest(artifact_id)
    if revision is None:
        raise AppError("Artifact not found", "not_found", 404)
    content = revision.content or {}
    lines_rel = content.get("tables_relpath")
    index_rel = content.get("index_relpath")
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise AppError("Artifact not found", "not_found", 404)
    if lines_rel and index_rel:
        return read_stored_table(
            request.app.state.storage, artifact.project_id, str(lines_rel), str(index_rel), table_id
        )
    for table in content.get("tables") or []:
        if isinstance(table, dict) and table.get("table_id") == table_id and table.get("rows"):
            return table
    embedded = content.get("table")
    if isinstance(embedded, dict) and embedded.get("table_id") == table_id:
        return embedded
    raise AppError(
        "This book has no saved table grid. Generate the cross-tabs again.",
        "not_found",
        404,
    )


_TERMINAL = {"completed", "completed_with_warnings", "failed", "cancelled", "clarification_needed"}


@router.get("/health")
def health(request: Request) -> dict:
    """Report process health without revealing the API key.

    Args:
        request: Current request.

    Returns:
        Health payload.
    """
    db = request.app.state.session_factory()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    finally:
        db.close()
    settings = request.app.state.settings
    models = ModelRouter(settings).status()
    return {
        "status": "ok",
        "database": database,
        "llm": "available" if settings.llm_configured else "missing_key",
        "llm_message": models.get("reason"),
        "models": models.get("configured"),
        "sandbox": "docker" if docker_available() else "subprocess_fallback",
    }


@router.post("/models/probe")
def probe_models(request: Request) -> dict:
    """Check configured model ids against the account.

    Args:
        request: Current request.

    Returns:
        Probe result.
    """
    return ModelRouter(request.app.state.settings).probe()


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)) -> list[dict]:
    """List projects.

    Args:
        db: Session.

    Returns:
        Projects.
    """
    repo = ProjectRepository(db)
    payload = []
    for row in repo.list():
        item = _project(row)
        conversations = repo.conversations(row.id)
        if conversations:
            item["conversation_id"] = conversations[0].id
        payload.append(item)
    return payload


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)) -> dict:
    """Create a project and its first conversation.

    Args:
        body: Project payload.
        db: Session.

    Returns:
        Project and conversation id.
    """
    project = ProjectRepository(db).create(body.name, body.study_context.model_dump())
    conversation = ProjectRepository(db).conversations(project.id)[0]
    payload = _project(project)
    payload["conversation_id"] = conversation.id
    return payload


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)) -> dict:
    """Return one project.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        Project.
    """
    repo = ProjectRepository(db)
    item = _project(repo.get(project_id))
    conversations = repo.conversations(project_id)
    if conversations:
        item["conversation_id"] = conversations[0].id
    return item


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectUpdate, db: Session = Depends(get_db)) -> dict:
    """Update project defaults.

    Args:
        project_id: Project id.
        body: Partial update.
        db: Session.

    Returns:
        Project.
    """
    project = ProjectRepository(db).get(project_id)
    if body.name is not None:
        project.name = body.name
    if body.active_dataset_id is not None:
        project.active_dataset_id = body.active_dataset_id
    if body.default_weight_variable is not None:
        project.default_weight_variable = body.default_weight_variable
    if body.study_context is not None:
        project.study_context = body.study_context.model_dump()
    return _project(project)


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: str, request: Request, confirm: bool = False, db: Session = Depends(get_db)
) -> dict:
    """Delete a project and its files when ``confirm`` is true.

    Args:
        project_id: Project id.
        confirm: Must be true.
        request: Current request.
        db: Session.

    Returns:
        Acknowledgement.
    """
    if not confirm:
        raise AppError(
            "Pass confirm=true to delete the project and its local files.", "confirmation_required"
        )
    ProjectRepository(db).get(project_id)
    request.app.state.storage.delete_project(project_id)
    from sqlalchemy import delete

    from app.models import (
        Artifact,
        ArtifactRevision,
        Conversation,
        Dataset,
        Job,
        Message,
        Project,
        StoredFile,
        Task,
        TaskEvent,
    )

    conversation_ids = [row.id for row in ProjectRepository(db).conversations(project_id)]
    task_ids = [row.id for row in db.query(Task).filter(Task.project_id == project_id)]
    artifact_ids = [row.id for row in db.query(Artifact).filter(Artifact.project_id == project_id)]
    if task_ids:
        db.execute(delete(TaskEvent).where(TaskEvent.task_id.in_(task_ids)))
    if conversation_ids:
        db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
    db.execute(delete(Task).where(Task.project_id == project_id))
    if artifact_ids:
        db.execute(delete(ArtifactRevision).where(ArtifactRevision.artifact_id.in_(artifact_ids)))
    db.execute(delete(Artifact).where(Artifact.project_id == project_id))
    db.execute(delete(Dataset).where(Dataset.project_id == project_id))
    db.execute(delete(StoredFile).where(StoredFile.project_id == project_id))
    db.execute(delete(Job).where(Job.project_id == project_id))
    db.execute(delete(Conversation).where(Conversation.project_id == project_id))
    db.execute(delete(Project).where(Project.id == project_id))
    return {"deleted": project_id}


@router.get("/projects/{project_id}/conversations")
def list_conversations(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """List conversations.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        Conversations.
    """
    rows = ProjectRepository(db).conversations(project_id)
    return [
        {"id": row.id, "title": row.title, "sdk_session_id": row.sdk_session_id} for row in rows
    ]


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Return persisted messages.

    Args:
        conversation_id: Conversation id.
        db: Session.

    Returns:
        Messages.
    """
    rows = ProjectRepository(db).messages(conversation_id)
    return [
        {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "task_id": row.task_id,
            "sequence": row.sequence,
        }
        for row in rows
    ]


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def post_message(
    conversation_id: str,
    body: MessageIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Store a user turn and run the task.

    Args:
        conversation_id: Conversation id.
        body: Message.
        request: Current request.
        db: Session.

    Returns:
        Task id.
    """
    projects = ProjectRepository(db)
    conversation = projects.conversation(conversation_id)
    projects.add_message(conversation_id, "user", body.content)
    task = TaskRepository(db).create(
        conversation.project_id,
        conversation_id,
        {"user_request": body.content, "file_ids": body.file_ids},
    )
    db.commit()
    settings = request.app.state.settings
    orchestrator = Orchestrator(
        settings, request.app.state.session_factory, request.app.state.storage
    )
    if settings.run_tasks_inline:
        await orchestrator.run(task.id)
    else:
        asyncio.create_task(orchestrator.run(task.id))
    return {"task_id": task.id}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)) -> dict:
    """Return task status and the stage messages recorded so far.

    Args:
        task_id: Task id.
        db: Session.

    Returns:
        Task, including events in sequence.
    """
    tasks = TaskRepository(db)
    task = tasks.get(task_id)
    return {
        "id": task.id,
        "status": task.status,
        "contract": task.contract,
        "validation": task.validation,
        "error": task.error,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "message": str((event.payload or {}).get("message") or ""),
            }
            for event in tasks.events(task_id)
        ],
    }


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, db: Session = Depends(get_db)) -> dict:
    """Mark a task cancelled.

    Args:
        task_id: Task id.
        db: Session.

    Returns:
        Task status.
    """
    task = TaskRepository(db).get(task_id)
    if task.status not in _TERMINAL:
        task.status = "cancelled"
    return {"id": task.id, "status": task.status}


@router.get("/tasks/{task_id}/events")
async def stream_events(task_id: str, request: Request) -> StreamingResponse:
    """Replay task events as server-sent events.

    Args:
        task_id: Task id.
        request: Current request.

    Returns:
        Event stream.
    """

    async def generate():
        """Yield stored events until the task is terminal.

        Yields:
            SSE frames.
        """
        seen = 0
        for _ in range(40):
            db = request.app.state.session_factory()
            try:
                events = TaskRepository(db).events(task_id)
                status = TaskRepository(db).get(task_id).status
            finally:
                db.close()
            for event in events:
                if event.sequence <= seen:
                    continue
                seen = event.sequence
                payload = json.dumps(
                    {
                        "event": event.event_type,
                        "payload": event.payload,
                        "sequence": event.sequence,
                    }
                )
                yield f"id: {event.sequence}\ndata: {payload}\n\n"
            if status in _TERMINAL and seen:
                break
            await asyncio.sleep(0.05)

    return StreamingResponse(generate(), media_type="text/event-stream")


def _project(row: object) -> dict:
    """Serialize a project.

    Args:
        row: Project row.

    Returns:
        Dictionary.
    """
    return {
        "id": row.id,
        "name": row.name,
        "active_dataset_id": row.active_dataset_id,
        "default_weight_variable": row.default_weight_variable,
        "study_context": row.study_context,
    }
