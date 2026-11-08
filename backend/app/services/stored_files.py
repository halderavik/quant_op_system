"""Persist generated export bytes as project files."""

from typing import Any

from sqlalchemy.orm import Session

from app.errors import AppError
from app.repositories.records import FileRepository
from app.services.storage import Storage
from app.util import new_id, sha256_bytes


def _write_export(
    db: Session, storage: Storage, project_id: str, filename: str, payload: bytes, media: str
) -> str:
    """Store an export and return its file id.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        filename: Download name.
        payload: Bytes.
        media: Media type.

    Returns:
        File id.
    """
    if not payload:
        raise AppError("The export was empty, so it was not published.", "export_missing")
    relative = f"exports/{new_id()}-{filename}"
    storage.write_bytes(project_id, relative, payload)
    return _file_from_path(
        db, project_id, storage.resolve(project_id, relative), filename, media, relative
    )


def _file_from_path(
    db: Session,
    project_id: str,
    path: Any,
    filename: str,
    media: str,
    relative: str | None = None,
) -> str:
    """Insert a file row for a path that already exists.

    Args:
        db: Session.
        project_id: Project id.
        path: Absolute path.
        filename: Download name.
        media: Media type.
        relative: Project-relative path.

    Returns:
        File id.
    """
    data = path.read_bytes()
    rel = relative or f"exports/{path.name}"
    row = FileRepository(db).add(
        project_id=project_id,
        filename=filename,
        media_type=media,
        sha256=sha256_bytes(data),
        storage_relpath=rel,
        size_bytes=len(data),
    )
    return row.id
