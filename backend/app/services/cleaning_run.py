"""Run a fraud recommendation, or drop the rows that recommendation removes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.agents.cleaning_agent import coding_ready, review_verbatims
from app.config import Settings
from app.engines.cleaning_export import export_cleaning, workbook_row_check
from app.engines.cleaning_oe import _compact, scan_open_ends
from app.engines.cleaning_rules import scan_closed
from app.engines.cleaning_score import assemble, kept_positions, validate_cleaning
from app.engines.invariants import summarize, validate_export
from app.errors import AppError
from app.repositories.records import (
    ArtifactRepository,
    DatasetRepository,
    FileRepository,
    ProjectRepository,
)
from app.schemas.cleaning import CleaningReport, VerbatimJudgement
from app.services.execute import _active_dataset, load_frame
from app.services.storage import Storage
from app.services.stored_files import _write_export
from app.util import new_id

logger = logging.getLogger(__name__)

# Reason: about 125 batch calls at most. Duplicates are labeled once, so this covers most studies.
_CAP = 5000
_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def run_cleaning(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    conversation_id: str,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Recommend which respondents to remove, review, or keep.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings.
        project_id: Project id.
        conversation_id: Conversation id, used as the model session.
        on_stage: Optional stage message for the chat.

    Returns:
        Summary payload. The uploaded SPSS file is not changed.
    """
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    variables = list(dataset.variables or [])
    dataset_id = dataset.id
    source_sha = dataset.source_sha256
    closed = scan_closed(frame, variables)
    opened = scan_open_ends(frame, closed.text_columns)
    # Reason: the model call can take long enough to block the next chat write on SQLite.
    db.commit()
    judgements, unreviewed, semantic = await _review(
        settings,
        opened.pending,
        ProjectRepository(db).conversation(conversation_id).sdk_session_id,
        on_stage,
    )
    report = assemble(
        closed,
        opened,
        judgements,
        unreviewed,
        dataset_id=dataset_id,
        source_sha256=source_sha,
        semantic_review=semantic,
    )
    payload = export_cleaning(report)
    checks = validate_cleaning(report)
    checks.append(workbook_row_check(payload, report.summary.row_count))
    file_id = _write_export(db, storage, project_id, "fraud-recommendation.xlsx", payload, _MEDIA)
    export_path = storage.resolve(project_id, FileRepository(db).get(file_id).storage_relpath)
    checks.append(validate_export(export_path))
    gate = summarize(checks)
    content = report.model_dump(mode="json")
    content["export_file_id"] = file_id
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="cleaning",
        name="Fraud recommendation",
        content=content,
        content_schema="cleaning/1",
        created_by="cleaning",
        validation_status=gate.status,
    )
    status = "completed" if gate.status == "passed" else "failed"
    if status == "completed" and report.summary.semantic_review.startswith(
        "Semantic review was not run"
    ):
        status = "completed_with_warnings"
    summary = _summary_text(report)
    if status == "failed":
        summary = "The recommendation did not pass validation. " + summary
    return {
        "summary": summary,
        "status": status,
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "validation": gate.model_dump(mode="json"),
        "warnings": report.summary.skipped[:5],
    }


def apply_cleaning(db: Session, storage: Storage, project_id: str) -> dict[str, Any]:
    """Write a new dataset version with recommended removals dropped.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.

    Returns:
        Summary payload. Review rows stay. The uploaded file stays in place.

    Raises:
        AppError: No recommendation exists, or it does not match the active dataset.
    """
    revision = ArtifactRepository(db).latest_of_type(project_id, "cleaning")
    if revision is None:
        raise AppError(
            "I need a fraud recommendation before I drop anyone. Ask me to identify fraud respondents first.",
            "missing_roles",
        )
    payload = dict(revision.content or {})
    payload.pop("export_file_id", None)
    report = CleaningReport.model_validate(payload)
    dataset = _active_dataset(db, project_id)
    if report.dataset_id and report.dataset_id != dataset.id:
        raise AppError(
            "This recommendation was run on a different dataset. Run the fraud check again before dropping rows.",
            "stale_cleaning",
        )
    frame = load_frame(storage, dataset)
    if report.summary.row_count != len(frame):
        raise AppError(
            "This recommendation does not match the active dataset. Run the fraud check again before dropping rows.",
            "stale_cleaning",
        )
    positions = kept_positions(report, len(frame))
    dropped = len(frame) - len(positions)
    if dropped == 0:
        return {
            "summary": (
                "The recommendation does not remove anyone, so the active dataset was left as it is. "
                "Review rows were not dropped."
            ),
            "status": "completed",
            "artifact_id": revision.artifact_id,
            "version": revision.version,
        }
    kept = frame.iloc[positions].reset_index(drop=True)
    dataset_id = new_id()
    relative = f"datasets/{dataset_id}.parquet"
    snapshot = storage.resolve(project_id, relative)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    kept.to_parquet(snapshot)
    created = DatasetRepository(db).add(
        id=dataset_id,
        project_id=project_id,
        source_file_id=dataset.source_file_id,
        source_sha256=dataset.source_sha256,
        format=dataset.format,
        row_count=int(len(kept)),
        variables=list(dataset.variables or []),
        weight_candidates=list(dataset.weight_candidates or []),
        version=int(dataset.version) + 1,
        parquet_relpath=relative,
    )
    project = ProjectRepository(db).get(project_id)
    project.active_dataset_id = created.id
    return {
        "summary": (
            f"Dropped {dropped} respondents recommended for removal. {len(kept)} remain, "
            "including anyone marked review. The original SPSS file is unchanged. "
            "Later tables use this cleaned copy."
        ),
        "status": "completed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
    }


async def _review(
    settings: Settings,
    pending: list[Any],
    session_id: str,
    on_stage: Callable[[str], None] | None,
) -> tuple[list[Any], set[int], str]:
    """Classify undecided verbatims, or leave them for review when the model cannot run.

    Args:
        settings: Application settings.
        pending: Undecided verbatims.
        session_id: SDK session id.
        on_stage: Optional stage message.

    Returns:
        Judgements, row positions left unreviewed, and the sentence stored on the summary.
    """
    if not pending:
        return [], set(), "Semantic review was not needed."
    if not coding_ready(settings):
        return (
            [],
            {item.source_row_id for item in pending},
            "Semantic review was not run because no API key is set.",
        )
    # Reason: the same text in the same question gets one label, so it is sent once.
    groups: dict[tuple[str, str], list[Any]] = {}
    for item in pending:
        groups.setdefault(_key(item), []).append(item)
    distinct = [items[0] for items in groups.values()]
    capped = distinct[:_CAP]
    rest = [item for first in distinct[_CAP:] for item in groups[_key(first)]]
    if on_stage is not None:
        on_stage(f"Reading {len(capped)} distinct open ends")

    def progress(done: int, total: int) -> None:
        if on_stage is not None and (done == total or done % max(1, total // 10) == 0):
            on_stage(f"Reading open ends: {done} of {total} batches")

    try:
        labels, failed = await review_verbatims(settings, capped, session_id, progress)
    except Exception:
        logger.warning("Open-end semantic review failed.", exc_info=True)
        return (
            [],
            {item.source_row_id for item in pending},
            "Semantic review failed, so those verbatims were left for review.",
        )
    judgements = _fan_out(labels, capped, groups)
    missed = [
        item for first in capped if first.surrogate_id in failed for item in groups[_key(first)]
    ]
    unreviewed = {item.source_row_id for item in [*rest, *missed]}
    notes = [f"Semantic review ran on {len(capped)} distinct verbatims ({len(pending)} answers)."]
    if rest:
        notes.append(
            f"{len(distinct) - len(capped)} distinct verbatims past the {_CAP} limit were left for review."
        )
    if missed:
        notes.append(f"{len(missed)} answers in failed batches were left for review.")
    return judgements, unreviewed, " ".join(notes)


def _key(item: Any) -> tuple[str, str]:
    """Return the duplicate key for a pending verbatim.

    Args:
        item: Pending verbatim.

    Returns:
        Variable name and normalized text.
    """
    return item.variable, _compact(item.text) or item.text


def _fan_out(
    labels: list[VerbatimJudgement],
    capped: list[Any],
    groups: dict[tuple[str, str], list[Any]],
) -> list[VerbatimJudgement]:
    """Copy each representative's label to the duplicates that were not sent.

    Args:
        labels: Model labels for representatives.
        capped: Representatives sent to the model.
        groups: Pending verbatims keyed by variable and normalized text.

    Returns:
        One judgement per pending verbatim whose representative was labeled.
    """
    by_id = {item.surrogate_id: item for item in capped}
    found: list[VerbatimJudgement] = []
    for label in labels:
        first = by_id.get(label.surrogate_id)
        if first is None:
            continue
        for item in groups[_key(first)]:
            found.append(label.model_copy(update={"surrogate_id": item.surrogate_id}))
    return found


def _summary_text(report: CleaningReport) -> str:
    """Write the chat sentence from the computed counts.

    Args:
        report: Recommendation.

    Returns:
        Summary. It names the skips and says the original file was kept.
    """
    summary = report.summary
    ranked = sorted(summary.rule_counts.items(), key=lambda item: (-item[1], item[0]))
    top = ", ".join(f"{rule_id} ({count})" for rule_id, count in ranked[:3] if count) or "none"
    skipped = "; ".join(summary.skipped) if summary.skipped else "none"
    text = (
        f"Examined {summary.row_count} respondents. "
        f"Recommend removing {summary.remove_n}, reviewing {summary.review_n}, "
        f"and keeping {summary.keep_n}. "
        f"Rules that fired most often: {top}. "
        f"Not run: {skipped}. "
        f"{summary.semantic_review} "
        "The original SPSS file was not changed."
    )
    if summary.weighted_remove_share is not None and summary.weighted_review_share is not None:
        text += (
            f" Weighted share of remove is {summary.weighted_remove_share:.1%} "
            f"and review is {summary.weighted_review_share:.1%} on `{summary.weight_variable}`."
        )
    return text
