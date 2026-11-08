"""Shared schema types."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class WarningItem(BaseModel):
    """A short caveat attached to a result."""

    severity: Literal["error", "warning", "info"] = "warning"
    message: str
    action: str | None = None


class Provenance(BaseModel):
    """Source versions used to produce an output."""

    dataset_id: str | None = None
    dataset_sha256: str | None = None
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    model_id: str | None = None
    run_id: str | None = None


class SpecialistResult(BaseModel):
    """Structured result returned by a specialist to the orchestrator."""

    result_status: Literal["completed", "completed_with_warnings", "clarification_needed", "failed"]
    summary: str
    warnings: list[WarningItem] = Field(default_factory=list)
    clarification: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    artifacts: list["ArtifactDraft"] = Field(default_factory=list)


class ArtifactDraft(BaseModel):
    """An artifact payload waiting to be stored as a new revision."""

    type: str
    name: str
    content_schema: str
    content: dict[str, Any]
    derived_from: list[dict[str, Any]] = Field(default_factory=list)
    validation_status: str = "pending"
    created_by: str = "agent"
    artifact_id: str | None = None


class ValidationCheck(BaseModel):
    """One reproducible validator check."""

    id: str
    type: Literal["deterministic", "semantic"] = "deterministic"
    status: Literal["passed", "failed", "skipped"]
    severity: Literal["error", "warning", "info"] = "error"
    details: str


class ValidationReport(BaseModel):
    """Validator gate attached to a task and artifact hash."""

    task_id: str | None = None
    status: Literal["passed", "passed_with_warnings", "failed"]
    checks: list[ValidationCheck] = Field(default_factory=list)
    required_repairs: list[str] = Field(default_factory=list)
    validated_artifact_versions: list[dict[str, Any]] = Field(default_factory=list)
    content_hashes: list[str] = Field(default_factory=list)


SpecialistResult.model_rebuild()
