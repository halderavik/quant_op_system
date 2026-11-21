"""Tracking study routes: waves, wave changes, and trend tables."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.records import ProjectRepository

router = APIRouter()


class NextWaveIn(BaseModel):
    """The new wave's project name and label."""

    name: str = Field(default="", max_length=200)
    label: str = Field(default="", max_length=80)


class TrendIn(BaseModel):
    """Variables to trend."""

    variables: list[str] = Field(min_length=1, max_length=60)


@router.get("/projects/{project_id}/tracking")
def tracking_route(project_id: str, db: Session = Depends(get_db)) -> dict:
    """The project's tracking series, oldest wave first; empty when it is not a tracker.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        This wave's tracking info and every wave in the series.
    """
    from app.services.tracking import series, tracking_info

    project = ProjectRepository(db).get(project_id)
    return {"tracking": tracking_info(project), "waves": series(db, project_id)}


@router.post("/projects/{project_id}/tracking/next-wave", status_code=201)
def next_wave_route(project_id: str, body: NextWaveIn, db: Session = Depends(get_db)) -> dict:
    """Start the next wave as a new project with this wave's study materials.

    Args:
        project_id: The wave to continue from.
        body: Name and label.
        db: Session.

    Returns:
        The new project id, wave number, and what was copied.
    """
    from app.services.tracking import start_next_wave

    return start_next_wave(db, project_id, body.name, body.label)


@router.get("/projects/{project_id}/tracking/changes")
def wave_changes_route(project_id: str, db: Session = Depends(get_db)) -> dict:
    """What changed in the questionnaire since the previous wave.

    Args:
        project_id: This wave's project id.
        db: Session.

    Returns:
        Per-question changes and counts.
    """
    from app.services.tracking import wave_changes

    return wave_changes(db, project_id)


@router.get("/projects/{project_id}/tracking/variables")
def trend_variables_route(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Variables every wave with data has.

    Args:
        project_id: Any wave's project id.
        db: Session.

    Returns:
        Name and label of each shared variable.
    """
    from app.services.tracking import common_variables

    ProjectRepository(db).get(project_id)
    return common_variables(db, project_id)


@router.post("/projects/{project_id}/tracking/trend")
def trend_route(
    project_id: str, body: TrendIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Trend the chosen variables across every wave with data.

    Args:
        project_id: Any wave's project id.
        body: Variables.
        request: Current request.
        db: Session.

    Returns:
        Waves and one table per variable, each wave tested against the one before.
    """
    from app.services.tracking import trend_table

    ProjectRepository(db).get(project_id)
    return trend_table(db, request.app.state.storage, project_id, body.variables)
