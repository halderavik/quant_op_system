"""Accept a canonical tab-spec workbook, and hold every other layout for review."""

from typing import Any

from sqlalchemy.orm import Session

from app.engines.external_spec import preview_external
from app.engines.tabspec_excel import import_tabspec
from app.repositories.records import ArtifactRepository, DatasetRepository, ProjectRepository
from app.services.execute import load_frame, run_spec_book
from app.services.storage import Storage
from app.services.tabbook_store import publish_crosstab_book


def ingest_workbook(db: Session, storage: Storage, project_id: str, data: bytes) -> dict[str, Any]:
    """Store a tab-spec workbook and run it only when the layout is canonical.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.
        data: Uploaded workbook bytes.

    Returns:
        Execution flag, artifact id, and a user-facing message.
    """
    preview = preview_external(data)
    if preview.format_id not in {"canonical", "analyst"} or preview.requires_confirmation:
        revision = ArtifactRepository(db).create(
            project_id=project_id,
            artifact_type="spec_review",
            name="Tab spec mapping review",
            content=preview.model_dump(mode="json"),
            content_schema="tabspec-review/1",
            created_by="user",
            validation_status="pending",
        )
        return {
            "executed": False,
            "artifact_id": revision.artifact_id,
            "message": "This workbook is not a confirmed canonical tab spec, so no tables were run.",
        }
    spec = import_tabspec(data)
    spec_revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="tabspec",
        name=spec.spec_id,
        content=spec.model_dump(mode="json"),
        content_schema="tabspec/1",
        created_by="user",
        validation_status="passed",
    )
    dataset = _active_dataset(db, project_id)
    if dataset is None:
        return {
            "executed": False,
            "artifact_id": spec_revision.artifact_id,
            "message": "The canonical spec is stored. Upload a dataset before running the tables.",
        }
    frame = load_frame(storage, dataset)
    book = run_spec_book(frame, dataset.variables, spec, dataset.id)
    _revision, file_id, _gate = publish_crosstab_book(
        db,
        storage,
        project_id,
        book,
        name="Imported tab book",
        derived_from=[
            {
                "type": "tabspec",
                "id": spec_revision.artifact_id,
                "version": spec_revision.version,
            }
        ],
    )
    skipped = len(book.exceptions)
    return {
        "executed": True,
        "artifact_id": spec_revision.artifact_id,
        "export_file_id": file_id,
        "message": f"Ran the canonical spec. {skipped} tables were recorded as exceptions.",
    }


def _active_dataset(db: Session, project_id: str) -> Any:
    """Return the active dataset when one is selected.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        Dataset or None.
    """
    project = ProjectRepository(db).get(project_id)
    if not project.active_dataset_id:
        return None
    return DatasetRepository(db).get(project.active_dataset_id)
