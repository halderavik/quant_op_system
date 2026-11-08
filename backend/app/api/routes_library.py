"""Artifact, file, dataset, and questionnaire routes."""

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.engines.decipher import compile_decipher
from app.engines.decipher_preview import step_preview
from app.engines.flow import validate_questionnaire
from app.errors import AppError
from app.repositories.records import (
    ArtifactRepository,
    DatasetRepository,
    FileRepository,
    ProjectRepository,
)
from app.schemas.artifact import RevisionCreate, SemanticPatch
from app.schemas.preview import PreviewRequest
from app.schemas.questionnaire import Questionnaire
from app.services.documents import export_questionnaire_file, save_questionnaire
from app.services.execute import ingest_spss, load_frame, validation_for_report_artifact
from app.services.patch import apply_semantic_patch
from app.services.revisions import prepare_revision
from app.services.storage import Storage
from app.util import new_id, sha256_bytes

router = APIRouter()


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """List artifacts with their latest revision.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        Artifacts.
    """
    repo = ArtifactRepository(db)
    payload = []
    for artifact in repo.list_project(project_id):
        latest = repo.latest(artifact.id)
        payload.append(_artifact(artifact, latest))
    return payload


@router.post("/projects/{project_id}/artifacts", status_code=201)
def create_artifact(project_id: str, body: dict, db: Session = Depends(get_db)) -> dict:
    """Create an artifact revision from canonical JSON.

    Args:
        project_id: Project id.
        body: Type, name, and content.
        db: Session.

    Returns:
        Revision summary.
    """
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type=body["type"],
        name=body.get("name") or body["type"],
        content=body["content"],
        content_schema=body.get("content_schema") or f"{body['type']}/1",
        created_by=body.get("created_by") or "user",
        artifact_id=body.get("artifact_id"),
        expected_version=body.get("expected_version"),
        validation_status=body.get("validation_status") or "pending",
    )
    return {
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "content_hash": revision.content_hash,
    }


@router.post("/artifacts/{artifact_id}/revisions", status_code=201)
def add_revision(artifact_id: str, body: RevisionCreate, db: Session = Depends(get_db)) -> dict:
    """Save a full new revision with an optimistic version check.

    Args:
        artifact_id: Artifact id.
        body: Content and expected version.
        db: Session.

    Returns:
        Revision summary.
    """
    from app.models import Artifact

    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise AppError("Artifact not found", "not_found", 404)
    content, status, validation = prepare_revision(db, artifact, body.content)
    revision = ArtifactRepository(db).create(
        project_id=artifact.project_id,
        artifact_type=artifact.type,
        name=body.name or artifact.name,
        content=content,
        content_schema=ArtifactRepository(db).latest(artifact_id).content_schema,
        created_by=body.created_by,
        artifact_id=artifact_id,
        expected_version=body.expected_version,
        validation_status=status,
    )
    return {
        "artifact_id": artifact_id,
        "version": revision.version,
        "stale": revision.stale,
        "validation_status": revision.validation_status,
        "validation": validation,
        "content": revision.content,
    }


@router.post("/artifacts/{artifact_id}/patch", status_code=201)
def patch_artifact(artifact_id: str, body: SemanticPatch, db: Session = Depends(get_db)) -> dict:
    """Apply a semantic patch as a new revision.

    Args:
        artifact_id: Artifact id.
        body: Patch.
        db: Session.

    Returns:
        Revision summary.
    """
    from app.models import Artifact

    artifact = db.get(Artifact, artifact_id)
    latest = ArtifactRepository(db).latest(artifact_id)
    if artifact is None or latest is None:
        raise AppError("Artifact not found", "not_found", 404)
    content = apply_semantic_patch(latest.content, body)
    revision = ArtifactRepository(db).create(
        project_id=artifact.project_id,
        artifact_type=artifact.type,
        name=artifact.name,
        content=content,
        content_schema=latest.content_schema,
        created_by=body.created_by,
        artifact_id=artifact_id,
        expected_version=body.expected_version,
    )
    return {"artifact_id": artifact_id, "version": revision.version, "content": revision.content}


@router.get("/artifacts/{artifact_id}/revisions")
def list_revisions(artifact_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Return version history.

    Args:
        artifact_id: Artifact id.
        db: Session.

    Returns:
        Revisions without duplicating large content in the list... content is included so the panel can restore.
    """
    return [
        {
            "version": row.version,
            "parent_version": row.parent_version,
            "content_hash": row.content_hash,
            "stale": row.stale,
            "validation_status": row.validation_status,
            "created_by": row.created_by,
            "content": row.content,
        }
        for row in ArtifactRepository(db).history(artifact_id)
    ]


@router.post("/projects/{project_id}/files", status_code=201)
async def upload_file(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Store an upload and ingest SPSS files.

    Args:
        project_id: Project id.
        request: Current request.
        file: Upload.
        db: Session.

    Returns:
        File metadata and dataset id when ingested.
    """
    ProjectRepository(db).get(project_id)
    data = await file.read()
    settings = request.app.state.settings
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(
            "This file is larger than the configured limit. Raise MAX_UPLOAD_MB or upload a smaller extract.",
            "file_too_large",
        )
    storage: Storage = request.app.state.storage
    safe = Storage.safe_filename(file.filename or "upload.bin")
    suffix = safe.lower().rsplit(".", 1)[-1]
    allowed = {"sav", "zsav", "xlsx", "csv", "docx", "pdf", "txt", "md", "json"}
    if suffix not in allowed:
        raise AppError(f"Unsupported file type '.{suffix}'.", "unsupported_file")
    relative = f"uploads/{new_id()}-{safe}"
    storage.write_bytes(project_id, relative, data)
    row = FileRepository(db).add(
        project_id=project_id,
        filename=safe,
        media_type=file.content_type or "application/octet-stream",
        sha256=sha256_bytes(data),
        storage_relpath=relative,
        size_bytes=len(data),
    )
    dataset_id = None
    workbook = None
    if suffix in {"sav", "zsav"}:
        dataset = ingest_spss(db, storage, settings, project_id, row.id)
        dataset_id = dataset.id
    elif suffix == "xlsx":
        from app.services.workbook_ingest import ingest_workbook

        workbook = ingest_workbook(db, storage, project_id, data)
    return {
        "file_id": row.id,
        "filename": row.filename,
        "sha256": row.sha256,
        "dataset_id": dataset_id,
        "workbook": workbook,
    }


@router.get("/files/{file_id}/download")
def download_file(file_id: str, request: Request, db: Session = Depends(get_db)) -> FileResponse:
    """Download a real stored file.

    Args:
        file_id: File id.
        request: Current request.
        db: Session.

    Returns:
        File response.
    """
    row = FileRepository(db).get(file_id)
    path = request.app.state.storage.resolve(row.project_id, row.storage_relpath)
    return FileResponse(path, filename=row.filename, media_type=row.media_type)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db)) -> dict:
    """Return dataset metadata.

    Args:
        dataset_id: Dataset id.
        db: Session.

    Returns:
        Metadata.
    """
    row = DatasetRepository(db).get(dataset_id)
    return {
        "id": row.id,
        "row_count": row.row_count,
        "variables": row.variables,
        "weight_candidates": row.weight_candidates,
        "source_sha256": row.source_sha256,
        "format": row.format,
    }


@router.get("/datasets/{dataset_id}/preview")
def preview_dataset(
    dataset_id: str, request: Request, limit: int = 20, db: Session = Depends(get_db)
) -> dict:
    """Return a short data preview.

    Args:
        dataset_id: Dataset id.
        request: Current request.
        limit: Row limit, capped at 50.
        db: Session.

    Returns:
        Column names and rows.
    """
    row = DatasetRepository(db).get(dataset_id)
    frame = load_frame(request.app.state.storage, row).head(min(limit, 50))
    return {
        "columns": list(frame.columns),
        "rows": frame.where(frame.notna(), None).to_dict(orient="records"),
    }


@router.post("/projects/{project_id}/questionnaires")
def post_questionnaire(project_id: str, body: Questionnaire, db: Session = Depends(get_db)) -> dict:
    """Validate and store a questionnaire.

    Args:
        project_id: Project id.
        body: Questionnaire.
        db: Session.

    Returns:
        Save result.
    """
    return save_questionnaire(db, project_id, body, created_by="user")


@router.post("/projects/{project_id}/questionnaires/export/{kind}")
def export_questionnaire(
    project_id: str, kind: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Export the latest questionnaire.

    Args:
        project_id: Project id.
        kind: docx, pdf, md, or json.
        request: Current request.
        db: Session.

    Returns:
        File id.
    """
    file_id = export_questionnaire_file(db, request.app.state.storage, project_id, kind)
    return {"file_id": file_id}


@router.post("/projects/{project_id}/questionnaires/decipher")
def program_decipher_route(
    project_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Program the latest questionnaire as Decipher XML.

    Args:
        project_id: Project id.
        request: Current request.
        db: Session.

    Returns:
        Artifact id, file id, and summary.
    """
    from app.services.decipher_program import program_decipher_survey

    return program_decipher_survey(db, request.app.state.storage, project_id)


@router.post("/projects/{project_id}/questionnaires/decipher/preview-source")
def preview_decipher_source(
    project_id: str, body: Questionnaire, db: Session = Depends(get_db)
) -> dict:
    """Compile a draft to survey XML without saving it.

    Args:
        project_id: Project id.
        body: Questionnaire draft.
        db: Session.

    Returns:
        Compiled XML, status, and any programming issues.
    """
    ProjectRepository(db).get(project_id)
    program = compile_decipher(body)
    return {
        "xml": program.xml,
        "title": program.title,
        "warnings": program.warnings,
        "validation_status": program.validation_status,
        "issues": program.issues,
    }


@router.post("/projects/{project_id}/questionnaires/decipher/preview")
def preview_decipher(project_id: str, body: PreviewRequest, db: Session = Depends(get_db)) -> dict:
    """Return the next respondent screen for a survey XML file.

    Args:
        project_id: Project id.
        body: XML, answers so far, and the question just answered.
        db: Session.

    Returns:
        The next screen. This route does not write a revision.
    """
    ProjectRepository(db).get(project_id)
    return step_preview(body.xml, body.answers, body.current_label).model_dump(mode="json")


@router.post("/artifacts/{artifact_id}/validate")
def validate_artifact(artifact_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-run the deterministic validator for an analysis artifact.

    Args:
        artifact_id: Artifact id.
        db: Session.

    Returns:
        Validation report.
    """
    latest = ArtifactRepository(db).latest(artifact_id)
    if latest is None:
        raise AppError("Artifact not found", "not_found", 404)
    if "report" not in latest.content or "result" not in latest.content:
        raise AppError("This artifact has no bound analysis report to validate.", "bad_request")
    report = validation_for_report_artifact(latest.content)
    latest.validation_status = report.status
    return report.model_dump(mode="json")


def _artifact(artifact: object, latest: object) -> dict:
    """Serialize an artifact and its latest revision.

    Args:
        artifact: Artifact identity.
        latest: Latest revision or None.

    Returns:
        Dictionary.
    """
    return {
        "id": artifact.id,
        "type": artifact.type,
        "name": artifact.name,
        "latest": (
            None
            if latest is None
            else {
                "version": latest.version,
                "content": latest.content,
                "stale": latest.stale,
                "validation_status": latest.validation_status,
                "content_hash": latest.content_hash,
                "content_schema": latest.content_schema,
                "validation": _questionnaire_flow(artifact, latest),
            }
        ),
    }


def _questionnaire_flow(artifact: object, latest: object) -> dict | None:
    """Return the live flow report for a questionnaire revision.

    Args:
        artifact: Artifact identity.
        latest: Latest revision.

    Returns:
        Flow report, or None when the artifact is not a questionnaire.
    """
    if getattr(artifact, "type", None) != "questionnaire" or latest is None:
        return None
    try:
        document = Questionnaire.model_validate(latest.content)
    except ValidationError:
        return None
    return validate_questionnaire(document).model_dump(mode="json")
