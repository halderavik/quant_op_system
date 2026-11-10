"""Program the saved questionnaire as a Decipher survey artifact."""

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.engines.decipher import compile_decipher
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.questionnaire import Questionnaire
from app.services.decipher_launch import launcher_from_settings
from app.services.storage import Storage
from app.services.stored_files import _write_export


def program_decipher_survey(
    db: Session,
    storage: Storage,
    project_id: str,
    settings: Settings | None = None,
) -> dict:
    """Compile the latest questionnaire, store the XML, and upload it when a key is set.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        settings: Server settings. The API key is read here and is not returned.

    Returns:
        Summary, status, artifact id, and file id.

    Raises:
        AppError: There is no questionnaire, or the survey XML failed validation.
    """
    current = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    if current is None:
        raise AppError(
            "There is no questionnaire in this project yet. Generate one, then ask to program it in Decipher.",
            "clarification_needed",
        )
    document = Questionnaire.model_validate(current.content)
    program = compile_decipher(document)
    if program.validation_status == "failed":
        detail = (
            " ".join(program.issues)
            if program.issues
            else "The Decipher survey could not be programmed."
        )
        raise AppError(detail, "decipher_invalid")
    existing = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    stored_path = _stored_path(existing.content if existing else None)
    active = settings or get_settings()
    xml, launch_status, launch_message, survey_path, survey_url, fixes = _upload(
        active, program.xml, document.title, stored_path
    )
    file_id = _write_export(
        db,
        storage,
        project_id,
        "survey.xml",
        xml.encode("utf-8"),
        "application/xml",
    )
    warnings = [*program.warnings, *[f"Decipher correction: {fix}" for fix in fixes]]
    validation = program.validation_status
    if fixes and validation == "passed":
        validation = "passed_with_warnings"
    stored = program.model_copy(
        update={
            "xml": xml,
            "warnings": warnings,
            "validation_status": validation,
            "file_id": file_id,
            "questionnaire_artifact_id": current.artifact_id,
            "questionnaire_version": current.version,
            "launch": launch_status,
            "launch_message": launch_message,
            "survey_path": survey_path,
            "survey_url": survey_url,
        }
    )
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="decipher_survey",
        name=f"Decipher: {document.title}"[:300],
        content=stored.model_dump(mode="json"),
        content_schema="decipher/1",
        created_by="decipher",
        derived_from=[
            {
                "id": current.artifact_id,
                "version": current.version,
                "type": "questionnaire",
            }
        ],
        validation_status=stored.validation_status,
        artifact_id=existing.artifact_id if existing else None,
        expected_version=existing.version if existing else None,
    )
    status = "completed" if stored.validation_status == "passed" else "completed_with_warnings"
    if launch_status == "failed":
        status = "completed_with_warnings"
    return {
        "summary": _summary(
            document.title,
            len(document.questions),
            len(program.warnings),
            launch_status,
            survey_path,
            launch_message,
        ),
        "status": status,
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "file_id": file_id,
        "validation_status": stored.validation_status,
        "survey_path": survey_path,
        "survey_url": survey_url,
    }


def _upload(
    settings: Settings, xml: str, title: str, stored_path: str | None
) -> tuple[str, str, str | None, str | None, str | None, list[str]]:
    """Upload the survey when an API key is set, and keep a corrected document.

    Args:
        settings: Server settings.
        xml: Compiled survey XML.
        title: Research Hub name.
        stored_path: Path from an earlier program of this project.

    Returns:
        XML to save, launch status, message, path, public URL, and corrections.
    """
    if not settings.decipher_api_key.strip():
        return xml, "not_configured", None, stored_path, None, []
    try:
        result = launcher_from_settings(settings).launch(xml, title, survey_path=stored_path)
    except AppError as exc:
        repaired = getattr(exc, "xml", None)
        fixes = [item for item in getattr(exc, "fixes", []) if isinstance(item, str)]
        saved = repaired if isinstance(repaired, str) and repaired.strip() else xml
        return (
            saved,
            "failed",
            exc.message,
            getattr(exc, "survey_path", None) or stored_path,
            getattr(exc, "survey_url", None),
            fixes,
        )
    return (
        result.xml or xml,
        "uploaded",
        result.message,
        result.survey_path,
        result.survey_url,
        list(result.fixes),
    )


def _stored_path(content: object) -> str | None:
    """Read a previously stored Decipher path.

    Args:
        content: Saved artifact content.

    Returns:
        Survey path, or None when this project has not uploaded yet.
    """
    if not isinstance(content, dict):
        return None
    path = content.get("survey_path")
    if isinstance(path, str) and path.strip():
        return path.strip()
    return None


def _summary(
    title: str,
    question_count: int,
    warning_count: int,
    launch_status: str,
    survey_path: str | None,
    launch_message: str | None,
) -> str:
    """Describe the programmed survey for the chat reply.

    Args:
        title: Questionnaire title.
        question_count: Number of questions read.
        warning_count: Programming warnings.
        launch_status: ``not_configured``, ``uploaded``, or ``failed``.
        survey_path: Decipher path when one exists.
        launch_message: Decipher's message when the upload did not succeed.

    Returns:
        User-facing summary.
    """
    if warning_count:
        noun = "warning" if warning_count == 1 else "warnings"
        programmed = f"Programmed {title} as Decipher XML with {warning_count} programming {noun}."
    else:
        programmed = f"Programmed {title} as Decipher XML ({question_count} questions)."
    if launch_status == "uploaded" and survey_path:
        detail = launch_message or f"Uploaded to Decipher at {survey_path}."
        return f"{programmed} {detail}"
    if launch_status == "failed":
        detail = launch_message or "Decipher did not accept the survey."
        return f"{programmed} The XML is in the side panel. {detail}"
    return (
        f"{programmed} The XML is in the side panel. "
        "Direct launch in Decipher is not connected. Download the XML and import it."
    )
