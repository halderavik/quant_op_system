"""Accept a canonical tab-spec workbook, and hold every other layout for review."""

from typing import Any

from sqlalchemy.orm import Session

from app.engines.external_spec import preview_external
from app.engines.invariants import summarize, validate_export
from app.engines.tabbook_excel import export_tabbook
from app.engines.tabspec_excel import import_tabspec
from app.repositories.records import ArtifactRepository, FileRepository
from app.services.execute import _optional_dataset, load_frame, run_spec_book
from app.services.storage import Storage
from app.services.stored_files import _write_export


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
    if preview.format_id != "canonical" or preview.requires_confirmation:
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
    dataset = _optional_dataset(db, project_id)
    if dataset is None:
        return {
            "executed": False,
            "artifact_id": spec_revision.artifact_id,
            "message": "The canonical spec is stored. Upload a dataset before running the tables.",
        }
    frame = load_frame(storage, dataset)
    book = run_spec_book(frame, dataset.variables, spec, dataset.id)
    payload = export_tabbook(book)
    file_id = _write_export(
        db,
        storage,
        project_id,
        "tab-book.xlsx",
        payload,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    stored = FileRepository(db).get(file_id)
    gate = summarize([validate_export(storage.resolve(project_id, stored.storage_relpath))])
    ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="crosstab",
        name="Imported tab book",
        content={
            "tables": [table.model_dump(mode="json") for table in book.tables],
            "exceptions": book.exceptions,
            "export_file_id": file_id,
            "table": book.tables[0].model_dump(mode="json") if book.tables else None,
        },
        content_schema="crosstab/1",
        created_by="crosstab",
        derived_from=[
            {
                "type": "tabspec",
                "id": spec_revision.artifact_id,
                "version": spec_revision.version,
            }
        ],
        validation_status=gate.status,
    )
    skipped = len(book.exceptions)
    return {
        "executed": True,
        "artifact_id": spec_revision.artifact_id,
        "export_file_id": file_id,
        "message": f"Ran the canonical spec. {skipped} tables were recorded as exceptions.",
    }
