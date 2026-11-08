"""Revision guards for questionnaire, tab spec, report, codeframe, and coding edits."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.engines.analysis.report import render_claims, unclaimed_numbers
from app.engines.coding_agg import aggregate, final_codes
from app.engines.flow import validate_questionnaire
from app.engines.invariants import summarize, validate_report
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.analysis import AnalysisReport
from app.schemas.coding import Codeframe, CodingAssignment
from app.schemas.questionnaire import Questionnaire
from app.schemas.tabspec import TabSpec
from app.services.codeframe_author import guard_codeframe


def prepare_revision(
    db: Session, artifact: Any, content: dict[str, Any]
) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    """Validate a panel edit and return the content that should be stored.

    Args:
        db: Session.
        artifact: Artifact identity.
        content: Proposed canonical JSON.

    Returns:
        Content, validation status, and an optional validation payload.
    """
    if artifact.type == "questionnaire":
        return _questionnaire(content)
    if artifact.type == "tabspec":
        return _tabspec(content)
    if artifact.type == "analysis":
        return _analysis(content)
    if artifact.type == "coding":
        return _coding(db, artifact.project_id, content)
    if artifact.type == "codeframe":
        previous = ArtifactRepository(db).latest(artifact.id)
        prior = previous.content if previous else None
        return _codeframe(db, artifact.project_id, content, prior)
    return content, "pending", None


def _questionnaire(content: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Validate questionnaire structure. A broken route is saved and flagged.

    Args:
        content: Proposed document.

    Returns:
        Dumped document, flow status, and the flow report.
    """
    try:
        document = Questionnaire.model_validate(content)
    except ValidationError as exc:
        raise AppError("The questionnaire is not valid.", "bad_questionnaire") from exc
    flow = validate_questionnaire(document)
    return document.model_dump(mode="json"), flow.status, flow.model_dump(mode="json")


def _tabspec(content: dict[str, Any]) -> tuple[dict[str, Any], str, None]:
    """Reject duplicate table ids and banner ids that are not on the spec.

    Args:
        content: Proposed spec. Extra keys such as an export id are kept.

    Returns:
        Spec content and a passing status.
    """
    try:
        spec = TabSpec.model_validate(content)
    except ValidationError as exc:
        raise AppError("The tab spec is not valid.", "bad_tabspec") from exc
    ids = [table.id for table in spec.tables]
    if len(ids) != len(set(ids)):
        raise AppError("Table ids must be unique.", "duplicate_table")
    known = {banner.id for banner in spec.banners}
    for table in spec.tables:
        missing = [banner_id for banner_id in table.banner_ids if banner_id not in known]
        if missing:
            raise AppError(
                f"Table {table.id} references a banner that is not on the spec: {', '.join(missing)}.",
                "bad_banner",
            )
    dumped = spec.model_dump(mode="json")
    for key, value in content.items():
        if key not in dumped:
            dumped[key] = value
    return dumped, "passed", None


def _analysis(content: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Rebuild the rendered narrative from claims and reject unclaimed numbers.

    Args:
        content: Analysis artifact with ``report`` and ``result``.

    Returns:
        Updated content and the validator status.

    Raises:
        AppError: When prose states a number that is not a claim, or a claim
            does not match the computed result. Nothing is stored in that case.
    """
    try:
        report = AnalysisReport.model_validate(content.get("report") or {})
    except ValidationError as exc:
        raise AppError("The report is not valid.", "bad_report") from exc
    unknown: list[str] = []
    for section in report.sections:
        unknown.extend(unclaimed_numbers(str(section.get("narrative") or ""), report.claims))
    for caveat in report.caveats:
        unknown.extend(unclaimed_numbers(caveat, report.claims))
    if unknown:
        raise AppError(
            "The narrative states a number that is not in the computed claims: "
            + ", ".join(unknown),
            "unclaimed_number",
        )
    report.rendered = render_claims(report.claims)
    gate = summarize(validate_report(report, content.get("result") or {}))
    if gate.status == "failed":
        detail = next(
            (check.details for check in gate.checks if check.status == "failed" and check.details),
            "The report claims do not match the computed result.",
        )
        raise AppError(str(detail), "report_mismatch")
    updated = dict(content)
    updated["report"] = report.model_dump(mode="json")
    return updated, gate.status, gate.model_dump(mode="json")


def _coding(
    db: Session, project_id: str, content: dict[str, Any]
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Recompute frequencies from final codes. Unknown override ids are rejected.

    Args:
        db: Session.
        project_id: Project id.
        content: Coding artifact.

    Returns:
        Content with a fresh frequency report.
    """
    frame = _load_codeframe(db, project_id, content)
    rows = [CodingAssignment.model_validate(row) for row in content.get("assignments") or []]
    report = aggregate(frame, rows)
    updated = dict(content)
    updated["assignments"] = [row.model_dump(mode="json") for row in rows]
    updated["report"] = report.model_dump(mode="json")
    return (
        updated,
        "passed",
        {"substantive_n": report.substantive_n, "nonsubstantive_n": report.nonsubstantive_n},
    )


def _codeframe(
    db: Session,
    project_id: str,
    content: dict[str, Any],
    previous: dict[str, Any] | None,
) -> tuple[dict[str, Any], str, None]:
    """Bump the codeframe version and reject edits that orphan coded ids.

    Args:
        db: Session.
        project_id: Project id.
        content: Proposed frame.
        previous: Current stored frame.

    Returns:
        Stored frame and a review status.
    """
    try:
        frame = Codeframe.model_validate(content)
    except ValidationError as exc:
        raise AppError("The codeframe is not valid.", "bad_codeframe") from exc
    guard_codeframe(frame)
    prior_version = int((previous or {}).get("version") or 0)
    frame.version = prior_version + 1 if previous else max(int(frame.version or 1), 1)
    if previous:
        old_ids = {str(item.get("id")) for item in previous.get("codes") or [] if item.get("id")}
        removed = old_ids - {code.id for code in frame.codes}
        used = _used_code_ids(db, project_id)
        orphaned = sorted(removed & used)
        if orphaned:
            raise AppError(
                "Those code ids are used by saved assignments and cannot be removed: "
                + ", ".join(orphaned),
                "orphan_code",
            )
    dumped = frame.model_dump(mode="json")
    if "ignored_columns" in content:
        dumped["ignored_columns"] = content["ignored_columns"]
    return dumped, "needs_review", None


def _load_codeframe(db: Session, project_id: str, content: dict[str, Any]) -> Codeframe:
    """Load the frame embedded on the coding artifact or the latest codeframe.

    Args:
        db: Session.
        project_id: Project id.
        content: Coding content.

    Returns:
        Codeframe.
    """
    embedded = content.get("codeframe")
    if isinstance(embedded, dict) and embedded.get("codes"):
        return Codeframe.model_validate(embedded)
    revision = ArtifactRepository(db).latest_of_type(project_id, "codeframe")
    if revision is None:
        raise AppError("Approve a codeframe before editing assignments.", "missing_codeframe")
    payload = revision.content
    if "codeframe" in payload and "codes" not in payload:
        payload = payload["codeframe"]
    return Codeframe.model_validate(payload)


def _used_code_ids(db: Session, project_id: str) -> set[str]:
    """Return code ids present on the latest coding assignments.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        Code ids. An empty set when nothing has been coded.
    """
    revision = ArtifactRepository(db).latest_of_type(project_id, "coding")
    if revision is None:
        return set()
    used: set[str] = set()
    for raw in revision.content.get("assignments") or []:
        row = CodingAssignment.model_validate(raw)
        used.update(final_codes(row))
    return used
