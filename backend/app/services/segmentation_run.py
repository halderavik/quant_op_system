"""Run a segmentation on the project's active dataset, keep it, and hand out a typing tool.

The result is a ``segmentation`` artifact: every solution tried, the recommended
and chosen one, segment names (editable), profiles, and a typing tool per solution.
The chosen segments can be added to the data as a new dataset version, and the
typing tool downloads as an Excel file that scores a respondent with formulas.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy.orm import Session

from app.engines.segmentation import compare_solutions
from app.errors import AppError
from app.repositories.records import ArtifactRepository, DatasetRepository, ProjectRepository
from app.services.storage import Storage
from app.util import new_id

ARTIFACT = "segmentation"


def candidate_variables(db: Session, project_id: str) -> list[dict[str, str]]:
    """Numeric variables of the active dataset that a segmentation can use.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        Name and label of each numeric variable.
    """
    dataset = _dataset(db, project_id)
    return [
        {"name": str(item.get("name")), "label": str(item.get("label") or item.get("name"))}
        for item in dataset.variables or []
        if not item.get("is_text")
    ]


def run_segmentation(
    db: Session,
    storage: Storage,
    project_id: str,
    variables: list[str],
    k_min: int = 3,
    k_max: int = 6,
) -> dict[str, Any]:
    """Compare solutions from ``k_min`` to ``k_max`` segments and save the result.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        variables: Segmentation variables.
        k_min: Fewest segments to try.
        k_max: Most segments to try.

    Returns:
        The saved segmentation (artifact id, version, and content without assignments).
    """
    from app.services.execute import load_frame

    if k_max < k_min:
        raise AppError("The most segments must be at least the fewest.", "bad_request", 400)
    dataset = _dataset(db, project_id)
    frame = load_frame(storage, dataset)
    labels = {
        str(item.get("name")): str(item.get("label") or item.get("name"))
        for item in dataset.variables or []
    }
    result = compare_solutions(frame, variables, list(range(k_min, k_max + 1)), labels)
    content = {
        "dataset_id": dataset.id,
        "dataset_version": dataset.version,
        "variables": [{"name": name, "label": labels.get(name, name)} for name in variables],
        **result,
        "chosen": result["recommended"],
    }
    existing = ArtifactRepository(db).latest_of_type(project_id, ARTIFACT)
    revision = _save(db, project_id, content, existing)
    return _public(revision)


def update_segmentation(
    db: Session, project_id: str, artifact_id: str, k: int | None, names: dict[str, str]
) -> dict[str, Any]:
    """Choose a solution and rename its segments.

    Args:
        db: Session.
        project_id: Project id.
        artifact_id: Segmentation artifact id.
        k: Solution to choose; None keeps the current choice.
        names: New names by segment number, for the chosen solution.

    Returns:
        The saved segmentation.
    """
    latest = _latest(db, project_id, artifact_id)
    content = dict(latest.content)
    solutions = {solution["k"]: solution for solution in content["solutions"]}
    chosen = int(k) if k is not None else int(content["chosen"])
    if chosen not in solutions:
        raise AppError("That solution was not part of this segmentation.", "bad_request", 400)
    content["chosen"] = chosen
    for profile in solutions[chosen]["profiles"]:
        name = names.get(str(profile["segment"]))
        if name is not None and name.strip():
            profile["name"] = name.strip()[:80]
    content["solutions"] = list(solutions.values())
    return _public(_save(db, project_id, content, latest))


def get_segmentation(db: Session, project_id: str) -> dict[str, Any] | None:
    """The latest segmentation of the project, or None."""
    latest = ArtifactRepository(db).latest_of_type(project_id, ARTIFACT)
    return _public(latest) if latest else None


def typing_tool_workbook(db: Session, storage: Storage, project_id: str, artifact_id: str) -> str:
    """An Excel typing tool for the chosen solution: enter answers, read the segment.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        artifact_id: Segmentation artifact id.

    Returns:
        File id of the workbook.
    """
    from app.services.stored_files import _write_export

    content = _latest(db, project_id, artifact_id).content
    solution = _chosen(content)
    typing = solution["typing"]
    labels = {item["name"]: item["label"] for item in content["variables"]}
    names = {str(p["segment"]): p["name"] for p in solution["profiles"]}
    book = Workbook()
    sheet = book.active
    sheet.title = "Typing tool"
    bold = Font(bold=True)
    entry = PatternFill("solid", fgColor="FFF2CC")
    sheet["A1"] = f"Segment typing tool ({solution['k']} segments)"
    sheet["A1"].font = Font(bold=True, size=13)
    sheet["A2"] = (
        f"Enter the respondent's answers in column C. Holdout accuracy "
        f"{round(100 * typing['accuracy'])}% (all variables: {round(100 * typing['full_accuracy'])}%)."
    )
    sheet["A4"], sheet["B4"], sheet["C4"] = "Variable", "Question", "Answer"
    for cell in ("A4", "B4", "C4"):
        sheet[cell].font = bold
    first = 5
    for offset, name in enumerate(typing["variables"]):
        row = first + offset
        sheet.cell(row=row, column=1, value=name)
        sheet.cell(row=row, column=2, value=labels.get(name, name))
        answer = sheet.cell(row=row, column=3, value=round(content["totals"].get(name, 0), 2))
        answer.fill = entry
    last = first + len(typing["variables"]) - 1
    score_row = last + 2
    sheet.cell(row=score_row, column=1, value="Segment").font = bold
    sheet.cell(row=score_row, column=2, value="Name").font = bold
    sheet.cell(row=score_row, column=3, value="Score").font = bold
    segments = [str(s) for s in typing["segments"]]
    for offset, segment in enumerate(segments):
        row = score_row + 1 + offset
        sheet.cell(row=row, column=1, value=int(segment))
        sheet.cell(row=row, column=2, value=names.get(segment, f"Segment {segment}"))
        terms = [str(typing["intercepts"][segment])]
        for index, name in enumerate(typing["variables"]):
            terms.append(f"({typing['coefficients'][segment][name]})*C{first + index}")
        sheet.cell(row=row, column=3, value="=" + "+".join(terms))
    top, bottom = score_row + 1, score_row + len(segments)
    result_row = bottom + 2
    sheet.cell(row=result_row, column=1, value="Assigned segment").font = bold
    sheet.cell(
        row=result_row,
        column=2,
        value=f"=INDEX(B{top}:B{bottom},MATCH(MAX(C{top}:C{bottom}),C{top}:C{bottom},0))",
    ).font = bold
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 48
    sheet.column_dimensions["C"].width = 14
    buffer = BytesIO()
    book.save(buffer)
    return _write_export(
        db,
        storage,
        project_id,
        f"typing_tool_{solution['k']}_segments.xlsx",
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def save_to_data(
    db: Session, storage: Storage, project_id: str, artifact_id: str
) -> dict[str, Any]:
    """Add the chosen segments to the data as a new dataset version.

    Respondents left out for missing answers get no segment. The new variable is
    ``SEG_<k>`` with the segment names as value labels.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        artifact_id: Segmentation artifact id.

    Returns:
        The new dataset id, its version, and the variable name.
    """
    from app.services.execute import load_frame

    content = _latest(db, project_id, artifact_id).content
    solution = _chosen(content)
    dataset = _dataset(db, project_id)
    if dataset.id != content.get("dataset_id"):
        source = DatasetRepository(db).get(str(content["dataset_id"]))
        if int(source.row_count) != int(dataset.row_count):
            raise AppError(
                "The active data changed since this segmentation was run. Run it again first.",
                "conflict",
                409,
            )
    frame = load_frame(storage, dataset)
    name = f"SEG_{solution['k']}"
    column = pd.Series(pd.NA, index=frame.index, dtype="Float64")
    keys = content["row_index"]
    lookup = {str(index): position for position, index in enumerate(frame.index)}
    for key, segment in zip(keys, solution["assignments"], strict=True):
        position = lookup.get(str(key))
        if position is not None:
            column.iloc[position] = float(segment)
    frame[name] = column
    variables = [item for item in dataset.variables or [] if item.get("name") != name]
    variables.append(
        {
            "name": name,
            "label": f"Segment ({solution['k']}-segment solution)",
            "kind": "numeric",
            "measurement": "nominal",
            "value_labels": {str(float(p["segment"])): p["name"] for p in solution["profiles"]},
            "user_missing_values": [],
            "is_text": False,
        }
    )
    dataset_id = new_id()
    relative = f"datasets/{dataset_id}.parquet"
    snapshot = storage.resolve(project_id, relative)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(snapshot)
    added = DatasetRepository(db).add(
        id=dataset_id,
        project_id=project_id,
        source_file_id=dataset.source_file_id,
        source_sha256=dataset.source_sha256,
        format=dataset.format,
        row_count=int(len(frame)),
        variables=variables,
        weight_candidates=list(dataset.weight_candidates or []),
        version=int(dataset.version) + 1,
        parquet_relpath=relative,
    )
    ProjectRepository(db).get(project_id).active_dataset_id = added.id
    db.flush()
    return {
        "dataset_id": added.id,
        "version": added.version,
        "variable": name,
        "summary": f"Added {name} to the data as dataset version {added.version}.",
    }


# ---------------------------------------------------------------- helpers


def _dataset(db: Session, project_id: str) -> Any:
    project = ProjectRepository(db).get(project_id)
    if not project.active_dataset_id:
        raise AppError("Upload the data first; there is no dataset to segment.", "not_found", 404)
    return DatasetRepository(db).get(project.active_dataset_id)


def _latest(db: Session, project_id: str, artifact_id: str) -> Any:
    repo = ArtifactRepository(db)
    artifact = next(
        (a for a in repo.list_project(project_id) if a.id == artifact_id and a.type == ARTIFACT),
        None,
    )
    latest = repo.latest(artifact.id) if artifact else None
    if latest is None:
        raise AppError("That segmentation was not found.", "not_found", 404)
    return latest


def _chosen(content: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in content["solutions"] if s["k"] == content["chosen"])


def _save(db: Session, project_id: str, content: dict[str, Any], existing: Any) -> Any:
    return ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type=ARTIFACT,
        name="Segmentation",
        content=content,
        content_schema="segmentation/1",
        created_by="segmentation",
        validation_status="passed",
        artifact_id=existing.artifact_id if existing is not None else None,
        expected_version=existing.version if existing is not None else None,
    )


def _public(revision: Any) -> dict[str, Any]:
    content = {
        **revision.content,
        "solutions": [
            {key: value for key, value in solution.items() if key != "assignments"}
            for solution in revision.content["solutions"]
        ],
    }
    content.pop("row_index", None)
    return {"artifact_id": revision.artifact_id, "version": revision.version, **content}


__all__ = [
    "candidate_variables",
    "get_segmentation",
    "run_segmentation",
    "save_to_data",
    "typing_tool_workbook",
    "update_segmentation",
]
