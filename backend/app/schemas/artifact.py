"""Artifact revision and semantic patch models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RevisionCreate(BaseModel):
    """A full content write with an optimistic version guard."""

    content: dict[str, Any]
    expected_version: int | None = None
    name: str | None = None
    created_by: str = "user"


class SemanticPatch(BaseModel):
    """A small edit applied to the latest canonical JSON."""

    expected_version: int
    op: str = Field(description="replace, add, remove, or set_question")
    path: str | None = None
    question_id: str | None = None
    value: Any = None
    created_by: str = "user"


class RevisionOut(BaseModel):
    """One immutable artifact revision."""

    artifact_id: str
    type: str
    name: str
    version: int
    parent_version: int | None = None
    content_schema: str
    content: dict[str, Any]
    derived_from: list[dict[str, Any]] = Field(default_factory=list)
    stale: bool
    validation_status: str
    content_hash: str
    created_by: str
    created_at: datetime


class ArtifactOut(BaseModel):
    """Artifact identity plus its latest revision, when one exists."""

    id: str
    project_id: str
    type: str
    name: str
    latest: RevisionOut | None = None
