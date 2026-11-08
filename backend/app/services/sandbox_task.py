"""Run a chart request in the sandbox and publish the output files."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.crosstab import TableResult
from app.services.jobs import execute_job
from app.services.storage import Storage
from app.services.stored_files import _file_from_path

_SCRIPT = r"""
import json
from pathlib import Path

table = json.loads(Path("table.json").read_text(encoding="utf-8"))
lines = []
bars = []
for row in table.get("rows") or []:
    if row.get("row_kind") != "category":
        continue
    cell = (row.get("cells") or {}).get("total") or {}
    estimate = cell.get("estimate")
    if estimate is None:
        continue
    label = str(row.get("label") or "")
    lines.append(f"{label} is {cell.get('display_value')} (source estimate {estimate}).")
    bars.append((label, float(estimate)))
Path("report.txt").write_text("\n".join(lines), encoding="utf-8")
height = 40 + 28 * max(len(bars), 1)
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="{height}" role="img">',
    "<title>Table chart</title>",
]
for index, (label, estimate) in enumerate(bars):
    y = 24 + index * 28
    length = max(0.0, min(200.0, estimate * 2))
    safe = label.replace("&", "&amp;").replace("<", "&lt;")
    parts.append(f'<text x="8" y="{y}" font-size="12">{safe}</text>')
    parts.append(f'<rect x="180" y="{y - 12}" width="{length}" height="14" fill="#115e59"/>')
parts.append("</svg>")
Path("chart.svg").write_text("\n".join(parts), encoding="utf-8")
print("wrote chart")
"""


def chart_via_sandbox(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    *,
    prompt: str,
    store_traces: bool,
) -> dict[str, Any]:
    """Chart the latest crosstab by running a generated script in the sandbox.

    Args:
        db: Session.
        storage: Storage service.
        settings: Application settings.
        project_id: Project id.
        prompt: User request. Stored only when traces are enabled.
        store_traces: Project trace setting.

    Returns:
        Task outcome. A nonzero script exit does not publish a chart.
    """
    current = ArtifactRepository(db).latest_of_type(project_id, "crosstab")
    if current is None or "table" not in (current.content or {}):
        raise AppError("There is no computed table in this project yet.", "not_found", 404)
    table = TableResult.model_validate(current.content["table"])
    job = execute_job(
        db,
        storage,
        settings,
        project_id,
        kind="chart",
        script=_SCRIPT,
        inputs={"table.json": json.dumps(table.model_dump(mode="json"))},
        prompt=prompt,
        store_traces=store_traces,
    )
    if job.status != "completed":
        return {
            "summary": "The chart script failed, so no chart was saved.",
            "status": "failed",
            "job_id": job.id,
        }
    job_dir = storage.project_root(project_id) / "jobs" / job.id
    svg = job_dir / "chart.svg"
    report_path = job_dir / "report.txt"
    if not svg.exists() or svg.stat().st_size == 0:
        job.status = "failed"
        db.flush()
        return {
            "summary": "The chart script finished without a chart file, so nothing was published.",
            "status": "failed",
            "job_id": job.id,
        }
    file_id = _file_from_path(
        db,
        project_id,
        svg,
        "chart.svg",
        "image/svg+xml",
        f"jobs/{job.id}/chart.svg",
    )
    rendered = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    claims = []
    for row in table.rows:
        if row.row_kind != "category":
            continue
        cell = row.cells.get("total")
        if cell is None or cell.estimate is None:
            continue
        claims.append(
            {
                "path": f"rows.{row.label}.total.estimate",
                "stated_value": cell.estimate,
                "sentence": f"{row.label} is {cell.display_value} (source estimate {cell.estimate}).",
            }
        )
    job.manifest = {**(job.manifest or {}), "file_ids": [file_id]}
    db.flush()
    content = {
        "title": table.title,
        "rendered": rendered,
        "claims": claims,
        "chart_file_id": file_id,
        "script": _SCRIPT,
        "provenance": {
            "dataset_id": table.dataset_id,
            "artifact_version": current.version,
            "source_artifact_id": current.artifact_id,
            "job_id": job.id,
            "isolation": job.isolation,
            "warning": job.warning,
            "validation": [{"id": "export_exists", "status": "passed"}],
        },
    }
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="chart",
        name=f"Chart of {table.title}",
        content=content,
        content_schema="chart/1",
        created_by="general",
        derived_from=[{"type": "crosstab", "id": current.artifact_id, "version": current.version}],
        validation_status="passed",
    )
    return {
        "summary": (
            f"Charted {table.title} from crosstab version {current.version}. "
            "Figures come from that table."
        ),
        "status": "completed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "job_id": job.id,
    }
