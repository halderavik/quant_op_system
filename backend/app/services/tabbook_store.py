"""Store a crosstab book as Excel plus one readable table at a time."""

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.invariants import summarize, validate_export
from app.engines.tabbook_excel import export_tabbook
from app.errors import AppError
from app.models import ArtifactRevision
from app.repositories.records import ArtifactRepository, FileRepository
from app.schemas.crosstab import TabBook, TableResult
from app.services.storage import Storage
from app.services.stored_files import _write_export
from app.util import new_id

_LARGE_REVISION = 1_500_000
_FILE_ID = re.compile(r'"export_file_id"\s*:\s*"([^"]+)"')


@dataclass
class ListedRevision:
    """Revision fields the artifact list needs, without a huge document."""

    version: int
    content: dict[str, Any]
    stale: bool
    validation_status: str
    content_hash: str
    content_schema: str


def slim_table(table: TableResult) -> dict[str, Any]:
    """Keep the cells the panel draws.

    Args:
        table: Computed table.

    Returns:
        Columns, display values, counts, and letters. The total column is omitted
        when the table has banner columns, matching the example workbook.
    """
    columns = [column for column in table.columns if column.id != "total"] or list(table.columns)
    rows: list[dict[str, Any]] = []
    for row in table.rows:
        cells: dict[str, Any] = {}
        for column in columns:
            cell = row.cells.get(column.id)
            if cell is None:
                continue
            cells[column.id] = {
                "display_value": cell.display_value,
                "unweighted_base": cell.unweighted_base,
                "unweighted_numerator": cell.unweighted_numerator,
                "significance_letters": cell.significance_letters,
                "weighted_base": cell.weighted_base,
            }
        rows.append({"label": row.label, "cells": cells})
    return {
        "table_id": table.table_id,
        "title": table.title,
        "columns": [
            {"id": column.id, "label": column.label, "letter": column.letter} for column in columns
        ],
        "rows": rows,
        "footnotes": table.footnotes[:8],
    }


def index_title(table: TableResult) -> str:
    """Return the panel label, including the banner when the question repeats.

    Args:
        table: Computed table.

    Returns:
        Title, with the banner caption when one was recorded.
    """
    if table.banner_caption:
        return f"{table.title} — {table.banner_caption}"
    return table.title


def write_table_store(
    storage: Storage, project_id: str, tables: list[TableResult]
) -> tuple[str, str]:
    """Write one JSON line per table and an offset index.

    Args:
        storage: Project storage.
        project_id: Project id.
        tables: Computed tables.

    Returns:
        Relative paths of the line file and the offset index.
    """
    store_id = new_id()
    lines_rel = f"exports/{store_id}-tables.jsonl"
    index_rel = f"exports/{store_id}-tables.index.json"
    chunks: list[bytes] = []
    index: dict[str, int] = {}
    cursor = 0
    for table in tables:
        encoded = (json.dumps(slim_table(table), separators=(",", ":")) + "\n").encode()
        index[table.table_id] = cursor
        chunks.append(encoded)
        cursor += len(encoded)
    storage.write_bytes(project_id, lines_rel, b"".join(chunks) or b"")
    storage.write_bytes(project_id, index_rel, json.dumps(index).encode())
    return lines_rel, index_rel


def read_stored_table(
    storage: Storage, project_id: str, lines_rel: str, index_rel: str, table_id: str
) -> dict[str, Any]:
    """Read one table from the line store.

    Args:
        storage: Project storage.
        project_id: Project id.
        lines_rel: JSONL path relative to the project.
        index_rel: Offset index path relative to the project.
        table_id: Table id.

    Returns:
        Slim table.

    Raises:
        AppError: When the id is not in the index.
    """
    index = json.loads(storage.read_bytes(project_id, index_rel))
    offset = index.get(table_id)
    if not isinstance(offset, int):
        raise AppError(f"Table {table_id} is not in this book.", "not_found", 404)
    path = storage.resolve(project_id, lines_rel)
    with path.open("rb") as handle:
        handle.seek(offset)
        line = handle.readline()
    return json.loads(line)


def publish_crosstab_book(
    db: Session,
    storage: Storage,
    project_id: str,
    book: TabBook,
    *,
    name: str,
    derived_from: list[dict[str, Any]] | None = None,
) -> tuple[Any, str, Any]:
    """Write the Excel book and a panel index. Full grids stay out of the artifact row.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.
        book: Computed tables.
        name: Artifact name.
        derived_from: Upstream artifact references.

    Returns:
        The new revision, the Excel file id, and the export validation gate.
    """
    file_id = _write_export(
        db,
        storage,
        project_id,
        "tab-book.xlsx",
        export_tabbook(book),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    lines_rel, index_rel = write_table_store(storage, project_id, book.tables)
    stored = FileRepository(db).get(file_id)
    gate = summarize([validate_export(storage.resolve(project_id, stored.storage_relpath))])
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="crosstab",
        name=name,
        content={
            "export_file_id": file_id,
            "tables_relpath": lines_rel,
            "index_relpath": index_rel,
            "tables": [
                {"table_id": table.table_id, "title": index_title(table)} for table in book.tables
            ],
            "exceptions": book.exceptions,
        },
        content_schema="crosstab/1",
        created_by="crosstab",
        derived_from=derived_from,
        validation_status=gate.status,
    )
    return revision, file_id, gate


def revision_for_list(db: Session, artifact_id: str) -> ListedRevision | None:
    """Load the latest revision without pulling a multi-hundred-megabyte crosstab into memory.

    Args:
        db: Session.
        artifact_id: Artifact id.

    Returns:
        List fields, or None when the artifact has no revision.
    """
    row = db.execute(
        select(
            ArtifactRevision.id,
            ArtifactRevision.version,
            ArtifactRevision.stale,
            ArtifactRevision.validation_status,
            ArtifactRevision.content_hash,
            ArtifactRevision.content_schema,
            func.length(ArtifactRevision.content),
        )
        .where(ArtifactRevision.artifact_id == artifact_id)
        .order_by(ArtifactRevision.version.desc())
    ).first()
    if row is None:
        return None
    size = int(row[6] or 0)
    if size > _LARGE_REVISION:
        snippet = db.scalar(
            select(
                func.substr(
                    ArtifactRevision.content,
                    func.instr(ArtifactRevision.content, '"export_file_id"'),
                    80,
                )
            ).where(ArtifactRevision.id == row[0])
        )
        content: dict[str, Any] = {
            "export_file_id": _export_id(snippet),
            "tables": [],
            "exceptions": [],
            "oversized": True,
        }
    else:
        content = db.scalar(select(ArtifactRevision.content).where(ArtifactRevision.id == row[0]))
        content = content or {}
    return ListedRevision(
        version=row[1],
        content=content,
        stale=bool(row[2]),
        validation_status=row[3],
        content_hash=row[4],
        content_schema=row[5],
    )


def _export_id(snippet: str | None) -> str | None:
    """Pull an export file id out of a short slice of stored JSON.

    Args:
        snippet: Text beginning at ``export_file_id``, or None.

    Returns:
        File id, or None when the slice does not contain one.
    """
    if not snippet:
        return None
    match = _FILE_ID.search(snippet)
    return match.group(1) if match else None
