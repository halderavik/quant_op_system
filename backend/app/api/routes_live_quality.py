"""Live quality routes: tracking settings and live bot and fraud results for a project."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import live_quality, quality_rules
from app.services.quality_rules import QualityRules

router = APIRouter()


class TrackingIn(BaseModel):
    """Whether the next Decipher programming adds tracking."""

    enabled: bool
    use_project_name: bool = False


def _state(request: Request, db: Session, project_id: str) -> dict[str, Any]:
    """Return settings, Decipher status, and dashboard links.

    Args:
        request: Current request.
        db: Session.
        project_id: Project id.

    Returns:
        Live-quality state without results.
    """
    settings = request.app.state.settings
    tracking = live_quality.tracking_settings(db, project_id)
    return {
        **tracking,
        "decipher": live_quality.decipher_status(db, project_id, tracking["survey_id"]),
        "api_base": settings.bot_detection_api_base,
    }


@router.get("/projects/{project_id}/live-quality")
def get_live_quality(project_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Return the project's tracking settings and Decipher status.

    Args:
        project_id: Project id.
        request: Current request.
        db: Session.

    Returns:
        Live-quality state.
    """
    return _state(request, db, project_id)


@router.put("/projects/{project_id}/live-quality")
def put_live_quality(
    project_id: str, body: TrackingIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Turn tracking on or off for the next Decipher programming.

    Args:
        project_id: Project id.
        body: Enabled flag.
        request: Current request.
        db: Session.

    Returns:
        Live-quality state after the change.
    """
    live_quality.set_tracking(db, project_id, body.enabled, body.use_project_name)
    db.commit()
    return _state(request, db, project_id)


class UploadedXmlIn(BaseModel):
    """A Decipher survey XML already uploaded to the project."""

    file_id: str


@router.post("/projects/{project_id}/live-quality/xml")
def add_tracking_to_xml(
    project_id: str, body: UploadedXmlIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Add tracking to an uploaded Decipher survey XML and make it the project's survey.

    Args:
        project_id: Project id.
        body: The uploaded file.
        request: Current request.
        db: Session.

    Returns:
        The outcome summary and the live-quality state after the change.
    """
    from app.services.decipher_tracking_import import add_tracking_to_upload

    outcome = add_tracking_to_upload(
        db, request.app.state.storage, project_id, body.file_id, request.app.state.settings
    )
    db.commit()
    return {**outcome, "state": _state(request, db, project_id)}


@router.get("/projects/{project_id}/live-quality/results")
async def get_live_results(
    project_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Return live results from the bot-detection service.

    Args:
        project_id: Project id.
        request: Current request.
        db: Session.

    Returns:
        Totals and one row per session. Empty when tracking has no id yet.
    """
    tracking = live_quality.tracking_settings(db, project_id)
    if not tracking["survey_id"]:
        return live_quality.summarize("", {}, {"respondents": []})
    rules = quality_rules.get_rules(db, project_id)
    return await live_quality.live_results(request.app.state.settings, tracking["survey_id"], rules)


@router.get("/live-quality/surveys")
async def list_live_surveys(request: Request, db: Session = Depends(get_db)) -> list[dict]:
    """List every survey in the bot-detection service, linked to Quant OS projects.

    Args:
        request: Current request.
        db: Session.

    Returns:
        Survey entries, Quant OS projects first.
    """
    return await live_quality.list_surveys(request.app.state.settings, db)


@router.get("/live-quality/results")
async def get_survey_results(
    survey_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Return live results for one survey id, under its project's rules when it has one.

    Args:
        survey_id: Tracking survey id.
        request: Current request.
        db: Session.

    Returns:
        Dashboard payload.
    """
    rules = live_quality.rules_for_survey(db, survey_id)
    return await live_quality.live_results(request.app.state.settings, survey_id, rules)


@router.get("/live-quality/export")
async def export_survey_results(
    survey_id: str, request: Request, db: Session = Depends(get_db)
) -> Response:
    """Download one row per respondent as CSV.

    Args:
        survey_id: Tracking survey id.
        request: Current request.
        db: Session.

    Returns:
        CSV attachment.
    """
    rules = live_quality.rules_for_survey(db, survey_id)
    result = await live_quality.live_results(request.app.state.settings, survey_id, rules)
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in survey_id)[:80]
    return Response(
        live_quality.results_csv(result),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="quality-{safe or "survey"}.csv"'},
    )


def _rules_state(db: Session, project_id: str) -> dict[str, Any]:
    """Rules in force, the defaults, what changed, and labels for the editor."""
    rules = quality_rules.get_rules(db, project_id)
    return {
        "rules": rules.model_dump(),
        "defaults": quality_rules.defaults().model_dump(),
        "changed": quality_rules.changed_fields(rules),
        **quality_rules.describe(),
    }


@router.get("/projects/{project_id}/live-quality/rules")
def get_quality_rules(project_id: str, db: Session = Depends(get_db)) -> dict:
    """Return the project's quality rules and the defaults.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        Rules state.
    """
    return _rules_state(db, project_id)


@router.put("/projects/{project_id}/live-quality/rules")
def put_quality_rules(project_id: str, body: QualityRules, db: Session = Depends(get_db)) -> dict:
    """Save the project's quality rules.

    Args:
        project_id: Project id.
        body: Complete rules.
        db: Session.

    Returns:
        Rules state after saving.
    """
    quality_rules.save_rules(db, project_id, body)
    db.commit()
    return _rules_state(db, project_id)


@router.delete("/projects/{project_id}/live-quality/rules")
def reset_quality_rules(project_id: str, db: Session = Depends(get_db)) -> dict:
    """Restore the default quality rules.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        Rules state after the reset.
    """
    quality_rules.save_rules(db, project_id, None)
    db.commit()
    return _rules_state(db, project_id)
