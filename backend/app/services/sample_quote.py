"""Price a Prolific audience and store the quote. This does not publish."""

import re

from sqlalchemy.orm import Session

from app.agents.sample_brief import propose_audience
from app.config import Settings
from app.engines.sample_audience import (
    AudienceProposal,
    api_filters,
    catalog_from_payload,
    filters_from_proposal,
    resolve_audience,
    validate_filters,
)
from app.engines.sample_parse import parse_request
from app.engines.sample_quota import planned_cells, reward_for_minutes, screenout_amount
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.sample_purchase import AudienceFilter, QuoteEdit, SamplePurchase
from app.services.prolific_client import ProlificClient
from app.services.sample_context import (
    _minutes,
    _money,
    _project_id,
    _require_key,
    _study_context,
    _workspace,
)

_ACCEPT = re.compile(
    r"\b(launch|publish|go ahead|price looks good|looks good|approve the price|field it)\b",
    re.I,
)
_CHANGE = re.compile(
    r"\b(change|instead|make it|increase to|decrease to|different audience)\b|"
    r"\bn\s*=\s*\d+|\b\d+\s+(?:respondents|participants|people|completes)\b|"
    r"\b\d+\s*-?\s*min",
    re.I,
)
_PAUSE = re.compile(r"\bpause\b", re.I)
_START = re.compile(r"\bresume\b|\bstart recruiting\b", re.I)
_STOP = re.compile(r"\bstop\b", re.I)


def sample_action(text: str) -> str:
    """Choose quote, launch, or a status change from the user message.

    Args:
        text: User message.

    Returns:
        ``quote``, ``launch``, ``pause``, ``start``, or ``stop``.
    """
    if _PAUSE.search(text):
        return "pause"
    if _START.search(text):
        return "start"
    if _STOP.search(text):
        return "stop"
    if _ACCEPT.search(text) and not _CHANGE.search(text):
        return "launch"
    return "quote"


async def quote_from_message(
    db: Session,
    settings: Settings,
    project_id: str,
    text: str,
    *,
    client: ProlificClient | None = None,
    proposal: AudienceProposal | None = None,
    session_id: str = "",
) -> dict:
    """Price the audience described in chat.

    Args:
        db: Session.
        settings: Application settings.
        project_id: Project id.
        text: User message.
        client: Prolific client. Tests pass a mock.
        proposal: Optional prebuilt proposal. Unknown filter ids are rejected.
        session_id: SDK session id for a catalog proposal.

    Returns:
        Summary and artifact id.

    Raises:
        AppError: The audience, sample size, or minutes are missing, or Prolific rejects a filter.
    """
    _require_key(settings)
    active = client or ProlificClient(settings)
    title, notes, question_count, survey_url = _study_context(db, project_id)
    parsed = parse_request(text, notes)
    catalog = catalog_from_payload(active.list_filters())
    filters, study_type, note = resolve_audience(parsed, catalog)
    if proposal is not None:
        filters, study_type, errors = filters_from_proposal(proposal, catalog)
        if errors:
            raise AppError(" ".join(errors), "prolific_rejected")
        note = ""
    elif not filters and not study_type and settings.llm_configured:
        suggested = await propose_audience(
            settings, text=f"{text}\n{chr(10).join(notes)}", catalog=catalog, session_id=session_id
        )
        filters, study_type, errors = filters_from_proposal(suggested, catalog)
        if errors:
            raise AppError(" ".join(errors), "prolific_rejected")
        if suggested.sample_size and parsed.sample_size is None:
            parsed.sample_size = suggested.sample_size
        if suggested.estimated_minutes and parsed.minutes is None:
            parsed.minutes = suggested.estimated_minutes
    if not filters and not study_type:
        raise AppError(
            "Say who to recruit, for example UK adults 18–65 or a US representative sample.",
            "clarification_needed",
        )
    if parsed.sample_size is None:
        raise AppError(
            "How many completed responses should this sample include?",
            "clarification_needed",
        )
    minutes, estimated = _minutes(parsed.minutes, question_count)
    return _price(
        db,
        project_id,
        active,
        settings,
        title=title,
        sample_size=parsed.sample_size,
        minutes=minutes,
        minutes_estimated=estimated,
        filters=filters,
        study_type=study_type,
        study_type_note=note,
        devices=parsed.devices,
        survey_url=survey_url,
        reward_cents=None,
    )


def quote_from_edit(
    db: Session,
    settings: Settings,
    project_id: str,
    edit: QuoteEdit,
    *,
    client: ProlificClient | None = None,
) -> dict:
    """Reprice a panel edit.

    Args:
        db: Session.
        settings: Application settings.
        project_id: Project id.
        edit: Sample size, minutes, reward, and filters.
        client: Prolific client.

    Returns:
        Summary and artifact id.

    Raises:
        AppError: A filter is not in the catalog, or the reward is below the minimum.
    """
    _require_key(settings)
    active = client or ProlificClient(settings)
    title, _notes, _count, survey_url = _study_context(db, project_id)
    catalog = catalog_from_payload(active.list_filters())
    errors = validate_filters(edit.filters, catalog)
    if errors:
        raise AppError(" ".join(errors), "prolific_rejected")
    return _price(
        db,
        project_id,
        active,
        settings,
        title=title,
        sample_size=edit.sample_size,
        minutes=edit.estimated_minutes,
        minutes_estimated=False,
        filters=edit.filters,
        study_type=edit.study_type,
        study_type_note="",
        devices=edit.devices or ["desktop", "tablet", "mobile"],
        survey_url=survey_url,
        reward_cents=edit.reward_cents,
    )


def _price(
    db: Session,
    project_id: str,
    client: ProlificClient,
    settings: Settings,
    *,
    title: str,
    sample_size: int,
    minutes: int,
    minutes_estimated: bool,
    filters: list[AudienceFilter],
    study_type: str | None,
    study_type_note: str,
    devices: list[str],
    survey_url: str | None,
    reward_cents: int | None,
) -> dict:
    """Call Prolific for eligibility, reward, cost, and balance, then save the quote.

    Args:
        db: Session.
        project_id: Project id.
        client: Prolific client.
        settings: Application settings.
        title: Participant-facing study name.
        sample_size: Completed places.
        minutes: Estimated minutes.
        minutes_estimated: Whether minutes were inferred from the question count.
        filters: Validated filters.
        study_type: Representative sample type, if used.
        study_type_note: Why a representative type was not applied.
        devices: Allowed devices.
        survey_url: Decipher survey URL, when one has been uploaded.
        reward_cents: Explicit reward. None uses the recommendation.

    Returns:
        Summary and artifact id.
    """
    workspace_id, currency, balance = _workspace(client, settings)
    recommendation = client.reward_recommendation(workspace_id, currency)
    minimum = int(recommendation.get("min_reward_per_hour") or 0)
    recommended = int(recommendation.get("recommended_reward_per_hour") or minimum)
    computed, raised = reward_for_minutes(recommended, minimum, minutes)
    warnings: list[str] = []
    if reward_cents is None:
        reward = computed
        if raised:
            warnings.append("The reward was raised to the workspace minimum hourly rate.")
    else:
        floor, _raised = reward_for_minutes(minimum, minimum, minutes)
        if reward_cents < floor:
            raise AppError(
                f"The reward is below the Prolific minimum for {minutes} minutes.",
                "prolific_rejected",
            )
        reward = reward_cents
    total = client.calculate_cost(reward, sample_size, workspace_id)
    eligible = (
        client.eligibility_count(api_filters(filters, weighted=False), workspace_id)
        if filters
        else 0
    )
    if study_type and not filters:
        eligible_note = (
            "Eligibility for a representative sample is confirmed when the draft is created."
        )
        eligible = eligible
    else:
        eligible_note = (
            "Fewer than 5 participants match. Prolific hides counts below 5."
            if eligible == 0
            else ""
        )
    available = balance.get("available_balance")
    available_cents = int(available) if isinstance(available, int | float) else None
    shortfall = None
    if available_cents is not None:
        shortfall = max(0, total - available_cents)
    screenout = screenout_amount(reward, minimum)
    purchase = SamplePurchase(
        name=title[:120] or "Survey",
        description=f"A survey: {title}."[:500],
        sample_size=sample_size,
        estimated_minutes=minutes,
        minutes_estimated=minutes_estimated,
        reward_cents=reward,
        reward_per_hour_cents=int(round(reward * 60 / minutes)),
        min_reward_per_hour_cents=minimum,
        currency=currency,
        participant_pay_cents=reward * sample_size,
        total_cost_cents=total,
        available_balance_cents=available_cents,
        shortfall_cents=shortfall,
        eligible_count=eligible,
        eligible_note=eligible_note,
        workspace_id=workspace_id,
        prolific_project_id=_project_id(client, settings, workspace_id),
        study_type=study_type,
        study_type_note=study_type_note,
        filters=filters,
        quota_cells=planned_cells(filters, sample_size),
        screenout_reward_cents=screenout,
        screenout_slots=sample_size,
        screenout_note=(
            "Screen-outs are not included in the total. Each screen-out pays a lower reward, "
            f"and that path pauses after {sample_size} screen-outs."
        ),
        devices=devices,
        decipher_survey_url=survey_url,
        decipher_ready=bool(survey_url),
        warnings=[*warnings, *([study_type_note] if study_type_note else [])],
    )
    if minutes_estimated:
        purchase.warnings.append(
            "Estimated time is one minute per question. Change it in the panel before launching."
        )
    purchase.launch_blockers = launch_blockers(purchase)
    revision = _save(db, project_id, purchase)
    return {
        "summary": _summary(purchase),
        "status": "completed_with_warnings" if purchase.warnings else "completed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "total_cost_cents": purchase.total_cost_cents,
    }


def launch_blockers(purchase: SamplePurchase) -> list[str]:
    """List the reasons a quote cannot be published.

    Args:
        purchase: Priced audience.

    Returns:
        Blocker messages. An empty list means launch can be attempted.
    """
    blockers: list[str] = []
    if not purchase.decipher_survey_url:
        blockers.append("Program and upload the Decipher survey before launching.")
    if purchase.filters and purchase.eligible_count == 0:
        blockers.append("Fewer than 5 participants match this audience.")
    if (purchase.shortfall_cents or 0) > 0:
        blockers.append("The workspace balance does not cover this total.")
    if purchase.screenout_reward_cents <= 0:
        blockers.append("The completion reward is too small to pay a lower screen-out reward.")
    return blockers


def _save(db: Session, project_id: str, purchase: SamplePurchase):
    """Store the quote as the latest sample purchase.

    Args:
        db: Session.
        project_id: Project id.
        purchase: Priced audience.

    Returns:
        New revision.
    """
    existing = ArtifactRepository(db).latest_of_type(project_id, "sample_purchase")
    if existing is not None:
        previous = SamplePurchase.model_validate(existing.content)
        if previous.prolific_study_id and purchase.prolific_study_id is None:
            purchase.prolific_study_id = previous.prolific_study_id
            purchase.prolific_status = previous.prolific_status
            purchase.status = previous.status
            purchase.completion_codes = previous.completion_codes
    return ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="sample_purchase",
        name=f"Prolific: {purchase.name}"[:300],
        content=purchase.model_dump(mode="json"),
        content_schema="sample_purchase/1",
        created_by="sample",
        validation_status="passed_with_warnings" if purchase.warnings else "passed",
        artifact_id=existing.artifact_id if existing else None,
        expected_version=existing.version if existing else None,
    )


def _summary(purchase: SamplePurchase) -> str:
    """Describe the quote without claiming it was published.

    Args:
        purchase: Priced audience.

    Returns:
        Chat summary.
    """
    audience = (
        purchase.study_type or ", ".join(item.label for item in purchase.filters) or "the audience"
    )
    money = _money(purchase.total_cost_cents, purchase.currency)
    text = (
        f"Prolific quote for {purchase.sample_size} completions ({audience}): {money} "
        "including fees and VAT. The quote is in the panel and has not been published."
    )
    if purchase.eligible_note:
        text += f" {purchase.eligible_note}"
    if purchase.launch_blockers:
        text += " " + purchase.launch_blockers[0]
    return text
