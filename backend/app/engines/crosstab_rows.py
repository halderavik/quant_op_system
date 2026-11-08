"""Row builders for the crosstab engine."""

from typing import Any

import numpy as np
import pandas as pd

from app.engines.derived import in_codes
from app.schemas.crosstab import CellResult, ColumnHeader, ResultRow
from app.schemas.tabspec import StudyDefaults, TableSpec


def _categorical_rows(
    frame: pd.DataFrame,
    table: TableSpec,
    columns: list[ColumnHeader],
    masks: dict[str, pd.Series],
    weights: pd.Series,
    use_weight: bool,
    meta: dict[str, dict[str, Any]],
    defaults: StudyDefaults,
) -> list[ResultRow]:
    """Compute exclusive category, net, and box rows.

    Args:
        frame: Data.
        table: Table definition.
        columns: Column headers.
        masks: Column masks before item eligibility.
        weights: Weight series.
        use_weight: Whether a weight variable was requested.
        meta: Variable dictionary.
        defaults: Study defaults, including percent type.

    Returns:
        Stub rows.
    """
    name = table.row_variable_names[0]
    info = meta.get(name, {})
    series = frame[name]
    missing = list(info.get("user_missing_values") or [])
    eligible = _eligible(series, missing, table.base.valid_response_rule)
    labels = dict(info.get("value_labels") or {})
    codes = list(labels.keys()) or _observed_codes(series, missing)
    rows: list[ResultRow] = []
    for code in codes:
        rows.append(
            _stub(
                code,
                str(labels.get(code, labels.get(str(code), code))),
                "category",
                in_codes(series, [code]),
                eligible,
                columns,
                masks,
                weights,
                use_weight,
                defaults.percent_type,
                table.display_decimals,
            )
        )
    for net in table.nets:
        rows.append(
            _stub(
                net.id,
                net.label,
                "net",
                in_codes(series, net.child_codes),
                eligible,
                columns,
                masks,
                weights,
                use_weight,
                defaults.percent_type,
                table.display_decimals,
            )
        )
    if table.top_box_codes:
        rows.append(
            _stub(
                "top_box",
                "Top box",
                "top_box",
                in_codes(series, table.top_box_codes),
                eligible,
                columns,
                masks,
                weights,
                use_weight,
                defaults.percent_type,
                table.display_decimals,
            )
        )
    if table.bottom_box_codes:
        rows.append(
            _stub(
                "bottom_box",
                "Bottom box",
                "bottom_box",
                in_codes(series, table.bottom_box_codes),
                eligible,
                columns,
                masks,
                weights,
                use_weight,
                defaults.percent_type,
                table.display_decimals,
            )
        )
    return rows


def _multi_rows(
    frame: pd.DataFrame,
    table: TableSpec,
    columns: list[ColumnHeader],
    masks: dict[str, pd.Series],
    weights: pd.Series,
    use_weight: bool,
    meta: dict[str, dict[str, Any]],
    filter_mask: pd.Series,
) -> list[ResultRow]:
    """Compute multiple-response rows. The base is respondents, not mentions.

    Args:
        frame: Data.
        table: Table definition.
        columns: Column headers.
        masks: Column masks.
        weights: Weights.
        use_weight: Whether weights were requested.
        meta: Variable dictionary.
        filter_mask: Table filter.

    Returns:
        One row per option, plus nets.
    """
    selected = []
    eligible = filter_mask.copy()
    any_answered = pd.Series(False, index=frame.index)
    for name in table.row_variable_names:
        info = meta.get(name, {})
        series = frame[name]
        answered = ~_missing_mask(series, list(info.get("user_missing_values") or []))
        any_answered = any_answered | answered
        selected.append((name, in_codes(series, [1])))
    eligible = filter_mask & any_answered
    rows = []
    union = pd.Series(False, index=frame.index)
    for name, chosen in selected:
        label = str(meta.get(name, {}).get("label") or name)
        union = union | chosen
        rows.append(
            _stub(
                name,
                label,
                "category",
                chosen,
                eligible,
                columns,
                masks,
                weights,
                use_weight,
                "column",
                table.display_decimals,
            )
        )
    for net in table.nets:
        member = pd.Series(False, index=frame.index)
        for name, chosen in selected:
            if name in net.child_variables:
                member = member | chosen
        rows.append(
            _stub(
                net.id,
                net.label,
                "net",
                member,
                eligible,
                columns,
                masks,
                weights,
                use_weight,
                "column",
                table.display_decimals,
            )
        )
    return rows


def _numeric_rows(
    frame: pd.DataFrame,
    table: TableSpec,
    columns: list[ColumnHeader],
    masks: dict[str, pd.Series],
    weights: pd.Series,
    use_weight: bool,
    meta: dict[str, dict[str, Any]],
) -> list[ResultRow]:
    """Compute a weighted or unweighted mean row.

    Args:
        frame: Data.
        table: Table definition.
        columns: Column headers.
        masks: Column masks.
        weights: Weights.
        use_weight: Whether weights were requested.
        meta: Variable dictionary.

    Returns:
        A single mean row.
    """
    name = table.row_variable_names[0]
    series = pd.to_numeric(frame[name], errors="coerce")
    missing = list(meta.get(name, {}).get("user_missing_values") or [])
    eligible = _eligible(series, missing, table.base.valid_response_rule)
    cells: dict[str, CellResult] = {}
    for column in columns:
        mask = masks[column.id] & eligible & series.notna()
        unw, wbase = _bases(mask, weights)
        values = series[mask]
        w = weights[mask]
        if use_weight:
            keep = w.notna() & np.isfinite(w) & (w > 0)
            denom = float(w[keep].sum())
            estimate = float((values[keep] * w[keep]).sum() / denom) if denom else None
        else:
            estimate = float(values.mean()) if unw else None
        cells[column.id] = _cell(
            estimate,
            unw,
            wbase,
            unw if not use_weight else None,
            wbase,
            table.display_decimals,
            percent=False,
        )
    return [ResultRow(code=name, label="Mean", row_kind="mean", cells=cells)]


def _stub(
    code: Any,
    label: str,
    kind: str,
    chosen: pd.Series,
    eligible: pd.Series,
    columns: list[ColumnHeader],
    masks: dict[str, pd.Series],
    weights: pd.Series,
    use_weight: bool,
    percent_type: str,
    decimals: int,
) -> ResultRow:
    """Build one stub row.

    Args:
        code: Row code.
        label: Row label.
        kind: Row kind.
        chosen: Respondents in the category.
        eligible: Respondents in the question base.
        columns: Headers.
        masks: Column masks.
        weights: Weights.
        use_weight: Whether to use weights in the percentage.
        percent_type: ``column``, ``row``, or ``total``.
        decimals: Display decimals.

    Returns:
        Result row.
    """
    bases = {}
    nums = {}
    for column in columns:
        mask = masks[column.id] & eligible
        bases[column.id] = (*_bases(mask, weights), mask)
        nums[column.id] = (
            int((mask & chosen).sum()),
            _positive_sum(mask & chosen, weights),
        )
    total_unw, total_w, _ = bases["total"]
    row_unw = sum(nums[col.id][0] for col in columns if col.id != "total")
    row_w = sum(nums[col.id][1] for col in columns if col.id != "total")
    cells: dict[str, CellResult] = {}
    for column in columns:
        unw, wbase, _mask = bases[column.id]
        unum, wnum = nums[column.id]
        if percent_type == "total":
            den_u, den_w = total_unw, total_w
        elif percent_type == "row" and column.id != "total":
            den_u, den_w = row_unw, row_w
        else:
            den_u, den_w = unw, wbase
        estimate = _percent(unum, den_u, wnum, den_w, use_weight)
        cells[column.id] = _cell(estimate, unw, wbase, unum, wnum, decimals, percent=True)
        cells[column.id].weighted_denominator = den_w if use_weight else wbase
    return ResultRow(code=code, label=label, row_kind=kind, cells=cells)  # type: ignore[arg-type]


def _eligible(series: pd.Series, missing: list[Any], rule: str) -> pd.Series:
    """Return rows that belong in the question base.

    Args:
        series: Question column.
        missing: User-missing codes.
        rule: Missingness rule.

    Returns:
        Boolean mask.
    """
    if rule == "include_missing":
        return pd.Series(True, index=series.index)
    return ~_missing_mask(series, missing)


def _missing_mask(series: pd.Series, missing: list[Any]) -> pd.Series:
    """Return rows that are empty or user-missing.

    Args:
        series: Column.
        missing: User-missing codes.

    Returns:
        Boolean mask.
    """
    base = series.isna()
    if missing:
        base = base | in_codes(series, missing)
    return base


def _bases(mask: pd.Series, weights: pd.Series) -> tuple[int, float]:
    """Return the unweighted base and the positive finite weighted base.

    Args:
        mask: Respondents in the base.
        weights: Weights.

    Returns:
        Unweighted count and weighted base. Zero weights stay in the unweighted count only.
    """
    unw = int(mask.sum())
    return unw, _positive_sum(mask, weights)


def _positive_sum(mask: pd.Series, weights: pd.Series) -> float:
    """Sum finite weights that are greater than zero.

    Args:
        mask: Rows to include.
        weights: Weights.

    Returns:
        Weighted sum.
    """
    sub = weights[mask]
    keep = sub.notna() & np.isfinite(sub.to_numpy(dtype=float, na_value=np.nan)) & (sub > 0)
    if not bool(keep.any()):
        return 0.0
    return float(sub[keep].sum())


def _percent(
    unum: int,
    uden: int,
    wnum: float,
    wden: float,
    use_weight: bool,
) -> float | None:
    """Return a percentage in the 0–100 range, or None when the base is empty.

    Args:
        unum: Unweighted numerator.
        uden: Unweighted denominator.
        wnum: Weighted numerator.
        wden: Weighted denominator.
        use_weight: Use the weighted ratio when true.

    Returns:
        Percentage.
    """
    if use_weight:
        if wden == 0:
            return None
        return 100.0 * wnum / wden
    if uden == 0:
        return None
    return 100.0 * unum / uden


def _cell(
    estimate: float | None,
    unw: int,
    wbase: float,
    unum: int | None,
    wnum: float | None,
    decimals: int,
    *,
    percent: bool,
) -> CellResult:
    """Assemble a cell.

    Args:
        estimate: Numeric estimate.
        unw: Unweighted base.
        wbase: Weighted base.
        unum: Unweighted numerator.
        wnum: Weighted numerator.
        decimals: Display decimals.
        percent: Format as a percentage when true.

    Returns:
        Cell result.
    """
    if estimate is None:
        display = "—"
    elif percent:
        display = f"{estimate:.{decimals}f}%"
    else:
        display = f"{estimate:.{decimals}f}"
    return CellResult(
        estimate=estimate,
        display_value=display,
        weighted_numerator=wnum,
        weighted_denominator=wbase,
        unweighted_numerator=unum,
        unweighted_base=unw,
        weighted_base=wbase,
        warnings=[],
    )


def _observed_codes(series: pd.Series, missing: list[Any]) -> list[Any]:
    """Return sorted non-missing observed codes.

    Args:
        series: Column.
        missing: Codes to skip.

    Returns:
        Codes.
    """
    values = [
        value
        for value in series.dropna().unique().tolist()
        if not in_codes(pd.Series([value]), missing).iloc[0]
    ]
    try:
        return sorted(values, key=lambda item: float(item))
    except (TypeError, ValueError):
        return sorted(values, key=str)
