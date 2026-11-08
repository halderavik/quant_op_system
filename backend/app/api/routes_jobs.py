"""Job list and cancel routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.records import JobRepository, ProjectRepository
from app.services.jobs import cancel_job, job_payload

router = APIRouter()


@router.get("/projects/{project_id}/jobs")
def list_jobs(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """List sandbox jobs for a project.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        Job rows, oldest first.
    """
    ProjectRepository(db).get(project_id)
    return [job_payload(job) for job in JobRepository(db).list_project(project_id)]


@router.post("/jobs/{job_id}/cancel")
def cancel_job_route(job_id: str, db: Session = Depends(get_db)) -> dict:
    """Cancel a live job, or return the existing row when it is already finished.

    Args:
        job_id: Job id.
        db: Session.

    Returns:
        The same job. A second cancel does not insert a row.
    """
    return job_payload(cancel_job(db, job_id))
