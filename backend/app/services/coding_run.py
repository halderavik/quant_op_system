"""Open-end coding job. Only selected response text is sent to the model."""

from collections.abc import Callable
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.agents.coding_agent import code_batch
from app.config import Settings
from app.engines.coding_export import export_coding_sav, export_coding_workbook
from app.engines.invariants import summarize, validate_export
from app.errors import AppError
from app.repositories.records import ArtifactRepository, ProjectRepository
from app.schemas.coding import Codeframe, CodingAssignment, CodingReport
from app.schemas.common import ValidationCheck
from app.services.documents import aggregate_saved_coding
from app.services.execute import _active_dataset, load_frame
from app.services.storage import Storage
from app.services.stored_files import _write_export

_BATCH = 20
_DISCLOSURE = (
    "Only the selected response text was sent to the model, with surrogate row ids. "
    "Respondent ids stayed in the local file."
)


async def run_open_end_coding(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    conversation_id: str,
    fields: dict[str, Any],
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Code one open-end column against an approved codeframe.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings.
        project_id: Project id.
        conversation_id: Conversation id, used as the model session.
        fields: Response column, respondent id, and optional weight.
        on_stage: Optional callback for a real stage message. It is not a model trace.

    Returns:
        Summary payload. Unknown code ids are removed before frequencies are saved.
    """
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    response_variable = str(fields.get("response_variable") or "")
    respondent_variable = str(fields.get("respondent_id_variable") or "respondent_id")
    _require_columns(frame, response_variable, respondent_variable)
    codeframe = _approved_codeframe(db, project_id)
    identity, texts, existing, artifact_id = _load_rows(
        db, project_id, frame, codeframe, response_variable, respondent_variable
    )
    pending = [
        position
        for position in range(len(frame))
        if position not in {row.source_row_id for row in existing}
    ]
    pending = [
        position for position in pending if not _blank(texts[position], codeframe.placeholders)
    ]
    blanks = _blank_rows(frame, texts, identity, existing, codeframe)
    existing = existing + blanks
    session_id = ProjectRepository(db).conversation(conversation_id).sdk_session_id
    weights = _weights(frame, fields, respondent_variable)
    sent_to_model = False
    if pending and on_stage is not None:
        on_stage("Classifying")
    for start in range(0, len(pending), _BATCH):
        chunk = pending[start : start + _BATCH]
        prompt = _prompt(chunk, texts)
        merged, _report = await code_batch(
            settings, codeframe, prompt, session_id, existing=existing
        )
        existing = _restore_local_fields(merged, identity, texts)
        report, existing = aggregate_saved_coding(codeframe, existing, weights)
        artifact_id = _persist(
            db, project_id, codeframe, existing, report, artifact_id, file_id=None
        )
        db.commit()
        sent_to_model = True
    report, existing = aggregate_saved_coding(codeframe, existing, weights)
    file_id = _export(db, storage, project_id, frame, codeframe, existing, report)
    artifact_id = _persist(db, project_id, codeframe, existing, report, artifact_id, file_id)
    gate = summarize(_checks(db, existing, report, storage, file_id))
    status = "completed" if gate.status == "passed" else "failed"
    disclosure = _DISCLOSURE if sent_to_model else "No response text was sent to the model."
    summary = (
        f"Coded {report.substantive_n} substantive responses. "
        f"{report.nonsubstantive_n} blank or placeholder rows were excluded from sentiment. {disclosure}"
    )
    if status != "completed":
        summary = "Coding did not pass validation. " + summary
    return {
        "summary": summary,
        "status": status,
        "artifact_id": artifact_id,
        "validation": gate.model_dump(mode="json"),
        "warnings": report.warnings,
    }


def _require_columns(frame: pd.DataFrame, response_variable: str, respondent_variable: str) -> None:
    """Reject a coding request that does not name dataset columns.

    Args:
        frame: Active dataset.
        response_variable: Open-end column.
        respondent_variable: Respondent id column.

    Raises:
        AppError: When a column was not selected or is absent.
    """
    if not response_variable:
        raise AppError(
            "Select the open-end column and approve a codeframe before coding. "
            "Example: code the open-end column comment using respondent id respondent_id.",
            "clarification_needed",
        )
    if response_variable not in frame.columns:
        raise AppError(
            f"`{response_variable}` is not in the active dataset.", "clarification_needed"
        )
    if respondent_variable not in frame.columns:
        raise AppError(
            f"`{respondent_variable}` is not in the active dataset. Name the respondent id column.",
            "clarification_needed",
        )


def _approved_codeframe(db: Session, project_id: str) -> Codeframe:
    """Load the latest codeframe artifact.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        Codeframe.

    Raises:
        AppError: When the user has not approved a frame.
    """
    revision = ArtifactRepository(db).latest_of_type(project_id, "codeframe")
    if revision is None:
        raise AppError(
            "Approve a codeframe before coding. I will not invent categories.",
            "clarification_needed",
        )
    payload = revision.content
    if "codeframe" in payload and "codes" not in payload:
        payload = payload["codeframe"]
    return Codeframe.model_validate(payload)


def _load_rows(
    db: Session,
    project_id: str,
    frame: pd.DataFrame,
    codeframe: Codeframe,
    response_variable: str,
    respondent_variable: str,
) -> tuple[dict[int, str], dict[int, str], list[CodingAssignment], str | None]:
    """Read checkpointed assignments and the local text for every row.

    Args:
        db: Session.
        project_id: Project id.
        frame: Dataset.
        codeframe: Approved frame.
        response_variable: Open-end column.
        respondent_variable: Respondent id column.

    Returns:
        Identity map, text map, prior assignments, and artifact id.
    """
    identity: dict[int, str] = {}
    texts: dict[int, str] = {}
    for position in range(len(frame)):
        raw_text = frame.iloc[position][response_variable]
        texts[position] = "" if pd.isna(raw_text) else str(raw_text)
        identity[position] = str(frame.iloc[position][respondent_variable])
    revision = ArtifactRepository(db).latest_of_type(project_id, "coding")
    if revision is None or revision.content.get("codeframe_id") != codeframe.codeframe_id:
        return identity, texts, [], None
    rows = [
        CodingAssignment.model_validate(item) for item in revision.content.get("assignments", [])
    ]
    return identity, texts, rows, revision.artifact_id


def _blank_rows(
    frame: pd.DataFrame,
    texts: dict[int, str],
    identity: dict[int, str],
    existing: list[CodingAssignment],
    codeframe: Codeframe,
) -> list[CodingAssignment]:
    """Create local assignments for blank rows so they are never sent to the model.

    Args:
        frame: Dataset.
        texts: Response text by row position.
        identity: Respondent id by row position.
        existing: Rows already checkpointed.
        codeframe: Approved frame.

    Returns:
        New blank assignments.
    """
    seen = {row.source_row_id for row in existing}
    rows: list[CodingAssignment] = []
    for position in range(len(frame)):
        if position in seen or not _blank(texts[position], codeframe.placeholders):
            continue
        rows.append(
            CodingAssignment(
                respondent_id=identity[position],
                source_row_id=position,
                response_text=texts[position],
                assigned_code_ids=[],
                sentiment=None,
                substantive=False,
            )
        )
    return rows


def _blank(text: str, placeholders: list[str]) -> bool:
    """Return whether text is a configured non-answer.

    Args:
        text: Response text.
        placeholders: Placeholder strings.

    Returns:
        True when the row should stay local.
    """
    return text.strip().lower() in {item.lower() for item in placeholders}


def _prompt(positions: list[int], texts: dict[int, str]) -> str:
    """Build a batch prompt that contains surrogate ids and response text only.

    Args:
        positions: Row positions in this batch.
        texts: Response text by position.

    Returns:
        Prompt text.
    """
    lines = [
        "Code these responses. Echo source_row_id exactly.",
        "Set respondent_id to that same integer as text. Do not add rows.",
        "source_row_id\tresponse",
    ]
    for position in positions:
        safe = texts[position].replace("\t", " ").replace("\n", " ")
        lines.append(f"{position}\t{safe}")
    return "\n".join(lines)


def _restore_local_fields(
    rows: list[CodingAssignment],
    identity: dict[int, str],
    texts: dict[int, str],
) -> list[CodingAssignment]:
    """Put local respondent ids and source text back onto model rows.

    Args:
        rows: Merged assignments.
        identity: Respondent id by source row.
        texts: Original response text.

    Returns:
        Rows whose source id belongs to this dataset.
    """
    restored: list[CodingAssignment] = []
    for row in rows:
        if row.source_row_id not in identity:
            continue
        update = row.model_copy(deep=True)
        update.respondent_id = identity[row.source_row_id]
        update.response_text = texts[row.source_row_id]
        restored.append(update)
    return restored


def _weights(
    frame: pd.DataFrame, fields: dict[str, Any], respondent_variable: str
) -> dict[str, float] | None:
    """Build a weight map when the request names a weight column.

    Args:
        frame: Dataset.
        fields: Contract fields.
        respondent_variable: Respondent id column.

    Returns:
        Weights by respondent id, or None.
    """
    weight_name = fields.get("weight_variable")
    if not weight_name or weight_name not in frame.columns:
        return None
    weights: dict[str, float] = {}
    for position in range(len(frame)):
        value = frame.iloc[position][weight_name]
        if pd.isna(value):
            continue
        weights[str(frame.iloc[position][respondent_variable])] = float(value)
    return weights


def _persist(
    db: Session,
    project_id: str,
    codeframe: Codeframe,
    rows: list[CodingAssignment],
    report: CodingReport,
    artifact_id: str | None,
    file_id: str | None,
) -> str:
    """Save the coding revision.

    Args:
        db: Session.
        project_id: Project id.
        codeframe: Approved frame.
        rows: Assignments.
        report: Frequency report.
        artifact_id: Existing artifact id.
        file_id: Export file id.

    Returns:
        Artifact id.
    """
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="coding",
        name=f"Coding {codeframe.response_variable}",
        content={
            "codeframe_id": codeframe.codeframe_id,
            "response_variable": codeframe.response_variable,
            "assignments": [row.model_dump(mode="json") for row in rows],
            "report": report.model_dump(mode="json"),
            "export_file_id": file_id,
            "disclosure": _DISCLOSURE,
        },
        content_schema="coding/1",
        created_by="coding",
        artifact_id=artifact_id,
        validation_status="pending",
    )
    return revision.artifact_id


def _export(
    db: Session,
    storage: Storage,
    project_id: str,
    frame: pd.DataFrame,
    codeframe: Codeframe,
    rows: list[CodingAssignment],
    report: CodingReport,
) -> str:
    """Write the Excel coding book and a labelled SPSS copy.

    Args:
        db: Session.
        storage: Storage.
        project_id: Project id.
        frame: Source data.
        codeframe: Codeframe.
        rows: Assignments.
        report: Frequencies.

    Returns:
        Excel file id.
    """
    file_id = _write_export(
        db,
        storage,
        project_id,
        "coding.xlsx",
        export_coding_workbook(codeframe, rows, report),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    sav_path = storage.resolve(project_id, "exports/coding.sav")
    sav_path.parent.mkdir(parents=True, exist_ok=True)
    export_coding_sav(frame, codeframe, rows, str(sav_path))
    return file_id


def _checks(
    db: Session,
    rows: list[CodingAssignment],
    report: CodingReport,
    storage: Storage,
    file_id: str,
) -> list[ValidationCheck]:
    """Check that frequencies reconcile to the saved rows and the export exists.

    Args:
        db: Session.
        rows: Assignments.
        report: Frequency report.
        storage: Storage.
        file_id: Excel file id.

    Returns:
        Validator checks.
    """
    from app.repositories.records import FileRepository

    accounted = report.substantive_n + report.nonsubstantive_n
    percent_ok = all(
        item.pct_of_respondents is None or 0 <= item.pct_of_respondents <= 100.0001
        for item in report.frequencies
    )
    stored = FileRepository(db).get(file_id)
    path = storage.resolve(stored.project_id, stored.storage_relpath)
    return [
        ValidationCheck(
            id="coding_row_count",
            status="passed" if accounted == len(rows) else "failed",
            details=f"{accounted} accounted vs {len(rows)} saved",
        ),
        ValidationCheck(
            id="coding_percent_bounds",
            status="passed" if percent_ok else "failed",
            details="Code percentages stay within 0 to 100",
        ),
        validate_export(path),
    ]
