"""Run the latest saved tab spec as a crosstab book."""

from typing import Any

from sqlalchemy.orm import Session

from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.tabspec import TabSpec
from app.services.execute import _active_dataset, load_frame, run_spec_book
from app.services.storage import Storage
from app.services.tabbook_store import publish_crosstab_book

_NO_SPEC = (
    "There is no saved tab spec yet. Ask me to build one, or name one row and one banner, "
    "such as trust by gender."
)


def run_saved_tabspec(db: Session, storage: Storage, project_id: str) -> dict[str, Any]:
    """Run the latest saved tab spec against the active dataset.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.

    Returns:
        Summary payload with the crosstab artifact id.

    Raises:
        AppError: When the project has no tab spec, or no dataset is active.
    """
    spec_row = ArtifactRepository(db).latest_of_type(project_id, "tabspec")
    if spec_row is None:
        raise AppError(_NO_SPEC, "missing_tabspec")
    # Reason: the panel stores export_file_id beside the spec. Validation ignores it.
    spec = TabSpec.model_validate(spec_row.content)
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    book = run_spec_book(frame, dataset.variables, spec, dataset.id)
    revision, _file_id, gate = publish_crosstab_book(
        db,
        storage,
        project_id,
        book,
        name="Tab book",
        derived_from=[{"type": "tabspec", "id": spec_row.artifact_id, "version": spec_row.version}],
    )
    ran = len(book.tables)
    skipped = len(book.exceptions)
    status = "completed" if skipped == 0 and gate.status == "passed" else "completed_with_warnings"
    table_word = "table" if ran == 1 else "tables"
    if skipped == 1:
        exception_text = "1 table was recorded as an exception."
    else:
        exception_text = f"{skipped} tables were recorded as exceptions."
    return {
        "summary": (
            f"Ran {ran} {table_word} from tab spec version {spec_row.version}. {exception_text} "
            "The workbook is in the panel."
        ),
        "status": status,
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "warnings": [str(item.get("message") or "") for item in book.exceptions[:5]],
        "validation": gate.model_dump(mode="json"),
    }
