"""Generate synthetic respondents from the programmed survey and publish them as SPSS."""

from __future__ import annotations

import logging
import random
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.agents.synthetic_agent import model_ready, plan_sample, profile_questions
from app.config import Settings
from app.engines.invariants import summarize
from app.engines.sample_parse import parse_request
from app.engines.synthetic_sim import check_quotas, simulate
from app.engines.synthetic_spss import build_frame, check_file, write_sav
from app.engines.synthetic_survey import parse_survey
from app.errors import AppError
from app.repositories.records import (
    ArtifactRepository,
    DatasetRepository,
    FileRepository,
    ProjectRepository,
)
from app.schemas.synthetic import PersonaCount, SurveyPlan, SyntheticReport, TraitLink
from app.services.execute import ingest_spss
from app.services.storage import Storage
from app.services.stored_files import _write_export

logger = logging.getLogger(__name__)

_MAX_SIZE = 5000
_FILENAME = "synthetic-data.sav"
_MEDIA = "application/x-spss-sav"
_REQUEST_SIZE = re.compile(
    r"(\d[\d,]*)\s+(?:synthetic\s+|simulated\s+|dummy\s+|fake\s+|test\s+)?"
    r"(?:respondents?|responses?|completes?|interviews?|participants?|people|records|cases)",
    re.I,
)
_NOTES_SIZE = re.compile(
    r"(\d[\d,]*)\s+(?:completed|completes|complete interviews|interviews)", re.I
)


async def run_synthetic(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    conversation_id: str,
    text: str,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Generate synthetic completes for the latest programmed survey.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings.
        project_id: Project id.
        conversation_id: Conversation id, used as the model session.
        text: User request, which may set the sample size and quotas.
        on_stage: Optional stage message for the chat.

    Returns:
        Summary payload with the artifact and dataset.

    Raises:
        AppError: No programmed survey, or no sample size can be found.
    """
    artifacts = ArtifactRepository(db)
    survey = artifacts.latest_of_type(project_id, "decipher_survey")
    if survey is None:
        raise AppError(
            "I need a programmed Decipher survey first. Ask me to program the survey, then ask for synthetic data.",
            "missing_roles",
        )
    content = dict(survey.content or {})
    questionnaire = artifacts.latest_of_type(project_id, "questionnaire")
    questions = list((questionnaire.content or {}).get("questions") or []) if questionnaire else []
    specs = parse_survey(str(content.get("xml") or ""), list(content.get("items") or []), questions)
    requirement = _requirement(
        text, questionnaire, artifacts.latest_of_type(project_id, "sample_purchase")
    )
    session_id = ProjectRepository(db).conversation(conversation_id).sdk_session_id
    # Reason: the model calls can take minutes, so the chat must not wait on an open write.
    db.commit()
    warnings: list[str] = []
    plan = SurveyPlan()
    profiles: dict = {}
    source = "uniform"
    if model_ready(settings):
        _stage(on_stage, "Planning personas and quotas")
        try:
            plan = await plan_sample(settings, specs, requirement, session_id)
        except Exception:
            logger.warning("Synthetic plan call failed.", exc_info=True)
            warnings.append("The persona plan could not be drawn up, so answers are uniform.")
    else:
        warnings.append(
            "No API key is set for the synthetic model, so every answer is drawn uniformly and no quotas were applied."
        )
    size = _sample_size(
        text, questionnaire, artifacts.latest_of_type(project_id, "sample_purchase"), plan
    )
    if size is None:
        raise AppError(
            "How many synthetic completes should I generate? For example: generate 600 synthetic respondents.",
            "clarification_needed",
        )
    quotas, dropped = check_quotas(specs, plan.quotas)
    warnings.extend(dropped)
    warnings.extend(plan.notes[:5])
    if plan.personas:

        def progress(done: int, total: int) -> None:
            if done == total or done % max(1, total // 5) == 0:
                _stage(on_stage, f"Profiling answers: {done} of {total} batches")

        _stage(on_stage, f"Profiling answers for {len(plan.personas)} personas")
        profiles, failed = await profile_questions(settings, specs, plan, session_id, progress)
        source = "model"
        if failed:
            warnings.append(
                f"{len(failed)} questions had no answer profile, so their answers are uniform: "
                + ", ".join(failed[:10])
            )
    seed = random.SystemRandom().randrange(1, 2**31)
    _stage(on_stage, f"Generating {size} synthetic respondents")
    simulation = simulate(specs, plan.personas, quotas, profiles, size, seed)
    warnings.extend(simulation.warnings)
    frame, meta = build_frame(specs, simulation)
    payload = write_sav(frame, meta)
    checks, quota_counts = check_file(payload, frame, specs, simulation, size)
    gate = summarize(checks)
    file_id = _write_export(db, storage, project_id, _FILENAME, payload, _MEDIA)
    dataset, active = _register(db, storage, settings, project_id, file_id)
    answered = [spec for spec in specs if spec.answered]
    counts = {name: 0 for name in [item.name for item in plan.personas] or ["General"]}
    for person in simulation.respondents:
        counts[person.persona] = counts.get(person.persona, 0) + 1
    shares = {item.name: item.share for item in plan.personas}
    total_share = sum(shares.values()) or 1.0
    report = SyntheticReport(
        title=f"Synthetic data: {content.get('title') or 'survey'}",
        decipher_artifact_id=survey.artifact_id,
        decipher_version=survey.version,
        sample_size=size,
        completes=len(simulation.respondents),
        attempts=simulation.attempts,
        terminated=simulation.terminated,
        seed=seed,
        personas=[
            PersonaCount(
                name=name,
                description=next((p.description for p in plan.personas if p.name == name), ""),
                target_share=shares.get(name, 1.0) / total_share,
                completes=count,
            )
            for name, count in counts.items()
        ],
        quotas=quota_counts,
        traits=_trait_links(plan, profiles),
        variable_count=len(frame.columns),
        profiled_questions=sum(spec.label in profiles for spec in answered),
        question_count=len(answered),
        answer_source=source,  # type: ignore[arg-type]
        dataset_id=dataset.id,
        dataset_active=active,
        export_file_id=file_id,
        warnings=_unique(warnings),
        checks=checks,
    )
    revision = artifacts.create(
        project_id=project_id,
        artifact_type="synthetic_data",
        name=report.title,
        content=report.model_dump(mode="json"),
        content_schema="synthetic_data/1",
        created_by="synthetic",
        validation_status=gate.status,
    )
    return {
        "summary": _summary(report, gate.status),
        "status": "completed" if gate.status != "failed" else "failed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "validation": gate.model_dump(mode="json"),
        "warnings": report.warnings[:5],
    }


def _stage(on_stage: Callable[[str], None] | None, message: str) -> None:
    """Send a stage message when the chat is listening."""
    if on_stage is not None:
        on_stage(message)


def _requirement(text: str, questionnaire: Any, purchase: Any) -> str:
    """Collect the sample requirement the planner reads.

    Args:
        text: User request.
        questionnaire: Latest questionnaire revision, or None.
        purchase: Latest sample quote revision, or None.

    Returns:
        Requirement text: the request first, then the questionnaire's sample notes, then the quote.
    """
    parts = [f"Request: {text.strip()}"]
    notes = list((questionnaire.content or {}).get("sample_notes") or []) if questionnaire else []
    if notes:
        parts.append("Questionnaire sample notes:\n" + "\n".join(f"- {note}" for note in notes))
    if purchase is not None:
        content = purchase.content or {}
        cells = [
            f"{' / '.join(cell.get('labels') or [])}: {cell.get('places')}"
            for cell in list(content.get("quota_cells") or [])
        ]
        parts.append(
            f"Panel quote: {content.get('sample_size')} completes, {content.get('description') or ''}"
            + (f". Cells: {'; '.join(cells)}" if cells else "")
        )
    return "\n\n".join(parts)


def _sample_size(text: str, questionnaire: Any, purchase: Any, plan: SurveyPlan) -> int | None:
    """Pick the number of completes: the request, then the quote, the notes, the plan.

    Args:
        text: User request.
        questionnaire: Latest questionnaire revision, or None.
        purchase: Latest sample quote revision, or None.
        plan: Model plan.

    Returns:
        Completes, capped, or None when no source states one.

    Raises:
        AppError: The size is above the limit.
    """
    match = _REQUEST_SIZE.search(text)
    size = int(match.group(1).replace(",", "")) if match else parse_request(text, []).sample_size
    if size is None and purchase is not None:
        size = int((purchase.content or {}).get("sample_size") or 0) or None
    if size is None and questionnaire is not None:
        for note in list((questionnaire.content or {}).get("sample_notes") or []):
            match = _NOTES_SIZE.search(str(note))
            if match:
                size = int(match.group(1).replace(",", ""))
                break
    if size is None and plan.sample_size:
        size = plan.sample_size
    if size is not None and size > _MAX_SIZE:
        raise AppError(
            f"Synthetic data is limited to {_MAX_SIZE} completes per run. Ask for a smaller sample.",
            "clarification_needed",
        )
    return size if size and size > 0 else None


def _register(
    db: Session, storage: Storage, settings: Settings, project_id: str, file_id: str
) -> tuple[Any, bool]:
    """Load the file as a dataset and make it active unless real data is active.

    Args:
        db: Session.
        storage: Project storage.
        settings: Settings.
        project_id: Project id.
        file_id: The stored ``.sav`` file.

    Returns:
        Dataset row, and whether it is now the active dataset.
    """
    project = ProjectRepository(db).get(project_id)
    previous = project.active_dataset_id
    dataset = ingest_spss(db, storage, settings, project_id, file_id)
    if previous and previous != dataset.id and _is_synthetic(db, previous):
        project.active_dataset_id = dataset.id
    return dataset, project.active_dataset_id == dataset.id


def _is_synthetic(db: Session, dataset_id: str) -> bool:
    """Return whether a dataset came from this generator."""
    dataset = DatasetRepository(db).get(dataset_id)
    if dataset is None or not dataset.source_file_id:
        return False
    stored = FileRepository(db).get(dataset.source_file_id)
    return stored.filename == _FILENAME


def _unique(items: list[str]) -> list[str]:
    """Drop repeated warnings."""
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


def _summary(report: SyntheticReport, status: str) -> str:
    """Write the chat reply from computed counts."""
    incidence = report.completes / report.attempts if report.attempts else 1.0
    personas = ", ".join(f"{item.name} ({item.completes})" for item in report.personas)
    quotas = "; ".join(
        f"{item.question} {item.label} {item.achieved}/{item.target}" for item in report.quotas
    )
    text = (
        f"Generated {report.completes} synthetic completes from Decipher survey v{report.decipher_version} "
        f"({report.variable_count} variables). {report.terminated} simulated respondents screened out "
        f"({incidence:.0%} incidence). Personas: {personas}. "
        + (f"Quotas: {quotas}. " if quotas else "No quotas were applied. ")
        + "The file is synthetic, not real fieldwork, and is ready to download as SPSS."
    )
    if report.dataset_active:
        text += " It is now the active dataset, so analysis and tables will use it."
    else:
        text += (
            " Real data stays the active dataset. Switch datasets to analyse the synthetic file."
        )
    if status == "failed":
        text = "The synthetic file did not pass its checks. " + text
    return text


def _trait_links(plan: SurveyPlan, profiles: dict) -> list[TraitLink]:
    """List each trait with the questions whose answers it moves.

    Args:
        plan: Plan with traits.
        profiles: Question profiles with loadings.

    Returns:
        One entry per trait, in plan order.
    """
    links: list[TraitLink] = []
    for trait in plan.traits:
        key = trait.name.strip().casefold()
        questions = [
            label
            for label, profile in profiles.items()
            if any(item.trait.strip().casefold() == key for item in profile.loadings)
        ]
        links.append(TraitLink(name=trait.name, description=trait.description, questions=questions))
    return links
