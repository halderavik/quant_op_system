"""Live quality: bot and fraud results for a project's Decipher survey, read from the bot-detection API."""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import Settings
from app.engines.decipher_tracking import survey_id_from_name
from app.errors import AppError
from app.repositories.records import ArtifactRepository, ProjectRepository
from app.services.quality_rules import QualityRules, get_rules

logger = logging.getLogger(__name__)

_CACHE_SECONDS = 4.0
_IN_PROGRESS = timedelta(minutes=20)
# Raw service reports per survey id; rules are applied on every read.
_CACHE: dict[
    str, tuple[float, tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]]
] = {}
# Reason: a session's stored events only change while it is active; key by last activity.
_EXTRAS: dict[str, tuple[str, dict[str, Any]]] = {}
# Reason: event details cost one call per session; very large surveys read only the newest.
_EXTRAS_LIMIT = 300


def tracking_settings(db: Session, project_id: str) -> dict[str, Any]:
    """Return the project's live-quality settings.

    The tracking id is the project name. Once a survey has been programmed in Decipher
    with an id, that id is kept, so renaming the project does not split its responses.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        ``enabled``, the ``survey_id`` in use, the ``name_id`` from the current project
        name, and ``fielded`` (whether the Decipher XML already carries ``survey_id``).
    """
    project = ProjectRepository(db).get(project_id)
    current = (project.study_context or {}).get("live_quality") or {}
    stored = str(current.get("survey_id") or "")
    name_id = survey_id_from_name(project.name)
    revision = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    fielded = (
        bool(stored)
        and revision is not None
        and ((revision.content or {}).get("tracking_survey_id") == stored)
    )
    return {
        "enabled": bool(current.get("enabled")),
        "survey_id": stored if fielded else name_id,
        "name_id": name_id,
        "fielded": fielded,
    }


def set_tracking(
    db: Session, project_id: str, enabled: bool, use_project_name: bool = False
) -> dict[str, Any]:
    """Turn tracking on or off.

    Args:
        db: Session.
        project_id: Project id.
        enabled: Whether the next Decipher programming adds tracking.
        use_project_name: Switch a fielded survey to the current project name. Its
            next programming sends new responses under that name.

    Returns:
        The new settings.
    """
    project = ProjectRepository(db).get(project_id)
    context = dict(project.study_context or {})
    current = dict(context.get("live_quality") or {})
    current["enabled"] = enabled
    if use_project_name:
        current["survey_id"] = survey_id_from_name(project.name)
    context["live_quality"] = current
    project.study_context = context
    flag_modified(project, "study_context")
    db.flush()
    return tracking_settings(db, project_id)


def remember_survey_id(db: Session, project_id: str, survey_id: str) -> None:
    """Record the tracking id a Decipher programming used.

    Args:
        db: Session.
        project_id: Project id.
        survey_id: Tracking id written into the XML.
    """
    project = ProjectRepository(db).get(project_id)
    context = dict(project.study_context or {})
    current = dict(context.get("live_quality") or {})
    current["survey_id"] = survey_id
    context["live_quality"] = current
    project.study_context = context
    flag_modified(project, "study_context")
    db.flush()


def decipher_status(db: Session, project_id: str, survey_id: str) -> dict[str, Any]:
    """Describe the project's Decipher survey and whether it carries this tracking id.

    Args:
        db: Session.
        project_id: Project id.
        survey_id: Tracking survey id.

    Returns:
        Survey link, path, whether it is live in Decipher, and whether tracking is in the XML.
    """
    revision = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    content = revision.content if revision is not None else {}
    return {
        "programmed": revision is not None,
        "survey_url": content.get("survey_url"),
        "survey_path": content.get("survey_path"),
        "uploaded": content.get("launch") == "uploaded",
        "tracking_in_xml": bool(survey_id) and content.get("tracking_survey_id") == survey_id,
        "has_questionnaire": ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
        is not None,
    }


async def live_results(
    settings: Settings, survey_id: str, rules: QualityRules | None = None
) -> dict[str, Any]:
    """Fetch and summarize live results for one tracking id.

    Args:
        settings: Application settings.
        survey_id: Tracking survey id.
        rules: Quality rules to apply; defaults when None.

    Returns:
        Totals, per-check summaries, and one row per session, newest first.

    Raises:
        AppError: The bot-detection API could not be reached.
    """
    cached = _CACHE.get(survey_id)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return summarize(survey_id, *cached[1], rules=rules)
    base = settings.bot_detection_api_base.rstrip("/")
    params = {"include_inactive": "true"}
    async with httpx.AsyncClient(timeout=45) as http:
        try:
            summary, detailed = await asyncio.gather(
                http.get(f"{base}/reports/summary/{quote(survey_id, safe='')}", params=params),
                http.get(f"{base}/reports/detailed/{quote(survey_id, safe='')}", params=params),
            )
        except httpx.HTTPError as exc:
            raise AppError(
                f"The bot-detection service could not be reached ({exc.__class__.__name__}).",
                "live_quality_unreachable",
                502,
            ) from None
    if summary.status_code == 404 or detailed.status_code == 404:
        raw: tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]] = (
            {},
            {"respondents": []},
            {},
        )
    elif summary.status_code >= 400 or detailed.status_code >= 400:
        raise AppError(
            "The bot-detection service could not build the report for this survey "
            f"(HTTP {max(summary.status_code, detailed.status_code)}). Very large surveys can fail there.",
            "live_quality_error",
            502,
        )
    else:
        detail = detailed.json()
        extras = await _session_extras(base, detail.get("respondents") or [])
        raw = (summary.json(), detail, extras)
    _CACHE[survey_id] = (time.monotonic(), raw)
    return summarize(survey_id, *raw, rules=rules)


async def _session_extras(base: str, respondents: list[Any]) -> dict[str, dict[str, Any]]:
    """Read page timing and grid answers the tracker stored in each session's events.

    The tracker writes ``qos-page:<ms>`` and ``qos-grid:<v1,v2,...>`` into the element id of
    form_submit events, because the API keeps only a fixed set of event fields.

    Args:
        base: Bot-detection API base URL.
        respondents: Detailed-report rows.

    Returns:
        Session id to ``{"pages": [ms, ...], "grids": [[values], ...]}``.
    """
    newest = sorted(
        (item for item in respondents if isinstance(item, dict) and item.get("session_id")),
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )[:_EXTRAS_LIMIT]
    wanted = [
        (str(item.get("session_id")), str(item.get("last_activity") or "")) for item in newest
    ]
    missing = [(sid, last) for sid, last in wanted if _EXTRAS.get(sid, ("", {}))[0] != last]
    if missing:
        gate = asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=30) as http:

            async def _one(sid: str, last: str) -> None:
                async with gate:
                    try:
                        response = await http.get(f"{base}/dashboard/sessions/{sid}/details")
                    except httpx.HTTPError:
                        return
                if response.status_code == 200:
                    _EXTRAS[sid] = (last, parse_events(response.json().get("behavior_data") or []))

            await asyncio.gather(*(_one(sid, last) for sid, last in missing))
    return {sid: _EXTRAS[sid][1] for sid, _ in wanted if sid in _EXTRAS}


def parse_events(events: list[Any]) -> dict[str, Any]:
    """Pull page times and grid answers out of stored events.

    Args:
        events: ``behavior_data`` rows from the session details endpoint.

    Returns:
        ``{"pages": [ms, ...], "grids": [[values], ...], "events": n}``. Repeated sends count once.
    """
    pages: list[int] = []
    grids: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") != "form_submit":
            continue
        element = str(event.get("element_id") or "")
        key = (str(event.get("timestamp") or ""), element)
        if key in seen:
            continue
        seen.add(key)
        if element.startswith("qos-page:"):
            try:
                pages.append(int(element.split(":", 1)[1]))
            except ValueError:
                continue
        elif element.startswith("qos-grid:"):
            values = [value for value in element.split(":", 1)[1].split(",") if value]
            if values:
                grids.append(values)
    return {"pages": pages, "grids": grids, "events": len(events)}


def _empty(survey_id: str) -> dict[str, Any]:
    """Return results for a survey nobody has started.

    Args:
        survey_id: Tracking survey id.

    Returns:
        Zero totals and no rows.
    """
    return summarize(survey_id, {}, {"respondents": []})


def _when(value: Any) -> datetime | None:
    """Parse an ISO timestamp.

    Args:
        value: ISO string.

    Returns:
        Aware datetime or None.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _mark_speeders(rows: list[dict[str, Any]], rules: QualityRules) -> None:
    """Flag speeders from page times.

    A respondent is a speeder when pages average under ``speeder_page_seconds``, or,
    once five or more checked respondents have timings, when their total time is
    under ``speeder_median_share`` of the median (0 turns that check off).

    Args:
        rows: Dashboard rows. Changed in place.
        rules: Quality rules.
    """
    timed = sorted(
        row["seconds"] for row in rows if row["status"] == "checked" and row.get("seconds")
    )
    median = timed[len(timed) // 2] if len(timed) >= 5 else None
    for row in rows:
        seconds, pages = row.get("seconds"), row.get("pages") or 0
        if not seconds or not pages:
            continue
        fast = seconds / pages < rules.speeder_page_seconds
        share = rules.speeder_median_share
        if median and share and row["status"] == "checked" and seconds < share * median:
            fast = True
        if fast and not row["speeder"]:
            row["speeder"] = True
            row["flags"].append("Speeder")
            row["timing_explanation"] = row.get("timing_explanation") or (
                f"Answered {pages} pages in {seconds:.0f} seconds."
            )


# Text reasons the rules can switch off; others the service reports always count.
TEXT_REASON_CODES = ("gibberish", "generic", "irrelevant", "copy_paste", "low_quality")


def _bot_verdict(item: dict[str, Any], rules: QualityRules) -> tuple[bool, list[str]]:
    """Decide bot or human under the project's rules.

    The service reports the behaviour score before decisive signals raised it
    (``base_score``) and which signals fired (``decisive_codes``). A respondent is a
    bot when the base score reaches the threshold or an enabled signal fired. Rows
    from older service versions fall back to the reported score.

    Args:
        item: Detailed-report respondent.
        rules: Quality rules.

    Returns:
        Whether the respondent is a bot, and the enabled signals that fired.
    """
    patterns = item.get("flagged_patterns") or {}
    codes = [code for code in patterns.get("decisive_codes") or [] if code in rules.bot_signals]
    base = patterns.get("base_score")
    if base is None:
        base = item.get("confidence_score")
    try:
        score = float(base)
    except (TypeError, ValueError):
        return bool(item.get("is_bot")), codes
    return score >= rules.bot_threshold or bool(codes), codes


def _bot_risk(confidence: Any, is_bot: bool) -> str:
    """Behaviour risk, at least ``high`` for a respondent judged a bot."""
    risk = behaviour_risk(confidence)
    return "high" if is_bot and risk in {"low", "medium", "unknown"} else risk


def behaviour_risk(confidence: Any) -> str:
    """Map the behavioural bot score to a risk level.

    Args:
        confidence: Bot score from 0 (human) to 1 (bot).

    Returns:
        ``high`` from 0.7, ``medium`` from 0.5, otherwise ``low``.
    """
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return "unknown"
    if score >= 0.7:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _row(
    item: dict[str, Any],
    now: datetime,
    extra: dict[str, Any] | None = None,
    rules: QualityRules | None = None,
) -> dict[str, Any]:
    """Turn one detailed-report respondent into a dashboard row.

    Args:
        item: RespondentDetail from the bot-detection API.
        now: Current time.
        extra: Page times and grid answers read from the session's events.
        rules: Quality rules; defaults when None.

    Returns:
        Row with status, verdict, scores, flags, and explanations.
    """
    extra = extra or {}
    rules = rules or QualityRules()
    pages = [int(ms) for ms in extra.get("pages") or []]
    grids = extra.get("grids") or []
    straight = [
        values
        for values in grids
        if len(values) >= rules.straightline_min_rows and len(set(values)) == 1
    ]
    risk = str(item.get("risk_level") or "unknown")
    checked = risk.lower() != "unknown"
    last = _when(item.get("last_activity")) or _when(item.get("created_at"))
    if checked:
        status = "checked"
    elif last and now - last < _IN_PROGRESS:
        status = "in_progress"
    else:
        status = "dropped"
    flags: list[str] = []
    is_bot, signals = _bot_verdict(item, rules)
    if is_bot:
        flags.append("Bot-like behaviour")
    entries = item.get("text_responses_of_interest") or []
    entry_reasons = [
        set((entry.get("flag_reasons") or {}).keys())
        for entry in entries
        if entry.get("is_flagged")
    ]
    counted = set(rules.text_reasons)
    if entries:
        low_quality = any(
            (not reasons)
            or (reasons & counted)
            or (reasons - _ENTRY_REASONS - set(TEXT_REASON_CODES))
            for reasons in entry_reasons
        )
    else:
        low_quality = (item.get("flagged_text_responses") or 0) > 0
    if low_quality:
        flags.append("Low-quality open ends")
    if rules.flag_pasted and any(reasons & _ENTRY_REASONS for reasons in entry_reasons):
        flags.append("Pasted answers")
    if rules.flag_duplicates and item.get("is_duplicate"):
        flags.append("Duplicate")
    fraud_score = item.get("fraud_score")
    if fraud_score is not None:
        high_fraud = float(fraud_score) >= rules.fraud_threshold
    else:
        high_fraud = str(item.get("fraud_risk_level") or "").upper() in {"HIGH", "CRITICAL"}
    if high_fraud:
        flags.append("High fraud risk")
    datacenter = (item.get("fraud_flag_reasons") or {}).get("datacenter_ip")
    if rules.flag_datacenter and datacenter:
        flags.append("Data-centre IP")
    if item.get("timing_flatliner"):
        flags.append("Flatliner")
    straight_lining = bool(item.get("grid_straight_lining")) or bool(straight)
    if straight_lining:
        flags.append("Straight-lining")
    return {
        "session_id": item.get("session_id"),
        "respondent_id": item.get("respondent_id"),
        "started": item.get("created_at"),
        "last_activity": item.get("last_activity"),
        "minutes": item.get("session_duration_minutes"),
        "events": item.get("total_events") or 0,
        "status": status,
        "verdict": ("bot" if is_bot else "human") if checked else "pending",
        "bot_signals": signals,
        "confidence": item.get("confidence_score"),
        # Reason: the service labels low-scoring humans "high" risk, so derive it from the score.
        "risk": _bot_risk(item.get("confidence_score"), is_bot) if checked else "unknown",
        "service_risk": risk,
        "text_responses": item.get("text_response_count") or 0,
        "text_quality": item.get("avg_text_quality_score"),
        "text_flagged": item.get("flagged_text_responses") or 0,
        "low_quality_text": low_quality,
        "fraud_score": item.get("fraud_score"),
        "duplicate": bool(item.get("is_duplicate")),
        "fraud_risk": item.get("fraud_risk_level"),
        "straight_lining": straight_lining,
        "grid_variance": item.get("grid_variance_score"),
        "grids": grids,
        "pages": len(pages),
        "seconds": round(sum(pages) / 1000, 1) if pages else None,
        # Set from page times by _mark_speeders; the service's per-answer timing
        # counts a quick short open end as a speeder.
        "speeder": False,
        "flatliner": bool(item.get("timing_flatliner")),
        "flags": flags,
        "explanation": item.get("bot_explanation") or item.get("analysis_summary"),
        "text_details": [
            {
                "question": entry.get("question_preview"),
                "answer": entry.get("response_preview"),
                "quality": entry.get("quality_score"),
                "flagged": bool(entry.get("is_flagged")),
                "reasons": [
                    key
                    for key, value in (entry.get("flag_reasons") or {}).items()
                    if not isinstance(value, dict) or value.get("is_relevant") is not True
                ],
            }
            for entry in item.get("text_responses_of_interest") or []
        ],
        "fraud_reasons": item.get("fraud_flag_reasons"),
        "grid_explanation": item.get("grid_explanation")
        or (
            f"Gave the same answer to all {len(straight[0])} rows of a grid." if straight else None
        ),
        "timing_explanation": item.get("timing_explanation"),
    }


def summarize(
    survey_id: str,
    summary: dict[str, Any],
    detailed: dict[str, Any],
    extras: dict[str, dict[str, Any]] | None = None,
    rules: QualityRules | None = None,
) -> dict[str, Any]:
    """Combine the summary and detailed reports into the dashboard payload.

    Args:
        survey_id: Tracking survey id.
        summary: Summary report JSON.
        detailed: Detailed report JSON.
        extras: Page times and grid answers per session id.
        rules: Quality rules; defaults when None.

    Returns:
        Dashboard payload. Counts come from the rows so they always match the table.
    """
    now = datetime.now(timezone.utc)
    extras = extras or {}
    rules = rules or QualityRules()
    rows = [
        _row(item, now, extras.get(str(item.get("session_id"))), rules)
        for item in detailed.get("respondents") or []
        if isinstance(item, dict)
    ]
    _mark_speeders(rows, rules)
    rows.sort(key=lambda row: row.get("started") or "", reverse=True)
    checked = [row for row in rows if row["status"] == "checked"]
    flagged = [row for row in rows if row["flags"]]
    text = summary.get("text_quality_summary") or {}
    fraud = summary.get("fraud_summary") or {}
    grid = summary.get("grid_analysis_summary") or {}
    timing = summary.get("timing_analysis_summary") or {}
    return {
        "survey_id": survey_id,
        "updated_at": now.isoformat(),
        "totals": {
            "sessions": len(rows),
            "in_progress": sum(1 for row in rows if row["status"] == "in_progress"),
            "checked": len(checked),
            "dropped": sum(1 for row in rows if row["status"] == "dropped"),
            "bots": sum(1 for row in checked if row["verdict"] == "bot"),
            "flagged": len(flagged),
            "duplicates": sum(1 for row in rows if row["duplicate"]),
            "speeders": sum(1 for row in rows if row["speeder"]),
            "straight_liners": sum(1 for row in rows if row["straight_lining"]),
            "low_quality_text": sum(1 for row in rows if row["low_quality_text"]),
        },
        "text": {
            "responses": text.get("total_responses") or 0,
            "avg_quality": text.get("avg_quality_score"),
            "flagged": text.get("flagged_count") or 0,
            "flagged_pct": text.get("flagged_percentage") or 0,
        },
        "fraud": {
            "analyzed": fraud.get("total_sessions_analyzed") or 0,
            "avg_score": fraud.get("average_fraud_score"),
            "high_risk": fraud.get("high_risk_sessions") or 0,
            "duplicates": fraud.get("duplicate_sessions") or 0,
            "methods": fraud.get("fraud_methods") or {},
        },
        "grid": {
            "responses": grid.get("total_responses") or 0,
            "straight_lined_pct": grid.get("straight_lined_percentage") or 0,
        },
        "timing": {
            "analyses": timing.get("total_analyses") or 0,
            "speeders_pct": timing.get("speeders_percentage") or 0,
            "flatliners_pct": timing.get("flatliners_percentage") or 0,
        },
        "flag_counts": _flag_counts(rows),
        "quality_distribution": text.get("quality_distribution") or {},
        "trend": trend(rows),
        "respondents": rows,
    }


# Text flags about how an answer was entered rather than what it says.
_ENTRY_REASONS = {"pasted", "no_typing"}

_FLAG_ORDER = (
    "Bot-like behaviour",
    "Low-quality open ends",
    "Pasted answers",
    "Straight-lining",
    "Speeder",
    "Flatliner",
    "Duplicate",
    "High fraud risk",
    "Data-centre IP",
)


def _flag_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count respondents per flag in a fixed order.

    Args:
        rows: Dashboard rows.

    Returns:
        ``[{"flag": name, "count": n}, ...]`` for every flag, zeros included.
    """
    return [
        {"flag": flag, "count": sum(1 for row in rows if flag in row["flags"])}
        for flag in _FLAG_ORDER
    ]


def trend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bucket starts and flagged respondents by hour, or by day for longer fieldwork.

    Args:
        rows: Dashboard rows.

    Returns:
        ``{"unit": "hour" | "day", "buckets": [{"start": iso, "started": n, "flagged": n}]}``
        with empty buckets filled, at most 120 buckets ending at the latest start.
    """
    times = [(when, bool(row["flags"])) for row in rows if (when := _when(row.get("started")))]
    if not times:
        return {"unit": "hour", "buckets": []}
    first = min(when for when, _ in times)
    last = max(when for when, _ in times)
    unit = "hour" if last - first <= timedelta(hours=48) else "day"
    step = timedelta(hours=1) if unit == "hour" else timedelta(days=1)

    def floor(when: datetime) -> datetime:
        if unit == "hour":
            return when.replace(minute=0, second=0, microsecond=0)
        return when.replace(hour=0, minute=0, second=0, microsecond=0)

    end = floor(last)
    start = max(floor(first), end - step * 119)
    counts: dict[datetime, list[int]] = {}
    cursor = start
    while cursor <= end:
        counts[cursor] = [0, 0]
        cursor += step
    for when, flagged in times:
        key = floor(when)
        if key in counts:
            counts[key][0] += 1
            counts[key][1] += int(flagged)
    return {
        "unit": unit,
        "buckets": [
            {"start": key.isoformat(), "started": value[0], "flagged": value[1]}
            for key, value in counts.items()
        ],
    }


async def list_surveys(settings: Settings, db: Session) -> list[dict[str, Any]]:
    """List surveys in the bot-detection service, linked to Quant OS projects.

    Args:
        settings: Application settings.
        db: Session.

    Returns:
        One entry per survey id with counts, last activity, and the Quant OS project
        that uses it. Tracked projects with no responses yet are included.

    Raises:
        AppError: The bot-detection API could not be reached.
    """
    base = settings.bot_detection_api_base.rstrip("/")
    async with httpx.AsyncClient(timeout=45) as http:
        try:
            response = await http.get(f"{base}/surveys", params={"limit": 1000})
        except httpx.HTTPError as exc:
            raise AppError(
                f"The bot-detection service could not be reached ({exc.__class__.__name__}).",
                "live_quality_unreachable",
                502,
            ) from None
    if response.status_code >= 400:
        raise AppError(
            f"The bot-detection service answered {response.status_code}.", "live_quality_error", 502
        )
    projects: dict[str, dict[str, Any]] = {}
    for project in ProjectRepository(db).list():
        current = (project.study_context or {}).get("live_quality") or {}
        if not current.get("enabled") and not current.get("survey_id"):
            continue
        tracking = tracking_settings(db, project.id)
        projects[tracking["survey_id"]] = {"project_id": project.id, "project_name": project.name}
    surveys: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in response.json().get("surveys") or []:
        survey_id = str(item.get("survey_id") or "")
        if not survey_id:
            continue
        seen.add(survey_id)
        surveys.append(
            {
                "survey_id": survey_id,
                "respondents": item.get("respondent_count") or 0,
                "sessions": item.get("session_count") or 0,
                "bots": item.get("bot_count") or 0,
                "last_session": item.get("last_session"),
                **projects.get(survey_id, {"project_id": None, "project_name": None}),
            }
        )
    for survey_id, project in projects.items():
        if survey_id not in seen:
            surveys.append(
                {
                    "survey_id": survey_id,
                    "respondents": 0,
                    "sessions": 0,
                    "bots": 0,
                    "last_session": None,
                    **project,
                }
            )
    surveys.sort(
        key=lambda row: (
            row["project_id"] is None,
            -(_when(row["last_session"]) or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
        )
    )
    return surveys


_CSV_COLUMNS = (
    "respondent_id",
    "session_id",
    "started",
    "status",
    "verdict",
    "risk",
    "confidence",
    "seconds",
    "pages",
    "text_responses",
    "text_quality",
    "text_flagged",
    "fraud_score",
    "fraud_risk",
    "duplicate",
    "straight_lining",
    "speeder",
    "flags",
    "flagged_answers",
)


def results_csv(result: dict[str, Any]) -> str:
    """Write one row per respondent as CSV.

    Args:
        result: Dashboard payload from :func:`live_results`.

    Returns:
        CSV text with a header row.
    """
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for row in result.get("respondents") or []:
        values = []
        for column in _CSV_COLUMNS:
            if column == "flags":
                values.append("; ".join(row.get("flags") or []))
            elif column == "flagged_answers":
                values.append(
                    " | ".join(
                        str(detail.get("answer") or "")
                        for detail in row.get("text_details") or []
                        if detail.get("flagged")
                    )
                )
            else:
                value = row.get(column)
                values.append("" if value is None else value)
        writer.writerow(values)
    return buffer.getvalue()


def rules_for_survey(db: Session, survey_id: str) -> QualityRules:
    """Rules of the Quant OS project that tracks ``survey_id``; defaults otherwise.

    Args:
        db: Session.
        survey_id: Tracking survey id.

    Returns:
        Quality rules.
    """
    for project in ProjectRepository(db).list():
        current = (project.study_context or {}).get("live_quality") or {}
        if not current.get("enabled") and not current.get("survey_id"):
            continue
        if tracking_settings(db, project.id)["survey_id"] == survey_id:
            return get_rules(db, project.id)
    return QualityRules()
