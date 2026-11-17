"""Keep the project's report plan current: from the questionnaire, then from the cleaned data."""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.engines.report.data_fit import fit_data
from app.engines.report.plan_rules import coverage, draft_plan, merge
from app.errors import AppError
from app.models.tables import Dataset
from app.repositories.records import ArtifactRepository, ProjectRepository
from app.schemas.questionnaire import Questionnaire
from app.schemas.report_plan import ReportPlan
from app.services.execute import load_frame
from app.services.storage import Storage

logger = logging.getLogger(__name__)
PLAN_TYPE = "report_plan"


def load_plan(db: Session, project_id: str) -> ReportPlan | None:
    """The saved plan, or None."""
    revision = ArtifactRepository(db).latest_of_type(project_id, PLAN_TYPE)
    return ReportPlan.model_validate(revision.content) if revision else None


def save_plan(
    db: Session, project_id: str, plan: ReportPlan, created_by: str = "report_planner"
) -> Any:
    """Write a new plan revision, creating the artifact the first time."""
    repo = ArtifactRepository(db)
    existing = repo.latest_of_type(project_id, PLAN_TYPE)
    return repo.create(
        project_id=project_id,
        artifact_type=PLAN_TYPE,
        name=f"Report plan: {plan.title}"[:200],
        content=plan.model_dump(mode="json"),
        content_schema="report_plan/1",
        created_by=created_by,
        artifact_id=existing.artifact_id if existing else None,
        expected_version=existing.version if existing else None,
        validation_status="passed",
    )


async def refresh_plan(
    db: Session,
    settings: Settings,
    project_id: str,
    *,
    session_id: str = "report-planner",
    stage: str = "",
    use_model: bool = True,
    storage: Storage | None = None,
) -> dict[str, Any]:
    """Draft or redraft the plan from the current questionnaire, keeping the user's edits.

    Args:
        db: Session.
        settings: Settings; the planner agent runs only with a model key.
        project_id: Project id.
        session_id: Model session.
        stage: Set the plan to this stage, such as ``questionnaire_final``.
        use_model: Let the planner agent refine the storyline.
        storage: Project storage, used to keep bases current once data exists.

    Returns:
        Task outcome with the plan artifact.

    Raises:
        AppError: The project has no questionnaire yet.
    """
    revision = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    if revision is None:
        raise AppError(
            "The report plan is built from the questionnaire. Draft one first.", "missing_roles"
        )
    questionnaire = Questionnaire.model_validate(revision.content)
    project = ProjectRepository(db).get(project_id)
    draft = draft_plan(questionnaire, project.study_context or {})
    notes: list[str] = []
    if use_model and settings.llm_configured:
        db.commit()
        try:
            from app.agents.report_planner import refine_plan

            draft, notes = await refine_plan(settings, draft, questionnaire, session_id)
        except Exception:
            logger.warning("Report planner agent failed; keeping the rules draft.", exc_info=True)
            notes.append(
                "The planner agent was not reachable, so the plan uses the standard storyline."
            )
    draft.questionnaire_ref = {"artifact_id": revision.artifact_id, "version": revision.version}
    old = load_plan(db, project_id)
    plan = merge(draft, old)
    if stage:
        plan.stage = stage  # type: ignore[assignment]
    plan = _refit(db, storage, plan, old)
    plan.coverage = coverage(plan, questionnaire)
    plan.notes = notes
    saved = save_plan(db, project_id, plan)
    return {
        "summary": _summary(plan, "Updated" if old else "Drafted"),
        "status": "completed",
        "artifact_id": saved.artifact_id,
        "version": saved.version,
    }


async def plan_with_data(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    conversation_id: str,
    on_stage: Callable[[str], None] | None = None,
    cleaning: str | None = None,
) -> dict[str, Any]:
    """Clean the active dataset, then fit the plan to it.

    The cleaning agent recommends removals and they are applied to a new dataset
    version; the uploaded file is never changed. A dataset that is already a
    cleaned copy is not cleaned again. Synthetic data skips cleaning unless the
    user asks for it, and real data can skip it when the user asks.

    Args:
        cleaning: "skip" or "run" to change the plan's cleaning choice; None keeps it.
    """
    from app.services.cleaning_run import apply_cleaning, run_cleaning
    from app.services.synthetic_run import is_synthetic

    stage = on_stage or (lambda _message: None)
    if cleaning in {"skip", "run"}:
        current = load_plan(db, project_id)
        if current is not None and current.cleaning != cleaning:
            current.cleaning = cleaning  # type: ignore[assignment]
            save_plan(db, project_id, current)
    if load_plan(db, project_id) is None:
        stage("Drafting the report plan from the questionnaire")
        await refresh_plan(
            db, settings, project_id, use_model=settings.llm_configured, storage=storage
        )
    project = ProjectRepository(db).get(project_id)
    if not project.active_dataset_id:
        raise AppError(
            "Upload the survey data (SPSS) first, then I can update the report plan.",
            "missing_dataset",
        )
    dataset = db.get(Dataset, project.active_dataset_id)
    raw_n = int(dataset.row_count or 0)
    choice = load_plan(db, project_id).cleaning
    synthetic = is_synthetic(db, dataset.id)
    cleaning_note = "The data was already a cleaned copy, so it was not cleaned again."
    removed = 0
    skipped = choice == "skip" or (choice == "auto" and synthetic)
    if skipped:
        cleaning_note = (
            "Synthetic data, so the cleaning step was skipped. Ask me to clean the data for the "
            "report to run it anyway."
            if synthetic and choice == "auto"
            else "Data cleaning was skipped at your request."
        )
    elif int(dataset.version or 1) <= 1:
        stage("Checking respondents for fraud, speeding and straight-lining")
        await run_cleaning(db, storage, settings, project_id, conversation_id, on_stage=on_stage)
        stage("Removing the respondents the cleaning agent flagged")
        applied = apply_cleaning(db, storage, project_id)
        cleaning_note = applied["summary"]
        project = ProjectRepository(db).get(project_id)
        cleaned = db.get(Dataset, project.active_dataset_id)
        removed = raw_n - int(cleaned.row_count or 0)
        dataset = cleaned
    stage("Checking bases for every planned slide")
    frame = load_frame(storage, dataset)
    plan = load_plan(db, project_id)
    plan.data.dataset_id = dataset.id
    plan.data.raw_n = raw_n
    plan.data.removed_by_cleaning = removed
    plan.data.final_n = int(len(frame))
    plan.data.weight_variable = project.default_weight_variable or ""
    plan.data.cleaning_summary = cleaning_note
    plan.data.synthetic = synthetic
    plan = fit_data(plan, frame, list(dataset.variables or []))
    plan.stage = "data_ready"
    revision = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    if revision is not None:
        plan.coverage = coverage(plan, Questionnaire.model_validate(revision.content))
    saved = save_plan(db, project_id, plan)
    flagged = [s for s in plan.all_slides() if s.status in {"needs_data", "low_base"}]
    opening = (
        f"{cleaning_note} Updated the report plan for {plan.data.final_n} respondents"
        if skipped
        else f"Cleaned the data ({removed} respondents removed, {plan.data.final_n} remain) and "
        "updated the report plan"
    )
    summary = (
        f"{opening}: "
        f"{len(plan.all_slides())} slides, {len(flagged)} flagged for missing data or low bases. "
        "Review and edit the plan, then ask me to generate the report."
    )
    return {
        "summary": summary,
        "status": "completed_with_warnings" if flagged else "completed",
        "artifact_id": saved.artifact_id,
        "version": saved.version,
    }


def _refit(
    db: Session, storage: Storage | None, plan: ReportPlan, old: ReportPlan | None
) -> ReportPlan:
    """Keep bases current when the plan is redrafted after data already arrived."""
    if storage is None or old is None or not old.data.dataset_id:
        return plan
    dataset = db.get(Dataset, old.data.dataset_id)
    if dataset is None:
        return plan
    try:
        return fit_data(plan, load_frame(storage, dataset), list(dataset.variables or []))
    except Exception:
        logger.warning("Could not refit the plan to the data.", exc_info=True)
        return plan


def _summary(plan: ReportPlan, verb: str) -> str:
    slides = [s for s in plan.all_slides() if s.status != "dropped"]
    analysis = sum(1 for s in slides if s.kind == "analysis")
    uncovered = [row.question_id for row in plan.coverage if not row.slide_ids]
    return (
        f"{verb} the report plan: {len(plan.sections)} sections, {len(slides)} slides "
        f"({analysis} advanced analyses). {len(uncovered)} questions are not reported, each with a reason. "
        "Open the plan to edit it."
    )
