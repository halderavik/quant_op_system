"""Program the saved questionnaire as a Decipher survey artifact."""

from sqlalchemy.orm import Session

from app.engines.decipher import compile_decipher
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.questionnaire import Questionnaire
from app.services.storage import Storage
from app.services.stored_files import _write_export


def program_decipher_survey(db: Session, storage: Storage, project_id: str) -> dict:
    """Compile the latest questionnaire and store the XML.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.

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
    file_id = _write_export(
        db,
        storage,
        project_id,
        "survey.xml",
        program.xml.encode("utf-8"),
        "application/xml",
    )
    stored = program.model_copy(
        update={
            "file_id": file_id,
            "questionnaire_artifact_id": current.artifact_id,
            "questionnaire_version": current.version,
        }
    )
    existing = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
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
        validation_status=program.validation_status,
        artifact_id=existing.artifact_id if existing else None,
        expected_version=existing.version if existing else None,
    )
    return {
        "summary": _summary(document.title, len(document.questions), len(program.warnings)),
        "status": (
            "completed" if program.validation_status == "passed" else "completed_with_warnings"
        ),
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "file_id": file_id,
        "validation_status": program.validation_status,
    }


def _summary(title: str, question_count: int, warning_count: int) -> str:
    """Describe the programmed survey for the chat reply.

    Args:
        title: Questionnaire title.
        question_count: Number of questions read.
        warning_count: Programming warnings.

    Returns:
        User-facing summary.
    """
    if warning_count:
        noun = "warning" if warning_count == 1 else "warnings"
        programmed = f"Programmed {title} as Decipher XML with {warning_count} programming {noun}."
    else:
        programmed = f"Programmed {title} as Decipher XML ({question_count} questions)."
    return (
        f"{programmed} The XML is in the side panel. "
        "Direct launch in Decipher is not connected. Download the XML and import it."
    )
