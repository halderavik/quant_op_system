"""Chart specs for analysis results.

A spec holds aggregate numbers only (never respondent rows), so it can travel
in result.json out of the sandbox. ``app.engines.chart_render`` draws each
spec as a PNG. Built-in methods get the standard research charts here;
AI-written methods may return their own specs in ``charts``.
"""

import math
from typing import Any

from app.schemas.analysis import AnalysisResult, AnalysisStep

KINDS = {"bar", "barh", "line", "heatmap", "stacked_bar"}
_MAX_CHARTS = 24
_MAX_SERIES = 12
_MAX_POINTS = 400
_MAX_BARS = 40
_Z = 1.96
_METHOD_TITLES = {
    "key_driver": "Driver importance",
    "linear_regression": "Regression coefficients",
    "binary_logistic_regression": "Logistic coefficients",
}


def method_charts(
    method: str, step: AnalysisStep, group: str, result: AnalysisResult, labels: dict[str, dict]
) -> list[dict[str, Any]]:
    """Standard charts for one method fit.

    Args:
        method: Canonical method name.
        step: The method step.
        group: Subgroup label for a split run, or empty.
        result: The fit's own result, before multi-fit prefixes.
        labels: Value labels by variable name, for category axes.

    Returns:
        Chart specs. Empty when the method has no standard chart.
    """
    suffix = f" — {group}" if group else ""
    charts: list[dict[str, Any]] = []
    estimates = result.model_estimates or {}
    descriptive = result.descriptive or {}
    metrics = result.metrics or {}
    if method == "key_driver":
        ranking = descriptive.get("importance_ranking") or []
        if ranking:
            charts.append(
                _bars(
                    f"Driver importance{suffix}",
                    [str(row["driver"]) for row in ranking],
                    [row["importance_pct"] for row in ranking],
                    "barh",
                    x_label="Share of explained variance (%)",
                    note=f"Johnson's relative weights. R² = {metrics.get('r_squared', 0):.3f}",
                )
            )
    elif method in {"linear_regression", "binary_logistic_regression", "ordinal_regression"}:
        terms = [
            (name, value)
            for name, value in estimates.items()
            if name != "const" and isinstance(value, dict) and "coefficient" in value
        ][:_MAX_BARS]
        if terms:
            errors = [_Z * float(value.get("std_error") or 0) for _, value in terms]
            charts.append(
                _bars(
                    f"Coefficients with 95% intervals{suffix}",
                    [name for name, _ in terms],
                    [value["coefficient"] for _, value in terms],
                    "barh",
                    errors=errors,
                    x_label="Coefficient" + (" (log-odds)" if "logistic" in method else ""),
                    zero_line=True,
                )
            )
    elif method in {"t_test", "anova"}:
        groups = descriptive.get("groups") or {}
        if groups:
            names = list(groups)
            charts.append(
                _bars(
                    f"Mean {step.dependent} by {step.group}{suffix}",
                    [_label(labels, step.group, name) for name in names],
                    [groups[name]["mean"] for name in names],
                    "bar",
                    errors=[_ci(groups[name]) for name in names],
                    y_label=f"Mean {step.dependent} (95% interval)",
                    note=f"p = {metrics.get('p_value', float('nan')):.3f}",
                )
            )
    elif method == "chi_square":
        table = descriptive.get("table") or {}
        if table:
            charts.append(_stacked(table, step, labels, suffix))
    elif method == "correlation":
        matrix = metrics.get("correlation") or {}
        names = list(matrix)[:_MAX_BARS]
        if len(names) > 1:
            charts.append(
                _heatmap(
                    f"Correlation matrix{suffix}",
                    names,
                    names,
                    [[matrix[row].get(col) for col in names] for row in names],
                    centre=0.0,
                )
            )
    elif method == "descriptive":
        names = [
            name
            for name, value in descriptive.items()
            if isinstance(value, dict) and "mean" in value
        ]
        if names:
            charts.append(
                _bars(
                    f"Means with 95% intervals{suffix}",
                    names[:_MAX_BARS],
                    [descriptive[name]["mean"] for name in names[:_MAX_BARS]],
                    "bar",
                    errors=[_ci(descriptive[name]) for name in names[:_MAX_BARS]],
                    y_label="Mean",
                )
            )
    elif method in {"efa", "pca"}:
        charts.extend(_factor_charts(method, estimates, metrics, suffix))
    elif "sizes" in estimates:
        charts.extend(_segment_charts(estimates, suffix))
    return charts


def workflow_charts(
    chosen: dict[str, Any],
    profile_tables: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Charts that span steps: the segment count search, profiles, and group comparisons."""
    charts: list[dict[str, Any]] = []
    scores = chosen.get("silhouette_by_k") or {}
    if len(scores) > 1:
        ks = sorted(scores, key=int)
        charts.append(
            {
                "kind": "line",
                "title": "Segment count search",
                "x_label": "Number of segments (k)",
                "y_label": "Silhouette",
                "series": [
                    {"name": "Silhouette", "x": [int(k) for k in ks], "y": [scores[k] for k in ks]}
                ],
                "markers": [
                    {"x": int(chosen.get("k") or 0), "label": f"Chosen k={chosen.get('k')}"}
                ],
            }
        )
    for table in profile_tables[:8]:
        columns = [name for name in table.get("columns") or [] if name != "Total"]
        rows = [row for row in table.get("rows") or [] if row.get("kind") == "category"][:_MAX_BARS]
        if not columns or not rows:
            continue
        charts.append(
            _heatmap(
                f"Profile: {table.get('variable')} by segment (column %)",
                [str(row.get("label")) for row in rows],
                columns,
                [[(row.get("values") or {}).get(col) for col in columns] for row in rows],
            )
        )
    for block in comparisons:
        groups = list(block.get("groups") or [])[:_MAX_SERIES]
        field = "importance_pct" if block.get("method") == "key_driver" else "coefficient"
        rows = [row for row in block.get("rows") or [] if row.get("field") == field][:_MAX_BARS]
        if not rows or len(groups) < 2:
            continue
        charts.append(
            {
                "kind": "barh",
                "title": (
                    f"{_METHOD_TITLES.get(block.get('method'), str(block.get('method')).replace('_', ' ').capitalize())}"
                    f" by {block.get('split_by')}"
                ),
                "x_label": "Share of explained variance (%)"
                if field == "importance_pct"
                else field,
                "categories": [str(row.get("term")) for row in rows],
                "series": [
                    {
                        "name": group,
                        "values": [(row.get("values") or {}).get(group) for row in rows],
                    }
                    for group in groups
                ],
            }
        )
    return charts


def clean_specs(specs: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep only well-formed, numeric, size-limited specs.

    AI-written scripts may return specs; anything malformed is dropped with a note.

    Returns:
        Kept specs and notes about what was dropped.
    """
    kept: list[dict[str, Any]] = []
    notes: list[str] = []
    for index, spec in enumerate(specs if isinstance(specs, list) else []):
        try:
            kept.append(_clean(spec))
        except (AttributeError, TypeError, ValueError, KeyError) as error:
            notes.append(f"Chart {index + 1} was skipped: {error}")
        if len(kept) >= _MAX_CHARTS:
            break
    return kept, notes


def _clean(spec: dict[str, Any]) -> dict[str, Any]:
    kind = str(spec.get("kind") or "")
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    out: dict[str, Any] = {
        "kind": kind,
        "title": _text(spec.get("title")) or "Chart",
        "x_label": _text(spec.get("x_label")),
        "y_label": _text(spec.get("y_label")),
        "note": _text(spec.get("note")),
    }
    if kind == "heatmap":
        rows = [_text(item) for item in spec["rows"]][:_MAX_BARS]
        columns = [_text(item) for item in spec["columns"]][:_MAX_BARS]
        matrix = [
            [_number(value) for value in row[: len(columns)]] for row in spec["matrix"][: len(rows)]
        ]
        if not rows or not columns:
            raise ValueError("empty heatmap")
        out.update(rows=rows, columns=columns, matrix=matrix, centre=_number(spec.get("centre")))
        return out
    series = []
    for item in list(spec["series"])[:_MAX_SERIES]:
        entry = {"name": _text(item.get("name"))}
        if kind == "line":
            xs = [_number(value) for value in item["x"]][:_MAX_POINTS]
            ys = [_number(value) for value in item["y"]][: len(xs)]
            if len(xs) != len(ys) or not xs:
                raise ValueError("line series needs equal x and y")
            entry.update(x=xs, y=ys)
        else:
            entry["values"] = [_number(value) for value in item["values"]][:_MAX_BARS]
            if item.get("errors"):
                entry["errors"] = [_number(value) for value in item["errors"]][:_MAX_BARS]
        series.append(entry)
    if not series:
        raise ValueError("no series")
    if kind != "line":
        out["categories"] = [_text(item) for item in spec["categories"]][:_MAX_BARS]
    out["series"] = series
    out["markers"] = [
        {"x": _number(item.get("x")), "label": _text(item.get("label"))}
        for item in list(spec.get("markers") or [])[:8]
        if _number(item.get("x")) is not None
    ]
    out["zero_line"] = bool(spec.get("zero_line"))
    return out


def _bars(
    title: str,
    categories: list[str],
    values: list[float],
    kind: str,
    *,
    errors: list[float] | None = None,
    x_label: str = "",
    y_label: str = "",
    note: str = "",
    zero_line: bool = False,
) -> dict[str, Any]:
    series: dict[str, Any] = {"name": "", "values": values}
    if errors:
        series["errors"] = errors
    return {
        "kind": kind,
        "title": title,
        "categories": categories,
        "series": [series],
        "x_label": x_label,
        "y_label": y_label,
        "note": note,
        "zero_line": zero_line,
    }


def _heatmap(
    title: str,
    rows: list[str],
    columns: list[str],
    matrix: list[list[Any]],
    centre: float | None = None,
) -> dict[str, Any]:
    return {
        "kind": "heatmap",
        "title": title,
        "rows": rows,
        "columns": columns,
        "matrix": matrix,
        "centre": centre,
    }


def _stacked(
    table: dict[str, dict[str, Any]], step: AnalysisStep, labels: dict[str, dict], suffix: str
) -> dict[str, Any]:
    """Row-percent stacked bars: one bar per var_a category, stacked by var_b."""
    stacks = list(table)[:_MAX_SERIES]
    bars = list(dict.fromkeys(key for column in table.values() for key in column))[:_MAX_BARS]
    totals = {bar: sum(float(table[stack].get(bar) or 0) for stack in table) for bar in bars}
    return {
        "kind": "stacked_bar",
        "title": f"{step.var_b} within {step.var_a} (row %){suffix}",
        "categories": [_label(labels, step.var_a, bar) for bar in bars],
        "series": [
            {
                "name": _label(labels, step.var_b, stack),
                "values": [
                    100.0 * float(table[stack].get(bar) or 0) / totals[bar] if totals[bar] else 0.0
                    for bar in bars
                ],
            }
            for stack in stacks
        ],
        "y_label": "Percent",
    }


def _factor_charts(
    method: str, estimates: dict[str, Any], metrics: dict[str, Any], suffix: str
) -> list[dict[str, Any]]:
    """Variance explained and the loading matrix."""
    charts: list[dict[str, Any]] = []
    share = metrics.get("explained_variance_ratio") or metrics.get("variance_explained") or []
    name = "Factor" if method == "efa" else "Component"
    if share:
        charts.append(
            _bars(
                f"Variance explained by {name.lower()}{suffix}",
                [f"{name} {index + 1}" for index in range(len(share))],
                [100.0 * float(value) for value in share],
                "bar",
                y_label="Percent of item variance",
            )
        )
    if method == "efa":
        items = [key for key, value in estimates.items() if isinstance(value, dict)][:_MAX_BARS]
        factors = sorted(
            {key for key in (estimates.get(items[0]) or {}) if key.startswith("factor_")}
            if items
            else set()
        )
        if items and factors:
            charts.append(
                _heatmap(
                    f"Rotated loadings{suffix}",
                    items,
                    [factor.replace("factor_", "Factor ") for factor in factors],
                    [[estimates[item].get(factor) for factor in factors] for item in items],
                    centre=0.0,
                )
            )
    else:
        components = [key for key in estimates if key.startswith("PC")]
        items = list((estimates.get(components[0]) or {}).keys())[:_MAX_BARS] if components else []
        if items:
            charts.append(
                _heatmap(
                    f"Component loadings{suffix}",
                    items,
                    components,
                    [[estimates[comp].get(item) for comp in components] for item in items],
                    centre=0.0,
                )
            )
    return charts


def _segment_charts(estimates: dict[str, Any], suffix: str) -> list[dict[str, Any]]:
    """Segment sizes and feature means by segment."""
    sizes = estimates.get("sizes") or {}
    charts: list[dict[str, Any]] = []
    if isinstance(sizes, dict) and sizes:
        names = sorted(sizes, key=lambda key: str(key))
        total = sum(float(sizes[key]) for key in names) or 1.0
        charts.append(
            _bars(
                f"Segment sizes{suffix}",
                [f"Segment {key}" for key in names],
                [100.0 * float(sizes[key]) / total for key in names],
                "bar",
                y_label="Percent of respondents",
            )
        )
    profiles = estimates.get("profiles") or {}
    if isinstance(profiles, dict) and profiles:
        segments = sorted(profiles, key=lambda key: str(key))
        features = list((profiles[segments[0]] or {}).keys())[:_MAX_BARS]
        if features:
            charts.append(
                _heatmap(
                    f"Segment feature means{suffix}",
                    features,
                    [f"Segment {key}" for key in segments],
                    [
                        [(profiles[seg] or {}).get(feature) for seg in segments]
                        for feature in features
                    ],
                )
            )
    return charts


def _ci(info: dict[str, Any]) -> float:
    n = float(info.get("n") or 0)
    std = float(info.get("std") or 0)
    return _Z * std / math.sqrt(n) if n > 1 else 0.0


def _label(labels: dict[str, dict], variable: str, code: Any) -> str:
    text = str(code)
    key = text[:-2] if text.endswith(".0") else text
    found = (labels.get(variable) or {}).get(key)
    return str(found) if found else key


def _text(value: Any) -> str:
    return str(value or "")[:160]


def _number(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def table_chart(result: Any) -> dict[str, Any] | None:
    """One chart for a computed crosstab: category or mean rows across banner columns.

    Args:
        result: ``TableResult``.

    Returns:
        Spec, or None when the table has nothing to plot.
    """
    rows = [row for row in result.rows if row.row_kind in {"category", "top_box", "bottom_box"}]
    kind_label = "Percent" if result.percent_type else "Estimate"
    if not rows:
        rows = [row for row in result.rows if row.row_kind == "mean"]
        kind_label = "Mean"
    rows = rows[:_MAX_BARS]
    columns = result.columns[:8]
    if not rows or not columns:
        return None
    series = [
        {
            "name": column.label,
            "values": [
                (row.cells.get(column.id).estimate if row.cells.get(column.id) else None)
                for row in rows
            ],
        }
        for column in columns
    ]
    return {
        "kind": "barh" if len(rows) > 6 or len(columns) > 3 else "bar",
        "title": result.title,
        "categories": [str(row.label) for row in rows],
        "series": series,
        "x_label": kind_label if len(rows) > 6 or len(columns) > 3 else "",
        "y_label": "" if len(rows) > 6 or len(columns) > 3 else kind_label,
        "note": f"Weighted by {result.weight_variable}" if result.weight_variable else "",
    }


def coding_charts(report: Any, codeframe: Any) -> list[dict[str, Any]]:
    """Net and code frequency charts for a coded open end.

    Args:
        report: ``CodingReport``.
        codeframe: ``Codeframe``.

    Returns:
        Specs for nets and for the most frequent codes.
    """
    variable = codeframe.response_variable
    base = f"Base: {report.substantive_n} answers"
    charts = []
    for kind, title, limit in (
        ("net", f"{variable}: nets", 20),
        ("code", f"{variable}: top codes", 25),
    ):
        items = sorted(
            (
                item
                for item in report.frequencies
                if item.kind == kind and item.pct_of_respondents is not None
            ),
            key=lambda item: -(item.pct_of_respondents or 0),
        )[:limit]
        if items:
            charts.append(
                _bars(
                    title,
                    [item.label for item in items],
                    [item.pct_of_respondents for item in items],
                    "barh",
                    x_label="Percent of respondents",
                    note=base,
                )
            )
    return charts
