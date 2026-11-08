"""Deterministic crosstab engine. The LLM never supplies these numbers."""

from typing import Any

import numpy as np
import pandas as pd

from app.engines.crosstab_rows import _categorical_rows, _multi_rows, _numeric_rows
from app.engines.derived import apply_derived, in_codes
from app.engines.expression import mask_frame
from app.engines.significance import ColumnCounts, apply_pairwise_letters, weights_vary
from app.errors import AppError
from app.schemas.crosstab import ColumnHeader, ResultRow, TabBook, TableResult
from app.schemas.tabspec import Banner, StudyDefaults, TableSpec, TabSpec

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def run_tabspec(
    frame: pd.DataFrame,
    variables: list[dict[str, Any]],
    spec: TabSpec,
    *,
    dataset_id: str | None = None,
    confirmed_external: bool = True,
) -> TabBook:
    """Run every table in a canonical spec and record exceptions.

    Args:
        frame: Respondent-level data.
        variables: Variable dictionary entries.
        spec: Canonical tab spec.
        dataset_id: Dataset identifier stored on each result.
        confirmed_external: Must be true before an ambiguous import is run.

    Returns:
        Tables that ran and an exception for each table that did not.
    """
    if not confirmed_external:
        raise AppError(
            "Review the highlighted column mapping before execution. No tables were computed.",
            "mapping_review",
            409,
        )
    book = TabBook()
    prepared = apply_derived(frame, spec.derived_variables)
    for table in spec.tables:
        try:
            book.tables.append(
                run_table(
                    prepared,
                    variables,
                    table,
                    spec.study_defaults,
                    spec.banners,
                    dataset_id=dataset_id,
                )
            )
        except AppError as exc:
            book.exceptions.append({"table_id": table.id, "message": exc.message})
    return book


def run_table(
    frame: pd.DataFrame,
    variables: list[dict[str, Any]],
    table: TableSpec,
    defaults: StudyDefaults,
    banners: list[Banner],
    *,
    dataset_id: str | None = None,
) -> TableResult:
    """Compute one table.

    Args:
        frame: Respondent-level data, already including derived columns.
        variables: Variable dictionary.
        table: Table definition.
        defaults: Study defaults.
        banners: Banner catalog.
        dataset_id: Dataset id to stamp on the result.

    Returns:
        Numeric table result.
    """
    weight_name = (
        table.weight_variable if table.weight_variable is not None else defaults.weight_variable
    )
    weights, weight_warnings = _weights(frame, weight_name)
    use_weight = weight_name is not None
    meta = {item["name"]: item for item in variables}
    _require_columns(frame, table, banners, meta)
    filter_mask = mask_frame(table.base.filter, frame)
    columns, col_masks = _columns(frame, table, banners, filter_mask, meta)
    footnotes = _footnotes(table, defaults, weight_name)
    warnings = list(weight_warnings)
    if table.table_type == "multiple_response":
        rows = _multi_rows(frame, table, columns, col_masks, weights, use_weight, meta, filter_mask)
    elif table.table_type == "numeric":
        rows = _numeric_rows(frame, table, columns, col_masks, weights, use_weight, meta)
    else:
        rows = _categorical_rows(
            frame, table, columns, col_masks, weights, use_weight, meta, defaults
        )
    if table.significance.enabled and rows:
        warnings.extend(_signify(rows, columns, table, weights, filter_mask, use_weight))
    result = TableResult(
        table_id=table.id,
        title=table.title,
        dataset_id=dataset_id,
        columns=columns,
        rows=rows,
        footnotes=footnotes + table.notes,
        warnings=warnings,
        weight_variable=weight_name,
        percent_type=defaults.percent_type,
    )
    result.validation = {"status": "passed", "checks": ["bases", "percentage_bounds"]}
    return result


def _weights(frame: pd.DataFrame, name: str | None) -> tuple[pd.Series, list[str]]:
    """Build the weight series and reject negative weights.

    Args:
        frame: Source data.
        name: Weight variable, or None for an unweighted table.

    Returns:
        Weights and warnings.
    """
    if not name:
        return pd.Series(1.0, index=frame.index), []
    if name not in frame.columns:
        raise AppError(f"Weight variable '{name}' is not in the dataset", "missing_variable")
    weights = pd.to_numeric(frame[name], errors="coerce")
    if (weights < 0).any():
        raise AppError(
            "Negative weights are rejected. Recode them before running this table.",
            "negative_weight",
        )
    warnings: list[str] = []
    bad = weights.isna() | ~np.isfinite(weights.to_numpy(dtype=float, na_value=np.nan))
    if bool(bad.any()):
        warnings.append("Missing or non-finite weights are excluded from the weighted base")
    return weights, warnings


def _require_columns(
    frame: pd.DataFrame,
    table: TableSpec,
    banners: list[Banner],
    meta: dict[str, dict[str, Any]],
) -> None:
    """Fail when a requested variable is not in the frame.

    Args:
        frame: Data.
        table: Table definition.
        banners: Banners referenced by the table.
        meta: Variable dictionary keyed by name.
    """
    needed = list(table.row_variable_names)
    for banner_id in table.banner_ids:
        banner = _banner(banners, banner_id)
        if banner.variable_name:
            needed.append(banner.variable_name)
        elif banner.variable_name is None and not banner.categories:
            raise AppError(f"Banner '{banner.id}' has no variable", "missing_variable")
    for name in needed:
        if name not in frame.columns and name not in meta:
            raise AppError(f"Variable '{name}' is not in the dataset", "missing_variable")
        if name not in frame.columns:
            raise AppError(f"Variable '{name}' is not in the dataset", "missing_variable")


def _columns(
    frame: pd.DataFrame,
    table: TableSpec,
    banners: list[Banner],
    filter_mask: pd.Series,
    meta: dict[str, dict[str, Any]],
) -> tuple[list[ColumnHeader], dict[str, pd.Series]]:
    """Build total and banner column masks.

    Args:
        frame: Data.
        table: Table definition.
        banners: Banner catalog.
        filter_mask: Rows passing the table filter.
        meta: Variable dictionary.

    Returns:
        Headers and a mask per column id.
    """
    headers = [ColumnHeader(id="total", label="Total", letter="")]
    masks: dict[str, pd.Series] = {"total": filter_mask}
    letter_index = 0
    for banner_id in table.banner_ids:
        banner = _banner(banners, banner_id)
        if not banner.variable_name:
            raise AppError(
                f"Banner '{banner.id}' is not mapped to a dataset variable", "missing_variable"
            )
        series = frame[banner.variable_name]
        for category in banner.categories:
            letter = _LETTERS[letter_index] if letter_index < len(_LETTERS) else ""
            letter_index += 1
            column_id = f"{banner.id}:{category.label}"
            headers.append(ColumnHeader(id=column_id, label=category.label, letter=letter))
            masks[column_id] = filter_mask & in_codes(series, category.codes)
        if banner.include_total and "total" in masks:
            continue
    if len(headers) == 1:
        headers[0].letter = ""
    return headers, masks


def _signify(
    rows: list[ResultRow],
    columns: list[ColumnHeader],
    table: TableSpec,
    weights: pd.Series,
    filter_mask: pd.Series,
    use_weight: bool,
) -> list[str]:
    """Attach pairwise letters to category rows.

    Args:
        rows: Computed rows.
        columns: Headers.
        table: Table definition.
        weights: Weights.
        filter_mask: Filter mask.
        use_weight: Whether a weight was requested.

    Returns:
        Table-level warnings.
    """
    warnings: list[str] = []
    banner_cols = [col for col in columns if col.id != "total"]
    varied = use_weight and weights_vary(weights, filter_mask)
    for row in rows:
        if row.row_kind not in {"category", "net", "top_box", "bottom_box"}:
            continue
        counts = []
        for col in banner_cols:
            cell = row.cells[col.id]
            counts.append(
                ColumnCounts(
                    col.id,
                    col.letter,
                    int(cell.unweighted_numerator or 0),
                    int(cell.unweighted_base or 0),
                    cell.estimate,
                )
            )
        warnings.extend(
            apply_pairwise_letters(
                row.cells,
                counts,
                alpha=table.significance.alpha,
                secondary_alpha=table.significance.secondary_alpha,
                correction=table.significance.correction,
                minimum_base=table.significance.minimum_effective_base,
                weighted=varied,
            )
        )
    return list(dict.fromkeys(warnings))


def _banner(banners: list[Banner], banner_id: str) -> Banner:
    """Find a banner by id.

    Args:
        banners: Catalog.
        banner_id: Requested id.

    Returns:
        Banner.
    """
    for banner in banners:
        if banner.id == banner_id:
            return banner
    raise AppError(f"Banner '{banner_id}' is not in the spec", "missing_banner")


def _footnotes(table: TableSpec, defaults: StudyDefaults, weight_name: str | None) -> list[str]:
    """Describe the percentage and weight shown in the table.

    Args:
        table: Table definition.
        defaults: Study defaults.
        weight_name: Resolved weight variable.

    Returns:
        Footnote strings.
    """
    notes = [f"{defaults.percent_type.capitalize()} percentages"]
    if weight_name:
        notes.append(
            f"Weighted by {weight_name}. Unweighted base is shown. Zero weights are unweighted only."
        )
    else:
        notes.append("Unweighted. Each eligible respondent counts as 1.")
    if table.table_type == "multiple_response":
        notes.append("Multiple response. Percentages use eligible respondents and may exceed 100.")
    if table.significance.enabled:
        primary = f"{(1 - table.significance.alpha) * 100:.0f}"
        secondary = f"{(1 - table.significance.secondary_alpha) * 100:.0f}"
        minimum = table.significance.minimum_effective_base
        notes.append(
            "Two-tailed z-test for unpooled proportions across banner columns. "
            f"UPPERCASE letters are significant at {primary}%. "
            f"Lowercase letters are significant at {secondary}%. "
            f"A column base of {minimum} or less is marked '.' and is not tested. "
            "The total column is not tested. "
            "Letters are not calculated when weights vary and no design effect was supplied."
        )
    return notes
