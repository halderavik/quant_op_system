"""Run the logic test on the project's survey XML."""

from typing import Any

from sqlalchemy.orm import Session

from app.engines.logic_qa import RESPONDENTS, run_logic_qa
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.questionnaire import Questionnaire


def logic_qa(db: Session, project_id: str, respondents: int = RESPONDENTS) -> dict[str, Any]:
    """Simulate respondents through the saved survey XML and check them against the questionnaire.

    The XML is the one stored for the project, which is also what was uploaded to
    Decipher (with any corrections Decipher asked for). The questionnaire is the
    version that XML was built from. Nothing is sent to Decipher.

    Args:
        db: Session.
        project_id: Project id.
        respondents: How many respondents to simulate (50 to 2000).

    Returns:
        The logic test result, plus the survey and questionnaire versions it used.

    Raises:
        AppError: No survey XML, XML that was programmed elsewhere, or no questionnaire.
    """
    repo = ArtifactRepository(db)
    survey = repo.latest_of_type(project_id, "decipher_survey")
    content = (survey.content or {}) if survey else {}
    if not content.get("xml"):
        raise AppError(
            "Program the survey first; there is no survey XML to test.", "not_found", 404
        )
    if content.get("source") == "uploaded_xml":
        raise AppError(
            "This XML was programmed outside Quant OS, so there is no questionnaire logic to "
            "test it against. Use Compare XML instead.",
            "bad_request",
            400,
        )
    source_id = content.get("questionnaire_artifact_id")
    source_version = content.get("questionnaire_version")
    revision = None
    if source_id and source_version:
        try:
            revision = repo.revision(str(source_id), int(source_version))
        except AppError:
            revision = None
    revision = revision or repo.latest_of_type(project_id, "questionnaire")
    if revision is None:
        raise AppError("There is no questionnaire to test the XML against.", "not_found", 404)
    document = Questionnaire.model_validate(revision.content)
    count = max(50, min(int(respondents), 2000))
    result = run_logic_qa(document, str(content["xml"]), list(content.get("items") or []), count)
    result["survey_version"] = survey.version if survey else None
    result["questionnaire_version"] = revision.version
    return result


__all__ = ["logic_qa"]
