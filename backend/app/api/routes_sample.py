"""Quote, launch, and status routes for a Prolific sample."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.errors import AppError
from app.repositories.records import ProjectRepository
from app.schemas.sample_purchase import LaunchConfirm, QuoteEdit, TransitionRequest
from app.services.sample_launch import launch_sample, refresh_sample, transition_sample
from app.services.sample_quote import quote_from_edit

router = APIRouter()


@router.post("/projects/{project_id}/sample/quote")
def quote_route(
    project_id: str,
    body: QuoteEdit,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Reprice the audience shown in the panel.

    Args:
        project_id: Project id.
        body: Sample size, minutes, reward, and filters.
        request: Current request.
        db: Session.

    Returns:
        Summary and artifact id.
    """
    ProjectRepository(db).get(project_id)
    return quote_from_edit(
        db,
        request.app.state.settings,
        project_id,
        body,
    )


@router.post("/projects/{project_id}/sample/launch")
def launch_route(
    project_id: str,
    body: LaunchConfirm,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Publish the quoted sample after an explicit confirmation.

    Args:
        project_id: Project id.
        body: Confirmation and the total the user saw.
        request: Current request.
        db: Session.

    Returns:
        Summary and artifact id.

    Raises:
        AppError: The user has not confirmed the price.
    """
    ProjectRepository(db).get(project_id)
    if not body.confirm:
        raise AppError("Confirm the price before publishing.", "confirm_required")
    return launch_sample(
        db,
        request.app.state.storage,
        request.app.state.settings,
        project_id,
        body.total_cost_cents,
    )


@router.post("/projects/{project_id}/sample/transition")
def transition_route(
    project_id: str,
    body: TransitionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Pause, resume, or stop the Prolific study.

    Args:
        project_id: Project id.
        body: Transition action.
        request: Current request.
        db: Session.

    Returns:
        Summary and artifact id.
    """
    ProjectRepository(db).get(project_id)
    return transition_sample(db, request.app.state.settings, project_id, body.action)


@router.post("/projects/{project_id}/sample/refresh")
def refresh_route(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Refresh the Prolific study status.

    Args:
        project_id: Project id.
        request: Current request.
        db: Session.

    Returns:
        Summary and artifact id.
    """
    ProjectRepository(db).get(project_id)
    return refresh_sample(db, request.app.state.settings, project_id)
