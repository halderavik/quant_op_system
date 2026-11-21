"""Tracking studies: start the next wave, see what changed, and trend results across waves.

A wave is an ordinary project. ``study_context["tracking"]`` links it into a series:
``{"series": <first wave's project id>, "wave": 2, "label": "Q2 2026",
"previous_project_id": ...}``.

* **Next wave** copies the latest questionnaire (with its programming logic), tab
  spec, weighting setup, and report plan into a new project, so the survey can be
  programmed again without re-planning. Data, XML, and outputs are not copied.
* **Wave changes** compares this wave's questionnaire with the previous wave's,
  flagging what breaks trend comparability (wording, answer lists, bases).
* **Trend table** reads each wave's active dataset and puts the same variables side
  by side, testing each wave against the one before it.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.engines.significance import ColumnCounts, _two_means, _two_proportion
from app.errors import AppError
from app.repositories.records import ArtifactRepository, DatasetRepository, ProjectRepository
from app.schemas.questionnaire import Question, Questionnaire
from app.services.storage import Storage

COPIED_TYPES = ("questionnaire", "tabspec", "weighting", "report_plan")
ALPHA = 0.05
MAX_TREND_VARIABLES = 60
_WORDING_SAME = 0.97


def tracking_info(project: Any) -> dict[str, Any]:
    """The project's place in a tracking series, or an empty dict."""
    return dict((project.study_context or {}).get("tracking") or {})


def series(db: Session, project_id: str) -> list[dict[str, Any]]:
    """Every wave of the project's series, oldest first.

    Args:
        db: Session.
        project_id: Any wave's project id.

    Returns:
        One row per wave: project id, name, wave number, label, and active dataset.
    """
    projects = ProjectRepository(db)
    current = projects.get(project_id)
    info = tracking_info(current)
    if not info:
        return []
    waves = [
        project
        for project in projects.list()
        if tracking_info(project).get("series") == info.get("series")
    ]
    waves.sort(key=lambda project: int(tracking_info(project).get("wave") or 0))
    return [
        {
            "project_id": project.id,
            "name": project.name,
            "wave": int(tracking_info(project).get("wave") or 0),
            "label": tracking_info(project).get("label")
            or f"Wave {tracking_info(project).get('wave')}",
            "has_data": bool(project.active_dataset_id),
            "current": project.id == project_id,
        }
        for project in waves
    ]


def start_next_wave(db: Session, project_id: str, name: str, label: str) -> dict[str, Any]:
    """Create the next wave as a new project with this wave's study materials.

    Args:
        db: Session.
        project_id: The wave to continue from (its latest materials are copied).
        name: New project name.
        label: Wave label, such as "Wave 2" or "Q3 2026".

    Returns:
        The new project id, its wave number, and what was copied.
    """
    projects = ProjectRepository(db)
    source = projects.get(project_id)
    info = tracking_info(source)
    if not info:
        info = {"series": source.id, "wave": 1, "label": "Wave 1"}
        source.study_context = {**(source.study_context or {}), "tracking": info}
    waves = series(db, project_id)
    number = max([wave["wave"] for wave in waves] + [int(info.get("wave") or 1)]) + 1
    context = {
        key: value for key, value in (source.study_context or {}).items() if key != "tracking"
    }
    context["tracking"] = {
        "series": info["series"],
        "wave": number,
        "label": label.strip() or f"Wave {number}",
        "previous_project_id": project_id,
    }
    created = projects.create(name.strip() or f"{source.name} – Wave {number}", context)
    created.default_weight_variable = source.default_weight_variable
    artifacts = ArtifactRepository(db)
    copied: list[str] = []
    for artifact in artifacts.list_project(project_id):
        if artifact.type not in COPIED_TYPES:
            continue
        latest = artifacts.latest(artifact.id)
        if latest is None:
            continue
        artifacts.create(
            project_id=created.id,
            artifact_type=artifact.type,
            name=artifact.name,
            content=latest.content,
            content_schema=latest.content_schema,
            created_by="tracking",
            derived_from=[{"id": artifact.id, "version": latest.version, "type": artifact.type}],
            validation_status=latest.validation_status,
        )
        copied.append(artifact.type)
    db.flush()
    return {
        "project_id": created.id,
        "name": created.name,
        "wave": number,
        "label": context["tracking"]["label"],
        "copied": sorted(set(copied)),
        "summary": (
            f"Started {context['tracking']['label']} as a new project and copied "
            f"{', '.join(sorted(set(copied))) or 'nothing'} from the previous wave. "
            "Program the survey again to get this wave's XML; its logic is already planned."
        ),
    }


# ---------------------------------------------------------------- wave changes


def wave_changes(db: Session, project_id: str) -> dict[str, Any]:
    """What changed in the questionnaire since the previous wave.

    Args:
        db: Session.
        project_id: This wave's project id.

    Returns:
        Per-question changes and counts; ``breaks_trend`` marks changes that make
        a question's results not directly comparable with the previous wave.
    """
    project = ProjectRepository(db).get(project_id)
    previous_id = tracking_info(project).get("previous_project_id")
    if not previous_id:
        raise AppError("This project is not a later wave of a tracking study.", "bad_request", 400)
    artifacts = ArtifactRepository(db)
    now = artifacts.latest_of_type(project_id, "questionnaire")
    before = artifacts.latest_of_type(str(previous_id), "questionnaire")
    if now is None or before is None:
        raise AppError("Both waves need a questionnaire to compare.", "not_found", 404)
    return compare_waves(
        Questionnaire.model_validate(before.content), Questionnaire.model_validate(now.content)
    )


def compare_waves(before: Questionnaire, now: Questionnaire) -> dict[str, Any]:
    """Compare two waves' questionnaires question by question.

    Args:
        before: Previous wave.
        now: This wave.

    Returns:
        Changes in this wave's order, then removed questions, with counts.
    """
    old = {question.id: question for question in before.questions}
    new_ids = {question.id for question in now.questions}
    rows: list[dict[str, Any]] = []
    for question in now.questions:
        previous = old.get(question.id)
        if previous is None:
            rows.append(_change(question.id, "added", ["New this wave."], False))
            continue
        notes, breaks = _differences(previous, question)
        if notes:
            rows.append(_change(question.id, "changed", notes, breaks))
    for question in before.questions:
        if question.id not in new_ids:
            rows.append(_change(question.id, "removed", ["Dropped this wave."], True))
    return {
        "changes": rows,
        "added": sum(row["status"] == "added" for row in rows),
        "removed": sum(row["status"] == "removed" for row in rows),
        "changed": sum(row["status"] == "changed" for row in rows),
        "breaks_trend": sum(row["breaks_trend"] for row in rows if row["status"] != "added"),
        "unchanged": sum(1 for question in now.questions if question.id in old)
        - sum(row["status"] == "changed" for row in rows),
    }


def _change(question_id: str, status: str, notes: list[str], breaks: bool) -> dict[str, Any]:
    return {"question_id": question_id, "status": status, "notes": notes, "breaks_trend": breaks}


def _differences(before: Question, now: Question) -> tuple[list[str], bool]:
    """Plain-language differences, and whether any of them breaks the trend."""
    notes: list[str] = []
    breaks = False
    if before.type != now.type:
        notes.append(f"Question type changed from {before.type} to {now.type}.")
        breaks = True
    ratio = SequenceMatcher(None, _norm(before.text), _norm(now.text)).ratio()
    if ratio < _WORDING_SAME:
        notes.append(f"Wording changed ({round(100 * ratio)}% the same).")
        breaks = breaks or ratio < 0.85
    old_options = {str(option.code): option.label for option in before.options}
    new_options = {str(option.code): option.label for option in now.options}
    added = [code for code in new_options if code not in old_options]
    removed = [code for code in old_options if code not in new_options]
    relabeled = [
        code
        for code in new_options
        if code in old_options
        and SequenceMatcher(None, _norm(old_options[code]), _norm(new_options[code])).ratio()
        < _WORDING_SAME
    ]
    if added:
        notes.append(f"Answers added: {', '.join(f'{c} {new_options[c]}' for c in added[:8])}.")
        breaks = True
    if removed:
        notes.append(f"Answers removed: {', '.join(f'{c} {old_options[c]}' for c in removed[:8])}.")
        breaks = True
    if relabeled:
        notes.append(
            "Answer wording changed: "
            + "; ".join(f"{c} '{old_options[c]}' → '{new_options[c]}'" for c in relabeled[:6])
            + "."
        )
        breaks = True
    if before.matrix_items != now.matrix_items:
        notes.append("Grid rows changed.")
        breaks = True
    if _json(before.display_if) != _json(now.display_if):
        notes.append("Base (who is asked) changed.")
        breaks = True
    if before.randomize_options != now.randomize_options:
        notes.append(
            "Answer order is now randomized."
            if now.randomize_options
            else "Answers are no longer randomized."
        )
    return notes, breaks


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _json(value: Any) -> Any:
    return value.model_dump(mode="json") if value is not None else None


# ---------------------------------------------------------------- trend tables


def trend_table(
    db: Session, storage: Storage, project_id: str, variables: list[str]
) -> dict[str, Any]:
    """Put the same variables side by side for every wave that has data.

    Each wave is tested against the wave before it: proportions with an unpooled
    z-test, means with a Welch t-test, at 95%. Weighted waves use each wave's
    project weight and the effective base.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Any wave's project id.
        variables: Variable names, as in the datasets.

    Returns:
        Waves and one table per variable.
    """
    from app.services.execute import load_frame

    waves = [wave for wave in series(db, project_id) if wave["has_data"]]
    if len(waves) < 2:
        raise AppError("A trend needs at least two waves with data.", "bad_request", 400)
    if not variables:
        raise AppError("Choose at least one variable to trend.", "bad_request", 400)
    if len(variables) > MAX_TREND_VARIABLES:
        raise AppError(
            f"Trend up to {MAX_TREND_VARIABLES} variables at a time.", "bad_request", 400
        )
    projects = ProjectRepository(db)
    datasets = DatasetRepository(db)
    frames: list[tuple[dict[str, Any], pd.DataFrame, pd.Series | None, dict[str, Any]]] = []
    for wave in waves:
        project = projects.get(wave["project_id"])
        dataset = datasets.get(str(project.active_dataset_id))
        frame = load_frame(storage, dataset)
        weight_name = project.default_weight_variable
        weights = (
            pd.to_numeric(frame[weight_name], errors="coerce").fillna(0)
            if weight_name and weight_name in frame.columns
            else None
        )
        meta = {item.get("name"): item for item in dataset.variables or []}
        frames.append((wave, frame, weights, meta))
    tables = [_trend_one(name, frames) for name in variables]
    return {
        "waves": [
            {k: wave[k] for k in ("project_id", "wave", "label", "current")} for wave, *_ in frames
        ],
        "tables": tables,
        "note": "Each wave is tested against the wave before it at 95% confidence.",
    }


def _trend_one(
    name: str,
    frames: list[tuple[dict[str, Any], pd.DataFrame, pd.Series | None, dict[str, Any]]],
) -> dict[str, Any]:
    """One variable across waves."""
    present = [
        (wave, frame, weights, meta)
        for wave, frame, weights, meta in frames
        if name in frame.columns
    ]
    missing = [wave["label"] for wave, frame, *_ in frames if name not in frame.columns]
    if not present:
        return {"variable": name, "label": name, "rows": [], "missing_in": missing}
    meta = present[-1][3].get(name) or {}
    labels = {_label_key(k): str(v) for k, v in (meta.get("value_labels") or {}).items()}
    series_by_wave = [pd.to_numeric(frame[name], errors="coerce") for _, frame, _, _ in present]
    values = sorted({v for s in series_by_wave for v in s.dropna().unique().tolist()})
    categorical = bool(labels) or (len(values) <= 12 and all(float(v).is_integer() for v in values))
    rows: list[dict[str, Any]] = []
    bases = []
    for (wave, frame, weights, _), data in zip(present, series_by_wave, strict=True):
        mask = data.notna()
        bases.append({"wave": wave["label"], "base": int(mask.sum())})
    if categorical:
        codes = [_key(v) for v in values]
        for code in codes:
            cells = []
            previous: ColumnCounts | None = None
            for (wave, _, weights, _), data in zip(present, series_by_wave, strict=True):
                counts = _proportion(data, weights, code, wave["label"])
                p_value = (
                    _two_proportion(counts, previous, weighted=weights is not None)
                    if previous is not None
                    else None
                )
                cells.append(_cell(counts, previous, p_value))
                previous = counts
            rows.append({"code": code, "label": labels.get(code, code), "cells": cells})
    previous = None
    cells = []
    for (wave, _, weights, _), data in zip(present, series_by_wave, strict=True):
        counts = _mean(data, weights, wave["label"])
        p_value = (
            _two_means(counts, previous, weighted=weights is not None)
            if previous is not None
            else None
        )
        cells.append(_cell(counts, previous, p_value, percent=False))
        previous = counts
    if not categorical:
        rows.append({"code": "mean", "label": "Mean", "cells": cells, "kind": "mean"})
    return {
        "variable": name,
        "label": str(meta.get("label") or name),
        "kind": "categorical" if categorical else "numeric",
        "bases": bases,
        "rows": rows,
        "missing_in": missing,
    }


def _proportion(data: pd.Series, weights: pd.Series | None, code: str, label: str) -> ColumnCounts:
    mask = data.notna()
    hit = mask & (data.map(_key) == code)
    count, base = int(hit.sum()), int(mask.sum())
    if weights is None:
        estimate = 100.0 * count / base if base else None
        return ColumnCounts(label, "", count, base, estimate, effective_base=float(base))
    w = weights[mask]
    total = float(w.sum())
    estimate = 100.0 * float(weights[hit].sum()) / total if total > 0 else None
    return ColumnCounts(label, "", count, base, estimate, effective_base=_kish(w))


def _mean(data: pd.Series, weights: pd.Series | None, label: str) -> ColumnCounts:
    valid = data.dropna()
    base = int(valid.size)
    if base == 0:
        return ColumnCounts(label, "", 0, 0, None)
    if weights is None:
        sd = float(valid.std(ddof=1)) if base > 1 else None
        return ColumnCounts(label, "", base, base, float(valid.mean()), sd, float(base))
    w = weights[valid.index].astype(float)
    total = float(w.sum())
    if total <= 0:
        return ColumnCounts(label, "", base, base, None)
    mean = float(np.average(valid, weights=w))
    sd = sqrt(float(np.average((valid - mean) ** 2, weights=w))) if base > 1 else None
    return ColumnCounts(label, "", base, base, mean, sd, _kish(w))


def _cell(
    counts: ColumnCounts, previous: ColumnCounts | None, p_value: float | None, percent: bool = True
) -> dict[str, Any]:
    change = None
    if previous is not None and counts.estimate is not None and previous.estimate is not None:
        change = round(counts.estimate - previous.estimate, 2)
    significant = p_value is not None and p_value < ALPHA
    return {
        "wave": counts.column_id,
        "value": round(counts.estimate, 1 if percent else 2)
        if counts.estimate is not None
        else None,
        "base": counts.base,
        "change": change,
        "significant": significant,
        "direction": ("up" if (change or 0) > 0 else "down") if significant else None,
    }


def _kish(weights: pd.Series) -> float:
    total = float(weights.sum())
    squares = float((weights**2).sum())
    return total * total / squares if squares > 0 else 0.0


def _label_key(raw: Any) -> str:
    """Value-label keys arrive as "1.0" from SPSS; codes are compared as "1"."""
    try:
        return _key(raw)
    except (TypeError, ValueError):
        return str(raw)


def _key(value: Any) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def common_variables(db: Session, project_id: str) -> list[dict[str, str]]:
    """Variables every wave with data has, for picking what to trend.

    Args:
        db: Session.
        project_id: Any wave's project id.

    Returns:
        Name and label of each variable present in every wave's dataset.
    """
    projects = ProjectRepository(db)
    datasets = DatasetRepository(db)
    names: list[str] | None = None
    labels: dict[str, str] = {}
    for wave in series(db, project_id):
        if not wave["has_data"]:
            continue
        dataset = datasets.get(str(projects.get(wave["project_id"]).active_dataset_id))
        here = [
            str(item.get("name")) for item in dataset.variables or [] if not item.get("is_text")
        ]
        for item in dataset.variables or []:
            labels[str(item.get("name"))] = str(item.get("label") or item.get("name"))
        names = here if names is None else [name for name in names if name in set(here)]
    return [{"name": name, "label": labels.get(name, name)} for name in names or []]


__all__ = [
    "common_variables",
    "compare_waves",
    "series",
    "start_next_wave",
    "tracking_info",
    "trend_table",
    "wave_changes",
]
