"""Draw chart specs as PNG files with matplotlib. Specs carry aggregates only."""

import re
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_PALETTE = [
    "#1f4b4a",
    "#d97a2b",
    "#4f7cac",
    "#9c5b8f",
    "#6a994e",
    "#c44536",
    "#7f7f7f",
    "#e0b04a",
    "#2a9d8f",
    "#8d6e63",
    "#5e60ce",
    "#b5838d",
]


def render(spec: dict[str, Any], destination: Path) -> Path:
    """Write one chart spec to a PNG.

    Args:
        spec: Cleaned spec from ``plots.clean_specs`` or a built-in builder.
        destination: PNG path.

    Returns:
        The path written.
    """
    kind = spec["kind"]
    if kind == "heatmap":
        figure = _heatmap(spec)
    elif kind == "line":
        figure = _line(spec)
    else:
        figure = _bars(spec)
    if spec.get("note"):
        # Reason: below the axes, wrapped, so it never covers the axis label.
        note = "\n".join(textwrap.wrap(spec["note"], 120))
        figure.text(0.01, -0.01, note, fontsize=8, color="#555555", ha="left", va="top")
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return destination


def file_name(index: int, title: str) -> str:
    """A safe, ordered PNG name for a chart title."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:60] or "chart"
    return f"{index:02d}_{slug}.png"


def _bars(spec: dict[str, Any]) -> plt.Figure:
    categories = spec.get("categories") or []
    series = spec["series"]
    horizontal = spec["kind"] == "barh"
    stacked = spec["kind"] == "stacked_bar"
    count = max(len(categories), 1)
    size = (
        (8, max(3.0, 0.35 * count * (len(series) if not stacked else 1) + 1.2))
        if horizontal
        else (max(6.0, 0.6 * count + 2), 4.5)
    )
    figure, axis = plt.subplots(figsize=size)
    positions = np.arange(len(categories))
    width = 0.8 / (1 if stacked else len(series))
    bottom = np.zeros(len(categories))
    for index, item in enumerate(series):
        values = np.array(
            [np.nan if value is None else value for value in item["values"]], dtype=float
        )
        values = np.resize(values, len(categories)) if len(values) != len(categories) else values
        errors = item.get("errors")
        offset = 0 if stacked else (index - (len(series) - 1) / 2) * width
        colour = _PALETTE[index % len(_PALETTE)]
        common = {"color": colour, "label": item.get("name") or None}
        if horizontal:
            bars = axis.barh(
                positions + offset, values, height=width, xerr=_errors(errors), capsize=3, **common
            )
        else:
            bars = axis.bar(
                positions + offset,
                values,
                width=width,
                bottom=bottom if stacked else None,
                yerr=_errors(errors),
                capsize=3,
                **common,
            )
        if len(series) == 1 and not stacked and len(categories) <= 25:
            axis.bar_label(bars, fmt="%.1f", fontsize=8, padding=2)
        if stacked:
            for bar, value, base in zip(bars, values, bottom, strict=False):
                if value >= 6:
                    axis.text(
                        bar.get_x() + bar.get_width() / 2,
                        base + value / 2,
                        f"{value:.0f}%",
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="white",
                    )
            bottom = bottom + np.nan_to_num(values)
    if horizontal:
        axis.set_yticks(positions, categories)
        axis.invert_yaxis()
        if spec.get("zero_line"):
            axis.axvline(0, color="#333333", linewidth=0.8)
    else:
        axis.set_xticks(
            positions,
            categories,
            rotation=30 if count > 6 else 0,
            ha="right" if count > 6 else "center",
        )
        if spec.get("zero_line"):
            axis.axhline(0, color="#333333", linewidth=0.8)
    _finish(axis, spec, legend=len(series) > 1)
    return figure


def _line(spec: dict[str, Any]) -> plt.Figure:
    figure, axis = plt.subplots(figsize=(8, 4.5))
    for index, item in enumerate(spec["series"]):
        axis.plot(
            item["x"],
            item["y"],
            marker="o" if len(item["x"]) <= 30 else None,
            color=_PALETTE[index % len(_PALETTE)],
            label=item.get("name") or None,
        )
    for marker in spec.get("markers") or []:
        axis.axvline(marker["x"], color="#999999", linestyle="--", linewidth=1)
        axis.annotate(
            marker["label"],
            (marker["x"], axis.get_ylim()[1]),
            rotation=90,
            va="top",
            ha="right",
            fontsize=8,
            color="#444444",
        )
    _finish(axis, spec, legend=len(spec["series"]) > 1)
    return figure


def _heatmap(spec: dict[str, Any]) -> plt.Figure:
    rows, columns = spec["rows"], spec["columns"]
    matrix = np.array(
        [[np.nan if value is None else value for value in row] for row in spec["matrix"]],
        dtype=float,
    )
    figure, axis = plt.subplots(
        figsize=(max(5.0, 0.9 * len(columns) + 3), max(3.0, 0.4 * len(rows) + 1.5))
    )
    centre = spec.get("centre")
    if centre is not None:
        limit = np.nanmax(np.abs(matrix - centre)) or 1.0
        image = axis.imshow(
            matrix, cmap="RdBu_r", vmin=centre - limit, vmax=centre + limit, aspect="auto"
        )
    else:
        image = axis.imshow(matrix, cmap="YlGnBu", aspect="auto")
    axis.set_xticks(
        range(len(columns)),
        columns,
        rotation=30 if len(columns) > 5 else 0,
        ha="right" if len(columns) > 5 else "center",
    )
    axis.set_yticks(range(len(rows)), rows)
    if len(rows) * len(columns) <= 300:
        for i in range(len(rows)):
            for j in range(len(columns)):
                if not np.isnan(matrix[i, j]):
                    axis.text(
                        j,
                        i,
                        f"{matrix[i, j]:.2f}" if abs(matrix[i, j]) < 10 else f"{matrix[i, j]:.0f}",
                        ha="center",
                        va="center",
                        fontsize=7,
                    )
    figure.colorbar(image, ax=axis, fraction=0.04)
    axis.set_title(spec["title"], fontsize=11, loc="left")
    return figure


def _errors(errors: list[Any] | None) -> Any:
    if not errors:
        return None
    return np.array([0 if value is None else value for value in errors], dtype=float)


def _finish(axis: Any, spec: dict[str, Any], *, legend: bool) -> None:
    axis.set_title(spec["title"], fontsize=11, loc="left")
    if spec.get("x_label"):
        axis.set_xlabel(spec["x_label"])
    if spec.get("y_label"):
        axis.set_ylabel(spec["y_label"])
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="both", alpha=0.25)
    axis.set_axisbelow(True)
    if legend:
        axis.legend(fontsize=8, frameon=False, loc="best")
