"""Add live bot and fraud tracking to a Decipher survey XML someone else programmed.

A researcher uploads a survey's XML (exported from Decipher or written by a
programmer). The tracker, the optional privacy notice and in-survey bot check, and the
hidden results page are added exactly as they are for a survey Quant OS programs, and
the result becomes the project's Decipher survey: downloadable, previewable, and
uploadable after confirmation. Nothing else in the survey changes.

An uploaded survey often belongs to a real, possibly live, Decipher project, so an
upload from here always creates a new Decipher test survey; it never replaces one.
"""

import re
import xml.etree.ElementTree as ET
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.engines.decipher_tracking import (
    add_tracking,
    has_tracking,
    page_breaks,
    parse_survey,
    remove_tracking,
    survey_token,
)
from app.errors import AppError
from app.repositories.records import ArtifactRepository, FileRepository
from app.services.storage import Storage
from app.services.stored_files import _write_export
from app.util import sha256_bytes

SOURCE = "uploaded_xml"
_MAX_BYTES = 20 * 1024 * 1024
_SUFFIXES = {"xml", "txt"}
_QUESTION_TAGS = {"radio", "checkbox", "select", "number", "float", "text", "textarea"}
_NEW_SURVEY = (
    "Ready to upload: this creates a new Decipher test survey with tracking. "
    "Your original Decipher survey is not changed."
)


def is_survey_xml(data: bytes) -> bool:
    """Whether file bytes look like a Decipher survey.

    Args:
        data: File content.

    Returns:
        True when a ``<survey`` element appears near the start.
    """
    head = data[:4096].decode("utf-8", errors="ignore").lstrip("﻿ \r\n\t")
    return bool(re.match(r"(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*)*<survey\b", head, re.S))


def attached_survey_xml(
    db: Session, storage: Storage, project_id: str, file_ids: list[str]
) -> str | None:
    """Return the first attached file that is a Decipher survey XML.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        file_ids: Files attached to the message.

    Returns:
        File id, or None.
    """
    files = FileRepository(db)
    for file_id in file_ids:
        try:
            row = files.get(file_id)
        except AppError:
            continue
        suffix = row.filename.lower().rsplit(".", 1)[-1]
        if row.project_id != project_id or suffix not in _SUFFIXES:
            continue
        if row.size_bytes <= _MAX_BYTES and is_survey_xml(
            storage.read_bytes(project_id, row.storage_relpath)[:4096]
        ):
            return row.id
    return None


def _facts(root: ET.Element, xml: str) -> dict[str, Any]:
    """Title and size of a survey, for the reply."""
    title = (root.get("alt") or root.get("name") or "").strip()
    questions = sum(1 for node in root.iter() if node.tag in _QUESTION_TAGS)
    return {
        "title": title or "Uploaded survey",
        "questions": questions,
        "pages": xml.count("<suspend"),
        "usable_pages": len(page_breaks(xml)),
    }


def add_tracking_to_upload(
    db: Session,
    storage: Storage,
    project_id: str,
    file_id: str,
    settings: Settings | None = None,
) -> dict:
    """Add tracking to an uploaded survey XML and save it as the project's Decipher survey.

    Tracking is switched on for the project, so results appear under Live quality.
    Tracking added earlier by Quant OS is replaced with the current settings.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        file_id: The uploaded XML file.
        settings: Server settings.

    Returns:
        Summary, status, artifact id, version, file id, and tracking id.

    Raises:
        AppError: The file is not a Decipher survey XML, is too large, or does not parse.
    """
    from app.services.live_quality import remember_survey_id, set_tracking, tracking_settings
    from app.services.quality_rules import get_rules, survey_rules

    active = settings or get_settings()
    row = FileRepository(db).get(file_id)
    if row.project_id != project_id:
        raise AppError("That file belongs to another project.", "unsupported_file")
    if row.size_bytes > _MAX_BYTES:
        raise AppError(f"{row.filename} is larger than 20 MB.", "unsupported_file")
    data = storage.read_bytes(project_id, row.storage_relpath)
    if not is_survey_xml(data):
        raise AppError(
            f"{row.filename} is not a Decipher survey XML. Export the survey's XML from "
            "Decipher (it starts with <survey ...>) and upload that file.",
            "unsupported_file",
        )
    try:
        original = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(f"{row.filename} is not UTF-8 text.", "unsupported_file") from None
    try:
        root = parse_survey(original)
    except ET.ParseError as exc:
        raise AppError(
            f"{row.filename} is not well-formed XML ({exc}). Fix it in Decipher and export it again.",
            "decipher_invalid",
        ) from None
    if root.tag != "survey":
        raise AppError(
            f"{row.filename} does not start with a <survey> element.", "decipher_invalid"
        )

    warnings: list[str] = []
    replaced = has_tracking(original)
    base = remove_tracking(original) if replaced else original
    if replaced and has_tracking(base):
        raise AppError(
            f"{row.filename} already has Quant OS tracking that could not be removed safely. "
            "Upload the survey's XML from before tracking was added.",
            "decipher_invalid",
        )
    if re.search(r'label="QOS_', base):
        raise AppError(
            f"{row.filename} already uses question labels starting with QOS_, which the "
            "tracking needs. Rename them in Decipher and export the XML again.",
            "decipher_invalid",
        )
    facts = _facts(root, base)

    set_tracking(db, project_id, True)
    tracking_id = tracking_settings(db, project_id)["survey_id"]
    remember_survey_id(db, project_id, tracking_id)
    rules = survey_rules(get_rules(db, project_id))
    try:
        tracked = add_tracking(
            base,
            tracking_id,
            active.bot_detection_api_base,
            token=survey_token(tracking_id, active.bot_detection_token_secret),
            rules=rules,
        )
    except (ValueError, ET.ParseError) as exc:
        raise AppError(f"Tracking could not be added: {exc}", "decipher_invalid") from None

    if rules.get("terminate"):
        after = int(rules.get("after_page") or 2)
        if "QOS_EARLY" not in tracked:
            warnings.append(
                f"The in-survey bot check needs at least {after} pages that every respondent "
                "sees, outside loops and conditional blocks, so only the final check runs."
            )

    source_sha = sha256_bytes(data)
    existing = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    content_before = existing.content if existing and isinstance(existing.content, dict) else {}
    # Reason: re-adding tracking to the same file keeps the test survey made from it.
    same_source = (
        content_before.get("source") == SOURCE and content_before.get("source_sha256") == source_sha
    )
    survey_path = content_before.get("survey_path") if same_source else None
    if active.decipher_api_key.strip():
        launch = "awaiting_confirmation"
        launch_message = (
            f"Ready to upload: this replaces the Decipher test survey at {survey_path}, "
            "made from this file earlier."
            if survey_path
            else _NEW_SURVEY
        )
    else:
        launch, launch_message = "not_configured", None

    stem = row.filename.rsplit(".", 1)[0]
    file_name = f"{stem}_with_tracking.xml"
    out_id = _write_export(
        db, storage, project_id, file_name, tracked.encode("utf-8"), "application/xml"
    )
    content = {
        "title": facts["title"],
        "xml": tracked,
        "items": [],
        "warnings": warnings,
        "validation_status": "passed_with_warnings" if warnings else "passed",
        "issues": [],
        "launch": launch,
        "launch_message": launch_message,
        "survey_path": survey_path,
        "survey_url": content_before.get("survey_url") if same_source else None,
        "file_id": out_id,
        "questionnaire_artifact_id": None,
        "questionnaire_version": None,
        "tracking_survey_id": tracking_id,
        "source": SOURCE,
        "source_file": row.filename,
        "source_sha256": source_sha,
    }
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="decipher_survey",
        name=f"Decipher: {facts['title']}"[:300],
        content=content,
        content_schema="decipher/1",
        created_by="decipher",
        derived_from=[{"id": row.id, "type": "file"}],
        validation_status=content["validation_status"],
        artifact_id=existing.artifact_id if existing else None,
        expected_version=existing.version if existing else None,
    )

    added = "the tracker script, a hidden results page"
    if "QOS_EARLY" in tracked:
        added += f", an in-survey bot check after page {int(rules.get('after_page') or 2)}"
    if 'label="QOS_privacy"' in tracked:
        added += ", a privacy notice on the first page"
    summary = (
        f"Added live bot and fraud tracking to {row.filename} ({facts['title']}, "
        f"{facts['questions']} questions): {added}. Nothing else in the survey changed. "
        f"Tracking id: {tracking_id}; results appear under Live quality. Respondents "
        "screened out before the last page get no verdict in the Decipher data, but their "
        "sessions still appear under Live quality."
    )
    if replaced:
        summary += (
            " The file already had Quant OS tracking, so it was replaced with the current settings."
        )
    summary += f" Download {file_name} from the Decipher output"
    if launch == "awaiting_confirmation":
        summary += (
            ", or click Upload to Decipher there (or reply 'upload it') to create a new "
            "Decipher test survey. Your original survey is not changed."
            if not survey_path
            else f", or click Upload to Decipher to update the test survey at {survey_path}."
        )
    else:
        summary += " and import it into Decipher. Direct upload needs DECIPHER_API_KEY."
    return {
        "summary": summary,
        "status": "completed_with_warnings" if warnings else "completed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "file_id": out_id,
        "tracking_survey_id": tracking_id,
        "validation_status": content["validation_status"],
        "survey_path": survey_path,
    }
