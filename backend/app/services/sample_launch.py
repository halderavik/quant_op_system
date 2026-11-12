"""Publish a confirmed Prolific quote against the programmed Decipher survey."""

import json
import secrets

from sqlalchemy.orm import Session

from app.config import Settings
from app.engines.prolific_redirect import add_prolific_source, entry_url
from app.engines.sample_audience import api_filters, has_weightings
from app.errors import AppError
from app.models.tables import Artifact
from app.repositories.records import ArtifactRepository
from app.schemas.sample_purchase import QuoteEdit, SamplePurchase
from app.services.decipher_launch import SurveyLauncher, launcher_from_settings
from app.services.prolific_client import ProlificClient
from app.services.sample_context import _money, _require_key
from app.services.sample_quote import _save, launch_blockers, quote_from_edit
from app.services.storage import Storage
from app.services.stored_files import _write_export

_STATUS = {
    "UNPUBLISHED": "draft",
    "PUBLISHING": "publishing",
    "ACTIVE": "active",
    "PAUSED": "paused",
    "AWAITING REVIEW": "awaiting_review",
    "COMPLETED": "completed",
}


def launch_sample(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    confirmed_total: int,
    *,
    client: ProlificClient | None = None,
    launcher: SurveyLauncher | None = None,
) -> dict:
    """Publish the saved quote when the live total still matches.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings.
        project_id: Project id.
        confirmed_total: Total the user confirmed, in cents or pence.
        client: Prolific client.
        launcher: Decipher uploader. Tests pass a fake.

    Returns:
        Summary and artifact id. A price change is saved and not published.

    Raises:
        AppError: The quote cannot be launched, or Prolific or Decipher rejects a required step.
    """
    _require_key(settings)
    active = client or ProlificClient(settings)
    current = _load(db, project_id)
    if current.status not in {"quoted", "draft"}:
        raise AppError(
            "This sample is already on Prolific. Pause, resume, or stop it from the panel.",
            "prolific_rejected",
        )
    edit = QuoteEdit(
        sample_size=current.sample_size,
        estimated_minutes=current.estimated_minutes,
        reward_cents=current.reward_cents,
        filters=current.filters,
        study_type=current.study_type,
        devices=current.devices,
    )
    quote_from_edit(db, settings, project_id, edit, client=active)
    purchase = _load(db, project_id)
    if purchase.total_cost_cents != confirmed_total:
        shown = _money(purchase.total_cost_cents, purchase.currency)
        return _outcome(
            db,
            project_id,
            purchase,
            f"The price is now {shown}. It was not published. Review the panel before launching.",
            launched=False,
        )
    blockers = launch_blockers(purchase)
    if blockers:
        raise AppError(blockers[0], "prolific_rejected")
    if purchase.prolific_study_id and purchase.completion_codes:
        return _publish_existing(db, project_id, active, purchase, confirmed_total)
    codes = {
        "qualified": secrets.token_hex(4).upper(),
        "terminated": secrets.token_hex(4).upper(),
        "overquota": secrets.token_hex(4).upper(),
    }
    uploaded = _upload_redirects(db, storage, settings, project_id, purchase, codes, launcher)
    purchase.decipher_survey_url = uploaded.survey_url or purchase.decipher_survey_url
    purchase.completion_codes = codes
    try:
        created = active.create_study(_study_body(project_id, purchase, uploaded.survey_url or ""))
    except AppError as exc:
        if "screen" in exc.message.lower():
            purchase.warnings.append(
                "Prolific did not accept screen-out pay on this workspace. "
                "The study was not published."
            )
            return _outcome(db, project_id, purchase, purchase.warnings[-1], launched=False)
        raise
    study_id = str(created["id"])
    purchase.prolific_study_id = study_id
    purchase.prolific_status = str(created.get("status") or "UNPUBLISHED")
    purchase.status = "draft"
    _apply_breakdown(purchase, active.study_cost(study_id))
    refusal = _publish_refusal(purchase, created, confirmed_total)
    if refusal:
        purchase.warnings.append(refusal)
        return _outcome(db, project_id, purchase, refusal, launched=False)
    try:
        transitioned = active.transition(study_id, "PUBLISH")
    except AppError as exc:
        purchase.warnings.append(exc.message)
        return _outcome(db, project_id, purchase, exc.message, launched=False)
    status = str(transitioned.get("status") or "ACTIVE")
    purchase.prolific_status = status
    purchase.status = _STATUS.get(status, "publishing")
    purchase.submission_counts = active.submission_counts(study_id)
    summary = (
        f"Published the Prolific study {study_id} for {purchase.sample_size} completions. "
        f"The locked total is {_money(purchase.total_cost_cents, purchase.currency)}."
    )
    return _outcome(db, project_id, purchase, summary, launched=True)


def _publish_existing(
    db: Session,
    project_id: str,
    client: ProlificClient,
    purchase: SamplePurchase,
    confirmed_total: int,
) -> dict:
    """Publish a draft that was created earlier and not published.

    Args:
        db: Session.
        project_id: Project id.
        client: Prolific client.
        purchase: Draft quote.
        confirmed_total: Total the user confirmed.

    Returns:
        Outcome dictionary.
    """
    study_id = purchase.prolific_study_id or ""
    created = client.get_study(study_id)
    _apply_breakdown(purchase, client.study_cost(study_id))
    refusal = _publish_refusal(purchase, created, confirmed_total)
    if refusal:
        purchase.warnings.append(refusal)
        return _outcome(db, project_id, purchase, refusal, launched=False)
    try:
        transitioned = client.transition(study_id, "PUBLISH")
    except AppError as exc:
        purchase.warnings.append(exc.message)
        return _outcome(db, project_id, purchase, exc.message, launched=False)
    status = str(transitioned.get("status") or "ACTIVE")
    purchase.prolific_status = status
    purchase.status = _STATUS.get(status, "publishing")
    purchase.submission_counts = client.submission_counts(study_id)
    summary = (
        f"Published the Prolific study {study_id} for {purchase.sample_size} completions. "
        f"The locked total is {_money(purchase.total_cost_cents, purchase.currency)}."
    )
    return _outcome(db, project_id, purchase, summary, launched=True)


def transition_sample(
    db: Session,
    settings: Settings,
    project_id: str,
    action: str,
    *,
    client: ProlificClient | None = None,
) -> dict:
    """Pause, resume, or stop the Prolific study.

    Args:
        db: Session.
        settings: Application settings.
        project_id: Project id.
        action: PAUSE, START, or STOP.
        client: Prolific client.

    Returns:
        Summary and artifact id.

    Raises:
        AppError: No study has been created.
    """
    _require_key(settings)
    purchase = _load(db, project_id)
    if not purchase.prolific_study_id:
        raise AppError("There is no Prolific study to update.", "clarification_needed")
    active = client or ProlificClient(settings)
    body = active.transition(purchase.prolific_study_id, action)
    status = str(body.get("status") or "")
    purchase.prolific_status = status
    purchase.status = _STATUS.get(status, purchase.status)
    purchase.submission_counts = active.submission_counts(purchase.prolific_study_id)
    summary = f"The Prolific study is now {status or action}."
    return _outcome(db, project_id, purchase, summary, launched=purchase.status == "active")


def refresh_sample(
    db: Session,
    settings: Settings,
    project_id: str,
    *,
    client: ProlificClient | None = None,
) -> dict:
    """Read the live study status and submission counts.

    Args:
        db: Session.
        settings: Application settings.
        project_id: Project id.
        client: Prolific client.

    Returns:
        Summary and artifact id.

    Raises:
        AppError: No study has been created.
    """
    _require_key(settings)
    purchase = _load(db, project_id)
    if not purchase.prolific_study_id:
        raise AppError("There is no Prolific study to refresh.", "clarification_needed")
    active = client or ProlificClient(settings)
    body = active.get_study(purchase.prolific_study_id)
    status = str(body.get("status") or purchase.prolific_status or "")
    purchase.prolific_status = status
    purchase.status = _STATUS.get(status, purchase.status)
    purchase.submission_counts = active.submission_counts(purchase.prolific_study_id)
    filled = purchase.submission_counts.get("APPROVED", 0)
    summary = f"The Prolific study is {status or 'unchanged'}. {filled} submissions are approved."
    return _outcome(db, project_id, purchase, summary, launched=purchase.status == "active")


def _upload_redirects(db, storage, settings, project_id, purchase, codes, launcher):
    """Patch the survey XML and upload it.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings.
        project_id: Project id.
        purchase: Quote.
        codes: Completion codes.
        launcher: Decipher uploader.

    Returns:
        Upload result.

    Raises:
        AppError: The survey XML is missing or Decipher is not configured.
    """
    row = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    content = row.content if row is not None and isinstance(row.content, dict) else {}
    xml = content.get("xml")
    if not isinstance(xml, str) or not xml.strip():
        raise AppError(
            "Program and upload the Decipher survey before launching.",
            "clarification_needed",
        )
    patched = add_prolific_source(xml, codes)
    uploader = launcher
    if uploader is None:
        if not settings.decipher_api_key.strip():
            raise AppError(
                "Decipher API is not configured. Upload the survey before launching the sample.",
                "decipher_not_configured",
            )
        uploader = launcher_from_settings(settings)
    path = content.get("survey_path")
    result = uploader.launch(
        patched,
        purchase.name,
        survey_path=path if isinstance(path, str) else None,
    )
    file_id = _write_export(
        db,
        storage,
        project_id,
        "survey.xml",
        (result.xml or patched).encode("utf-8"),
        "application/xml",
    )
    stored = dict(content)
    stored.update(
        {
            "xml": result.xml or patched,
            "file_id": file_id,
            "survey_path": result.survey_path,
            "survey_url": result.survey_url,
            "launch": "uploaded",
            "launch_message": result.message,
        }
    )
    label = "Decipher survey"
    if row is not None:
        artifact = db.get(Artifact, row.artifact_id)
        if artifact is not None and artifact.name:
            label = artifact.name
    ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="decipher_survey",
        name=label,
        content=stored,
        content_schema=row.content_schema if row is not None else "decipher/1",
        created_by="sample",
        validation_status=row.validation_status if row is not None else "passed",
        artifact_id=row.artifact_id if row is not None else None,
        expected_version=row.version if row is not None else None,
    )
    return result


def _study_body(project_id: str, purchase: SamplePurchase, survey_url: str) -> dict:
    """Build the unpublished study payload.

    Args:
        project_id: Studio project id.
        purchase: Quote.
        survey_url: Decipher survey URL.

    Returns:
        Create-study body.
    """
    screen = purchase.screenout_reward_cents
    slots = purchase.sample_size
    screen_action = {
        "action": "FIXED_SCREEN_OUT_PAYMENT",
        "fixed_screen_out_reward": screen,
        "slots": slots,
    }
    body = {
        "name": purchase.name,
        "description": purchase.description,
        "external_study_url": entry_url(survey_url),
        "prolific_id_option": "url_parameters",
        "total_available_places": purchase.sample_size,
        "estimated_completion_time": purchase.estimated_minutes,
        "reward": purchase.reward_cents,
        "internal_name": f"SRAS {project_id}"[:120],
        "completion_codes": [
            {
                "code": purchase.completion_codes["qualified"],
                "code_type": "COMPLETED",
                "actions": [{"action": "AUTOMATICALLY_APPROVE"}],
            },
            {
                "code": purchase.completion_codes["terminated"],
                "code_type": "FIXED_SCREENOUT",
                "actions": [screen_action],
            },
            {
                "code": purchase.completion_codes["overquota"],
                "code_type": "SCREENED_OUT",
                "actions": [dict(screen_action)],
            },
        ],
        "device_compatibility": purchase.devices,
        "peripheral_requirements": [],
        "filters": api_filters(purchase.filters),
        "submissions_config": {"max_submissions_per_participant": 1},
        "study_labels": ["survey"],
        "metadata": json.dumps({"studio_project_id": project_id}),
    }
    if purchase.prolific_project_id:
        body["project"] = purchase.prolific_project_id
    if purchase.study_type:
        body["study_type"] = purchase.study_type
    elif has_weightings(purchase.filters):
        # Reason: Prolific refuses weighted filters on the default SINGLE study type.
        body["study_type"] = "QUOTA"
    return body


def _publish_refusal(purchase: SamplePurchase, created: dict, confirmed_total: int) -> str:
    """Return why the draft must stay unpublished.

    Args:
        purchase: Quote, updated with the projected breakdown when present.
        created: Created study.
        confirmed_total: Total the user confirmed.

    Returns:
        A refusal message, or an empty string when publish can continue.
    """
    if created.get("is_ready_to_publish") is False:
        return "Prolific did not mark the draft ready to publish."
    minimum = created.get("minimum_reward_per_hour")
    hourly = purchase.reward_cents * 60 / purchase.estimated_minutes
    if isinstance(minimum, int | float) and hourly < float(minimum):
        return (
            "Prolific's minimum for these filters is higher than the quoted reward. "
            "The draft was not published."
        )
    if purchase.rewards_cents is not None and purchase.total_cost_cents != confirmed_total:
        shown = _money(purchase.total_cost_cents, purchase.currency)
        return f"The projected study cost is {shown}, which does not match the confirmed total."
    return ""


def _apply_breakdown(purchase: SamplePurchase, payload: dict) -> None:
    """Copy rewards, fees, and tax onto the quote when Prolific returned them.

    Args:
        purchase: Quote.
        payload: Projected cost.
    """
    rewards = _amount(payload, "rewards", "rewards")
    fees = _amount(payload, "rewards", "fees")
    tax = _amount(payload, "rewards", "tax")
    if rewards is None and fees is None and tax is None:
        return
    purchase.rewards_cents = rewards or 0
    purchase.fees_cents = fees or 0
    purchase.tax_cents = tax or 0
    purchase.total_cost_cents = purchase.rewards_cents + purchase.fees_cents + purchase.tax_cents


def _amount(payload: dict, section: str, key: str) -> int | None:
    """Read one cost amount.

    Args:
        payload: Cost object.
        section: rewards or bonuses.
        key: rewards, fees, or tax.

    Returns:
        Amount, or None when it is absent.
    """
    block = payload.get(section)
    if not isinstance(block, dict):
        return None
    value = block.get(key)
    if not isinstance(value, dict):
        return None
    amount = value.get("amount")
    if isinstance(amount, int | float):
        return int(round(amount))
    return None


def _load(db: Session, project_id: str) -> SamplePurchase:
    """Load the latest quote.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        Quote.

    Raises:
        AppError: No quote has been saved.
    """
    row = ArtifactRepository(db).latest_of_type(project_id, "sample_purchase")
    if row is None:
        raise AppError(
            "Price the sample before launching it.",
            "clarification_needed",
        )
    return SamplePurchase.model_validate(row.content)


def _outcome(
    db: Session, project_id: str, purchase: SamplePurchase, summary: str, launched: bool
) -> dict:
    """Save the purchase and return the chat outcome.

    Args:
        db: Session.
        project_id: Project id.
        purchase: Quote or published study.
        summary: User-facing summary.
        launched: Whether publish succeeded.

    Returns:
        Outcome dictionary.
    """
    purchase.launch_blockers = [] if launched else launch_blockers(purchase)
    revision = _save(db, project_id, purchase)
    return {
        "summary": summary,
        "status": "completed" if launched else "completed_with_warnings",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "launched": launched,
        "total_cost_cents": purchase.total_cost_cents,
    }
