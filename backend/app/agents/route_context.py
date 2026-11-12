"""Project metadata the orchestrator reads before choosing a specialist."""

from typing import Any

from sqlalchemy.orm import Session

from app.errors import AppError
from app.repositories.records import ArtifactRepository, TaskRepository

# Reason: the router needs to know which deliverables exist. It does not need their contents.
SNAPSHOT_TYPES = (
    "questionnaire",
    "tabspec",
    "crosstab",
    "analysis",
    "report",
    "codeframe",
    "coding",
    "cleaning",
    "decipher_survey",
    "sample_purchase",
)
_NAME_CAP = 40
_REPLY_CAP = 500
_OBJECTIVE_CAP = 8
_OBJECTIVE_LEN = 200


def artifact_versions(artifacts: ArtifactRepository, project_id: str) -> dict[str, int]:
    """Return the latest version of each snapshot artifact type.

    Args:
        artifacts: Artifact repository.
        project_id: Project id.

    Returns:
        Type to version. Types with no revision are omitted. Content is not read.
    """
    versions: dict[str, int] = {}
    for kind in SNAPSHOT_TYPES:
        row = artifacts.latest_of_type(project_id, kind)
        if row is not None:
            versions[kind] = row.version
    return versions


def previous_turn(db: Session, previous: object | None) -> tuple[str, str]:
    """Return the intent and status of the task behind the previous reply.

    Args:
        db: Session.
        previous: Previous assistant message, or None.

    Returns:
        Intent and status. Both are empty when that reply has no task.
    """
    task_id = getattr(previous, "task_id", None)
    if not task_id:
        return "", ""
    try:
        prior = TaskRepository(db).get(str(task_id))
    except AppError:
        return "", ""
    contract = prior.contract or {}
    return str(contract.get("intent") or ""), str(prior.status or "")


def study_objectives(study_context: dict[str, Any] | None) -> list[str]:
    """Return the stored study objectives, shortened for the route prompt.

    Args:
        study_context: Project study context.

    Returns:
        Up to eight objective strings.
    """
    raw = (study_context or {}).get("objectives") or []
    if not isinstance(raw, list):
        return []
    objectives: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        objectives.append(text[:_OBJECTIVE_LEN])
        if len(objectives) == _OBJECTIVE_CAP:
            break
    return objectives


def project_snapshot(
    *,
    artifact_versions_by_type: dict[str, int],
    dataset_active: bool,
    variable_names: list[str],
    previous_reply: str,
    previous_intent: str,
    previous_status: str,
    objectives: list[str],
) -> dict[str, Any]:
    """Assemble the metadata packet sent to the route model.

    Args:
        artifact_versions_by_type: Latest version for each saved artifact type.
        dataset_active: Whether a dataset is active.
        variable_names: Variable names on that dataset.
        previous_reply: Previous assistant message.
        previous_intent: Intent of the previous task.
        previous_status: Status of the previous task.
        objectives: Study objectives already stored on the project.

    Returns:
        JSON-ready snapshot. It has no respondent rows and no artifact bodies.
    """
    names = [str(name) for name in variable_names]
    return {
        "artifacts": {
            kind: version
            for kind, version in artifact_versions_by_type.items()
            if kind in SNAPSHOT_TYPES
        },
        "dataset_active": dataset_active,
        "variable_count": len(names),
        "variable_names": names[:_NAME_CAP],
        "previous_reply": previous_reply.strip()[:_REPLY_CAP],
        "previous_intent": previous_intent,
        "previous_status": previous_status,
        "objectives": objectives[:_OBJECTIVE_CAP],
    }
