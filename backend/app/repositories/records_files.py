"""File and job rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Job, StoredFile
from app.util import new_id


def _now() -> datetime:
    """Return the current UTC time.

    Returns:
        Timezone-aware timestamp.
    """
    return datetime.now(timezone.utc)


class FileRepository:
    """Uploaded file rows."""

    def __init__(self, db: Session) -> None:
        """Bind a session.

        Args:
            db: SQLAlchemy session.
        """
        self.db = db

    def add(self, **kwargs: Any) -> StoredFile:
        """Insert a file row.

        Args:
            **kwargs: Column values.

        Returns:
            Stored file.
        """
        row = StoredFile(id=kwargs.pop("id", new_id()), created_at=_now(), **kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, file_id: str) -> StoredFile:
        """Return a file row.

        Args:
            file_id: File id.

        Returns:
            Stored file.
        """
        row = self.db.get(StoredFile, file_id)
        if row is None:
            raise AppError("File not found", "not_found", 404)
        return row

    def list_project(self, project_id: str) -> list[StoredFile]:
        """Return files for one project, newest first.

        Args:
            project_id: Project id.

        Returns:
            Stored file rows.
        """
        return list(
            self.db.scalars(
                select(StoredFile)
                .where(StoredFile.project_id == project_id)
                .order_by(StoredFile.created_at.desc())
            ).all()
        )


class JobRepository:
    """Sandbox job rows."""

    def __init__(self, db: Session) -> None:
        """Bind a session.

        Args:
            db: SQLAlchemy session.
        """
        self.db = db

    def add(self, **kwargs: Any) -> Job:
        """Insert a job.

        Args:
            **kwargs: Column values.

        Returns:
            Job.
        """
        row = Job(id=kwargs.pop("id", new_id()), created_at=_now(), updated_at=_now(), **kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, job_id: str) -> Job:
        """Return one job.

        Args:
            job_id: Job id.

        Returns:
            Job row.

        Raises:
            AppError: When the job does not exist.
        """
        row = self.db.get(Job, job_id)
        if row is None:
            raise AppError("Job not found", "not_found", 404)
        return row

    def list_project(self, project_id: str) -> list[Job]:
        """Return jobs for one project, oldest first.

        Args:
            project_id: Project id.

        Returns:
            Job rows.
        """
        return list(
            self.db.scalars(
                select(Job).where(Job.project_id == project_id).order_by(Job.created_at)
            ).all()
        )
