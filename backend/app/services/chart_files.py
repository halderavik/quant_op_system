"""Render chart specs and store them as downloadable PNGs plus one ZIP."""

import io
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.engines.analysis.plots import clean_specs
from app.engines.chart_render import file_name, render
from app.services.storage import Storage
from app.services.stored_files import _write_export

logger = logging.getLogger(__name__)


def store_charts(
    db: Session, storage: Storage, project_id: str, specs: Any, prefix: str
) -> dict[str, Any]:
    """Draw every valid spec and store the images.

    A chart that fails to draw is skipped with a note; it never fails the run.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        specs: Chart specs from the result.
        prefix: Download name prefix, such as ``analysis`` or ``coding_Q15``.

    Returns:
        ``charts`` (title, kind, file_id), ``chart_file_id`` (the first),
        ``charts_zip_file_id``, ``images`` (title, PNG bytes) for the workbook,
        and ``notes`` about skipped charts.
    """
    cleaned, notes = clean_specs(specs)
    charts: list[dict[str, Any]] = []
    images: list[tuple[str, bytes]] = []
    drawn_specs: list[dict[str, Any]] = []
    archive = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(archive, "w") as bundle:
        for index, spec in enumerate(cleaned, start=1):
            name = file_name(index, spec["title"])
            try:
                path = render(spec, Path(tmp) / name)
            except Exception as error:
                logger.exception("Chart %s failed to draw", spec.get("title"))
                notes.append(
                    f"Chart '{spec['title']}' could not be drawn ({error.__class__.__name__})."
                )
                continue
            data = path.read_bytes()
            file_id = _write_export(db, storage, project_id, f"{prefix}_{name}", data, "image/png")
            charts.append({"title": spec["title"], "kind": spec["kind"], "file_id": file_id})
            drawn_specs.append(spec)
            images.append((spec["title"], data))
            bundle.writestr(name, data)
    result: dict[str, Any] = {
        "charts": charts,
        "chart_file_id": charts[0]["file_id"] if charts else None,
        "charts_zip_file_id": None,
        "images": images,
        "notes": notes,
        "specs": drawn_specs,
    }
    if len(charts) > 1:
        result["charts_zip_file_id"] = _write_export(
            db, storage, project_id, f"{prefix}_charts.zip", archive.getvalue(), "application/zip"
        )
    return result
