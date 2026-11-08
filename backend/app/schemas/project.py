"""Project, chat, and task API models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskStatus = Literal[
    "queued",
    "clarification_needed",
    "running",
    "validating",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
]


class StudyContext(BaseModel):
    """Study defaults remembered on the project."""

    market: str | None = None
    audience: str | None = None
    objectives: list[str] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)
    store_traces: bool = False


class ProjectCreate(BaseModel):
    """Payload for creating a project."""

    name: str = Field(min_length=1, max_length=200)
    study_context: StudyContext = Field(default_factory=StudyContext)


class ProjectUpdate(BaseModel):
    """Partial project update."""

    name: str | None = None
    active_dataset_id: str | None = None
    default_weight_variable: str | None = None
    study_context: StudyContext | None = None


class ProjectOut(BaseModel):
    """Project returned to the client."""

    id: str
    name: str
    active_dataset_id: str | None = None
    default_weight_variable: str | None = None
    study_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ConversationOut(BaseModel):
    """Conversation summary."""

    id: str
    project_id: str
    title: str
    sdk_session_id: str
    created_at: datetime


class MessageIn(BaseModel):
    """A user turn."""

    content: str = Field(min_length=1)
    file_ids: list[str] = Field(default_factory=list)


class MessageOut(BaseModel):
    """A stored message."""

    id: str
    role: str
    content: str
    task_id: str | None = None
    sequence: int
    created_at: datetime


class TaskContract(BaseModel):
    """Typed work order produced before a specialist runs."""

    task_id: str
    project_id: str
    conversation_id: str
    intent: str
    specialist: str
    dataset_id: str | None = None
    input_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    user_request: str
    provided_fields: dict[str, Any] = Field(default_factory=dict)
    missing_required: list[str] = Field(default_factory=list)
    defaults_used: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    status: TaskStatus = "queued"


class TaskOut(BaseModel):
    """Task status for the client."""

    id: str
    status: TaskStatus
    contract: dict[str, Any]
    validation: dict[str, Any] | None = None
    error: str | None = None


class TaskEventOut(BaseModel):
    """One streamed or replayed task event."""

    sequence: int
    event_type: str
    payload: dict[str, Any]
