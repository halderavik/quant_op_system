"""Record learning events. Capture never blocks or breaks the work it observes.

Every public function swallows its own errors and logs them: a failed capture
must not fail a save, a download, or a chat task.
"""

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.learning.diff import generic_diff, has_changes, questionnaire_diff, report_diff
from app.models.tables import (
    Artifact,
    ArtifactRevision,
    LearningEvent,
    Project,
    StoredFile,
    Task,
)
from app.util import new_id

logger = logging.getLogger(__name__)

_STUDY_TYPES = {
    "brand_health": r"brand health|awareness|consideration|brand funnel|tracker|tracking",
    "concept_test": r"concept|proposition|idea screen",
    "ad_test": r"\bad test|advert|creative|campaign|commercial",
    "pricing": r"pric|van westendorp|gabor|willingness to pay|\bwtp\b",
    "usage_attitude": r"usage|u&a|attitude|habit",
    "satisfaction": r"satisfaction|\bnps\b|net promoter|loyalty|customer experience|\bcx\b",
    "segmentation": r"segment",
    "product_test": r"product test|in-home|\bihut\b|sensory|taste test",
    "packaging": r"\bpack(?:aging|age)?\b",
}
_INSIGHT = {
    "segmentation": ("clustering", "kmeans", "pam", "hierarch", "gaussian", "spectral", "dbscan"),
    "drivers": ("key_driver",),
    "group_difference": ("t_test", "anova", "chi_square"),
    "dimension_reduction": ("efa", "pca"),
    "regression": ("regression",),
    "correlation": ("correlation",),
    "descriptive": ("descriptive",),
}
_FOLLOWUP_MARK = "Follow-up instruction:"


def capture_enabled(db: Session, project_id: str) -> bool:
    """Return whether this project records learning events.

    The global switch is ``LEARNING_CAPTURE``. A project opts out with
    ``study_context.learning_opt_out``.
    """
    from app.config import get_settings

    if not get_settings().learning_capture:
        return False
    project = db.get(Project, project_id)
    return bool(project) and not (project.study_context or {}).get("learning_opt_out")


def record_revision(
    db: Session,
    artifact: Artifact,
    revision: ArtifactRevision,
    *,
    actor: str,
    instruction: str = "",
) -> LearningEvent | None:
    """Record what changed between a revision and the one before it.

    A second call for the same revision (a chat edit saved as a user revision)
    adds the chat instruction to the first event instead of writing another.

    Args:
        db: Session.
        artifact: Artifact identity.
        revision: The new revision.
        actor: ``user`` for panel saves, ``chat`` for edits asked for in chat.
        instruction: The chat request that produced the edit, if any.

    Returns:
        The event, or None when nothing changed, capture is off, or it failed.
    """
    try:
        if not revision.parent_version or not capture_enabled(db, artifact.project_id):
            return None
        kind = _edit_kind(artifact.type)
        existing = db.scalar(
            select(LearningEvent).where(
                LearningEvent.artifact_id == artifact.id,
                LearningEvent.to_version == revision.version,
                LearningEvent.kind == kind,
            )
        )
        if existing is not None:
            if instruction:
                existing.instruction = instruction
                existing.actor = actor
            return existing
        previous = db.scalar(
            select(ArtifactRevision).where(
                ArtifactRevision.artifact_id == artifact.id,
                ArtifactRevision.version == revision.parent_version,
            )
        )
        if previous is None:
            return None
        diff = _diff(artifact.type, previous.content or {}, revision.content or {})
        if not has_changes(diff):
            return None
        diff["previous_author"] = previous.created_by
        event = LearningEvent(
            id=new_id(),
            project_id=artifact.project_id,
            artifact_id=artifact.id,
            artifact_type=artifact.type,
            kind=kind,
            actor=actor,
            from_version=previous.version,
            to_version=revision.version,
            instruction=instruction,
            context=study_context(db, artifact.project_id, revision.content or {}, artifact.type),
            payload=diff,
        )
        db.add(event)
        db.flush()
        return event
    except Exception:
        logger.exception("Learning capture failed for artifact %s", artifact.id)
        return None


def record_task_outcome(db: Session, task: Task, outcome: dict[str, Any]) -> None:
    """Record learning signals from a finished chat task.

    A questionnaire revised in chat is recorded with the request that asked
    for it. An analysis run is recorded with its plan, and as a follow-up when
    the previous task in the conversation was also an analysis.

    Args:
        db: Session.
        task: The finished task, with its contract.
        outcome: Specialist outcome; ``artifact_id`` names the saved artifact.
    """
    try:
        contract = task.contract or {}
        intent = str(contract.get("intent") or "")
        artifact_id = str(outcome.get("artifact_id") or "")
        if not artifact_id or not capture_enabled(db, task.project_id):
            return
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:
            return
        latest = _latest(db, artifact_id)
        request = str(contract.get("user_request") or "")
        if intent == "revise_questionnaire" and latest is not None:
            record_revision(db, artifact, latest, actor="chat", instruction=_own_words(request))
        elif intent == "run_analysis" and latest is not None:
            _record_analysis(db, task, artifact, latest, request, str(outcome.get("status") or ""))
    except Exception:
        logger.exception("Learning capture failed for task %s", task.id)


def record_download(db: Session, stored: StoredFile) -> None:
    """Record that a user downloaded a deliverable."""
    try:
        if not capture_enabled(db, stored.project_id):
            return
        db.add(
            LearningEvent(
                id=new_id(),
                project_id=stored.project_id,
                kind="download",
                actor="user",
                payload={"file_id": stored.id, "filename": stored.filename},
            )
        )
        db.flush()
    except Exception:
        logger.exception("Learning capture failed for download %s", stored.id)


def record_feedback(db: Session, artifact: Artifact, rating: str, note: str) -> LearningEvent:
    """Record an explicit rating on an artifact. This one is not optional to the caller."""
    latest = _latest(db, artifact.id)
    event = LearningEvent(
        id=new_id(),
        project_id=artifact.project_id,
        artifact_id=artifact.id,
        artifact_type=artifact.type,
        kind="feedback",
        actor="user",
        to_version=latest.version if latest else None,
        instruction=note.strip()[:2000],
        context=study_context(
            db, artifact.project_id, (latest.content if latest else {}) or {}, artifact.type
        ),
        payload={"rating": rating},
    )
    db.add(event)
    db.flush()
    return event


def study_context(
    db: Session, project_id: str, content: dict[str, Any], artifact_type: str
) -> dict[str, Any]:
    """Tags a later lesson step can group by. No respondent data.

    Args:
        db: Session.
        project_id: Project id.
        content: Artifact content the event is about.
        artifact_type: Artifact type.

    Returns:
        Study title, objectives, study types, and, for analyses, the insight type.
    """
    questionnaire = content if artifact_type == "questionnaire" else _questionnaire(db, project_id)
    title = str((questionnaire or {}).get("title") or "")
    objectives = [
        str(item.get("description") or "")
        for item in (questionnaire or {}).get("objectives") or []
        if item.get("description")
    ]
    project = db.get(Project, project_id)
    objectives += [
        str(item)
        for item in ((project.study_context or {}).get("objectives") or [] if project else [])
    ]
    text = " ".join([title, *objectives]).lower()
    settings = (project.study_context or {}) if project else {}
    context: dict[str, Any] = {
        "market": settings.get("market"),
        "audience": settings.get("audience"),
        "study_title": title,
        "objectives": objectives[:12],
        "study_types": [name for name, pattern in _STUDY_TYPES.items() if re.search(pattern, text)]
        or ["other"],
    }
    if questionnaire:
        context["question_count"] = len(questionnaire.get("questions") or [])
        context["estimated_minutes"] = questionnaire.get("estimated_minutes")
    if artifact_type == "analysis":
        context["insight_types"] = insight_types(content.get("workflow") or {})
    return context


def insight_types(workflow: dict[str, Any]) -> list[str]:
    """Classify an analysis plan by the kind of insight its methods produce."""
    methods = [
        str(step.get("method") or "").lower()
        for step in workflow.get("steps") or []
        if step.get("kind") == "method"
    ]
    found = [
        name
        for name, markers in _INSIGHT.items()
        if any(marker in method for method in methods for marker in markers)
    ]
    return found or (["other"] if methods else [])


def _record_analysis(
    db: Session,
    task: Task,
    artifact: Artifact,
    revision: ArtifactRevision,
    request: str,
    status: str,
) -> None:
    """Record the plan that ran, and whether it corrected the previous analysis."""
    content = revision.content or {}
    workflow = content.get("workflow") or {}
    result = content.get("result") or {}
    checks = (result.get("diagnostics") or {}).get("quality_checks") or []
    plan = _plan_summary(workflow)
    payload: dict[str, Any] = {
        "objective": workflow.get("objective"),
        "plan": plan,
        "standards_applied": workflow.get("standards") or [],
        "quality_flags": [
            f"{item.get('area')}: {item.get('check')}"
            for item in checks
            if item.get("status") == "flag"
        ],
        "status": status,
        "valid_n": (result.get("sample_flow") or {}).get("valid_n"),
    }
    previous = _previous_analysis(db, task, artifact.id)
    kind = "analysis_run"
    instruction = _own_words(request)
    if _FOLLOWUP_MARK in request or previous is not None:
        kind = "analysis_followup"
        if previous is not None:
            payload["previous"] = {
                "artifact_id": previous.artifact_id,
                "version": previous.version,
                "plan": _plan_summary((previous.content or {}).get("workflow") or {}),
            }
    db.add(
        LearningEvent(
            id=new_id(),
            project_id=task.project_id,
            artifact_id=artifact.id,
            artifact_type="analysis",
            kind=kind,
            actor="chat",
            to_version=revision.version,
            instruction=instruction,
            context=study_context(db, task.project_id, content, "analysis"),
            payload=payload,
        )
    )
    db.flush()


def _plan_summary(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Steps without long reasons: kind, method, and the settings that shape results."""
    keep = ("kind", "method", "strategy", "box", "k", "k_min", "k_max", "dependent", "group")
    keep_lists = ("variables", "predictors", "codes")
    steps = []
    for step in workflow.get("steps") or []:
        item = {key: step.get(key) for key in keep if step.get(key) not in (None, "", 0)}
        for key in keep_lists:
            if step.get(key):
                item[key] = list(step[key])[:30]
        for key in ("split_by", "output", "var_a", "var_b"):
            if step.get(key):
                item[key] = step[key]
        steps.append(item)
    return steps


def _previous_analysis(db: Session, task: Task, artifact_id: str) -> ArtifactRevision | None:
    """The analysis just before this one, when the previous chat turn was an analysis."""
    earlier = db.scalar(
        select(Task)
        .where(
            Task.conversation_id == task.conversation_id,
            Task.created_at < task.created_at,
            Task.id != task.id,
        )
        .order_by(Task.created_at.desc())
        .limit(1)
    )
    if earlier is None or (earlier.contract or {}).get("intent") != "run_analysis":
        return None
    if earlier.status not in {"completed", "completed_with_warnings"}:
        return None
    return db.scalar(
        select(ArtifactRevision)
        .join(Artifact, Artifact.id == ArtifactRevision.artifact_id)
        .where(
            Artifact.project_id == task.project_id,
            Artifact.type == "analysis",
            ArtifactRevision.created_at < task.created_at,
        )
        .order_by(ArtifactRevision.created_at.desc())
        .limit(1)
    )


def _latest(db: Session, artifact_id: str) -> ArtifactRevision | None:
    return db.scalar(
        select(ArtifactRevision)
        .where(ArtifactRevision.artifact_id == artifact_id)
        .order_by(ArtifactRevision.version.desc())
        .limit(1)
    )


def _questionnaire(db: Session, project_id: str) -> dict[str, Any] | None:
    revision = db.scalar(
        select(ArtifactRevision)
        .join(Artifact, Artifact.id == ArtifactRevision.artifact_id)
        .where(Artifact.project_id == project_id, Artifact.type == "questionnaire")
        .order_by(ArtifactRevision.created_at.desc())
        .limit(1)
    )
    return revision.content if revision else None


def _edit_kind(artifact_type: str) -> str:
    if artifact_type == "questionnaire":
        return "questionnaire_edit"
    if artifact_type == "analysis":
        return "report_edit"
    return "artifact_edit"


def _diff(artifact_type: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if artifact_type == "questionnaire":
        return questionnaire_diff(before, after)
    if artifact_type == "analysis":
        return report_diff(before, after)
    return generic_diff(before, after)


def _own_words(request: str) -> str:
    """The user's own text, without a prior analysis request joined in front of it."""
    if _FOLLOWUP_MARK in request:
        request = request.split(_FOLLOWUP_MARK, 1)[1]
    return request.strip()[:2000]
