"""Fit a report plan to the cleaned data: map variables, compute bases, flag what can't be reported."""

import re
from typing import Any

import pandas as pd

from app.engines.analysis import standards as std
from app.engines.analysis.steps import mask_off_scale, mask_user_missing
from app.schemas.report_plan import PlanSlide, ReportPlan

_FILTER = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<|in)\s*(.+?)\s*$")
_MIN_ANALYSIS = {"clustering": 200, "pam_gower": 200, "key_driver": 100, "efa": 150, "pca": 150}


def fit_data(plan: ReportPlan, frame: pd.DataFrame, variables: list[dict[str, Any]]) -> ReportPlan:
    """Return the plan with each slide's base, status and reason set from the data.

    Args:
        plan: The current plan.
        frame: Cleaned respondent data.
        variables: Variable dictionary.

    Returns:
        Updated plan. Slides the user dropped stay dropped.
    """
    plan = plan.model_copy(deep=True)
    data = mask_user_missing(frame, variables)
    data, _ = mask_off_scale(data, variables)
    missing_all: set[str] = set()
    columns = [str(c) for c in data.columns]
    for slide in plan.all_slides():
        if slide.status == "dropped" or slide.kind in {"title", "text"}:
            continue
        _rename_to_data(slide, columns)
        _fit_slide(slide, data, missing_all)
    plan.data.missing_variables = sorted(missing_all)
    return plan


def apply_filter(frame: pd.DataFrame, text: str) -> pd.Series:
    """Rows kept by a plain filter such as ``Q5r1 == 1`` or ``S7 in [1, 2]``; all rows when empty."""
    if not text.strip():
        return pd.Series(True, index=frame.index)
    match = _FILTER.match(text)
    if not match or match.group(1) not in frame.columns:
        raise ValueError(
            f"Filter '{text}' is not a simple 'VARIABLE == value' rule on a known column."
        )
    name, op, raw = match.groups()
    column = pd.to_numeric(frame[name], errors="coerce")
    if op == "in":
        values = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", raw)]
        return column.isin(values)
    value = float(raw)
    return {
        "==": column == value,
        "!=": column != value,
        ">=": column >= value,
        "<=": column <= value,
        ">": column > value,
        "<": column < value,
    }[op]


_GRID_NAME = re.compile(r"^([A-Za-z]+\d+)([A-Za-z_]+)(\d+)$")


def data_name(name: str, columns: list[str]) -> str:
    """The dataset column for a questionnaire variable name, or the name unchanged.

    The questionnaire may list a grid row as ``Q10a3`` while the programmed survey
    exports it as ``Q10r3``. When the listed name is missing and exactly one
    column has the same question id and row number, that column is used.
    """
    if name in columns:
        return name
    match = _GRID_NAME.match(name)
    if not match:
        return name
    stem, _, row = match.groups()
    pattern = re.compile(rf"^{re.escape(stem)}([A-Za-z_]+){row}$")
    found = [c for c in columns if pattern.match(c) and not c.lower().endswith("oe")]
    return found[0] if len(found) == 1 else name


def _rename_to_data(slide: PlanSlide, columns: list[str]) -> None:
    source = slide.source
    source.variables = [data_name(v, columns) for v in source.variables]
    if source.banner:
        source.banner = data_name(source.banner, columns)
    match = _FILTER.match(source.filter or "")
    if match and match.group(1) not in columns:
        renamed = data_name(match.group(1), columns)
        source.filter = source.filter.replace(match.group(1), renamed, 1)
    if source.analysis_request:
        for old in re.findall(r"\b[A-Za-z]+\d+[A-Za-z_]+\d+\b", source.analysis_request):
            new = data_name(old, columns)
            if new != old:
                source.analysis_request = re.sub(rf"\b{old}\b", new, source.analysis_request)


def _fit_slide(slide: PlanSlide, data: pd.DataFrame, missing_all: set[str]) -> None:
    present = [v for v in slide.source.variables if v in data.columns]
    missing = [v for v in slide.source.variables if v not in data.columns]
    missing_all.update(missing)
    if slide.source.banner and slide.source.banner not in data.columns:
        missing.append(slide.source.banner)
    if not present:
        _status(
            slide,
            "needs_data",
            "Not in the data: " + ", ".join(missing[:6]) if missing else "No variables named.",
        )
        return
    try:
        rows = apply_filter(data, slide.source.filter)
    except ValueError as error:
        _status(slide, "needs_data", str(error))
        return
    block = data.loc[rows, present]
    if slide.kind == "coding":
        answered = block.astype(str).apply(lambda col: col.str.strip().ne("") & col.ne("nan"))
        base = int(answered.any(axis=1).sum())
    else:
        base = int(block.notna().any(axis=1).sum())
    slide.base_n = base
    need = (
        _MIN_ANALYSIS.get(slide.source.method, std.LOW_BASE)
        if slide.kind == "analysis"
        else std.MIN_BASE
    )
    if base < need:
        _status(
            slide,
            "low_base",
            f"Base of {base} is under {need}, so this slide cannot be reported reliably.",
        )
    elif missing:
        _status(slide, "planned", "Some variables are not in the data: " + ", ".join(missing[:6]))
    elif base < std.LOW_BASE:
        _status(slide, "planned", f"Base of {base}: directional only.")
    else:
        _status(slide, "planned", "")
    if slide.source.banner and slide.source.banner in data.columns and slide.status == "planned":
        column = data.loc[rows, slide.source.banner]
        if column.nunique() > 8:
            # Reason: a numeric banner such as age is banded when charted, not split by value.
            return
        groups = column.value_counts()
        small = groups[groups < std.MIN_BASE]
        if not small.empty:
            slide.status_reason = (
                (slide.status_reason + " " if slide.status_reason else "")
                + f"{len(small)} {slide.source.banner} group(s) under {std.MIN_BASE}; shown as directional."
            )


def _status(slide: PlanSlide, status: str, reason: str) -> None:
    slide.status = status  # type: ignore[assignment]
    slide.status_reason = reason
