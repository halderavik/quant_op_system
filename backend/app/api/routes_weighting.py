"""Weighting routes: census targets, user edits, building the weight, and using it."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.records import ProjectRepository
from app.services import weighting_run

router = APIRouter()


class ProposeIn(BaseModel):
    """Who the survey represents and which variables to weight on."""

    population: str = ""
    variables: list[str] = []


class PlanIn(BaseModel):
    """The plan as edited in the panel."""

    plan: dict[str, Any]
    expected_version: int | None = None


class UseIn(BaseModel):
    """Whether later tables use the built weight."""

    enabled: bool


@router.get("/projects/{project_id}/weighting")
def get_weighting(project_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Return the plan, candidate variables with sample shares, and the project weight."""
    return weighting_run.weighting_state(db, request.app.state.storage, project_id)


@router.post("/projects/{project_id}/weighting/propose")
async def propose_weighting(
    project_id: str, body: ProposeIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Research census targets with references and save them for review."""
    project = ProjectRepository(db)
    conversations = project.conversations(project_id)
    session_id = conversations[0].sdk_session_id if conversations else f"weighting-{project_id}"
    # Reason: SQLite holds the write lock until commit; the research call takes minutes.
    db.commit()
    return await weighting_run.propose_targets(
        db,
        request.app.state.storage,
        request.app.state.settings,
        project_id,
        population=body.population,
        variables=body.variables or [],
        session_id=session_id,
    )


@router.put("/projects/{project_id}/weighting")
def put_weighting(
    project_id: str, body: PlanIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Save edited or added targets."""
    return weighting_run.save_plan(
        db, request.app.state.storage, project_id, body.plan, body.expected_version
    )


@router.post("/projects/{project_id}/weighting/build")
def build_weighting(project_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Rake to the saved targets and make the weight the project weight."""
    return weighting_run.build_weight(db, request.app.state.storage, project_id)


@router.put("/projects/{project_id}/weighting/use")
def use_weighting(project_id: str, body: UseIn, db: Session = Depends(get_db)) -> dict:
    """Turn the built weight on or off for later tables."""
    return weighting_run.set_weight_use(db, project_id, body.enabled)
