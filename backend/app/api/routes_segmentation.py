"""Segmentation routes: compare solutions, name segments, typing tool, and save to data."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.records import ProjectRepository

router = APIRouter()


class SegmentationIn(BaseModel):
    """Variables and the range of segment counts to compare."""

    variables: list[str] = Field(min_length=2, max_length=80)
    k_min: int = Field(default=3, ge=2, le=12)
    k_max: int = Field(default=6, ge=2, le=12)


class SegmentationUpdate(BaseModel):
    """Choose a solution and rename its segments."""

    k: int | None = Field(default=None, ge=2, le=12)
    names: dict[str, str] = Field(default_factory=dict)


@router.get("/projects/{project_id}/segmentation/variables")
def segmentation_variables(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """Numeric variables of the active dataset."""
    from app.services.segmentation_run import candidate_variables

    return candidate_variables(db, project_id)


@router.get("/projects/{project_id}/segmentation")
def latest_segmentation(project_id: str, db: Session = Depends(get_db)) -> dict:
    """The latest segmentation, or ``{"segmentation": null}``."""
    from app.services.segmentation_run import get_segmentation

    ProjectRepository(db).get(project_id)
    return {"segmentation": get_segmentation(db, project_id)}


@router.post("/projects/{project_id}/segmentation", status_code=201)
def run_segmentation_route(
    project_id: str, body: SegmentationIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Compare K-means solutions and save the segmentation."""
    from app.services.segmentation_run import run_segmentation

    return run_segmentation(
        db, request.app.state.storage, project_id, body.variables, body.k_min, body.k_max
    )


@router.patch("/projects/{project_id}/segmentation/{artifact_id}")
def update_segmentation_route(
    project_id: str, artifact_id: str, body: SegmentationUpdate, db: Session = Depends(get_db)
) -> dict:
    """Choose a solution and rename segments."""
    from app.services.segmentation_run import update_segmentation

    return update_segmentation(db, project_id, artifact_id, body.k, body.names)


@router.post("/projects/{project_id}/segmentation/{artifact_id}/typing-tool")
def typing_tool_route(
    project_id: str, artifact_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Excel typing tool for the chosen solution."""
    from app.services.segmentation_run import typing_tool_workbook

    return {"file_id": typing_tool_workbook(db, request.app.state.storage, project_id, artifact_id)}


@router.post("/projects/{project_id}/segmentation/{artifact_id}/save-to-data")
def save_segments_route(
    project_id: str, artifact_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Add the chosen segments to the data as a new dataset version."""
    from app.services.segmentation_run import save_to_data

    return save_to_data(db, request.app.state.storage, project_id, artifact_id)
