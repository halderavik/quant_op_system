"""Charts drawn from computed table cells."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.schemas.crosstab import TableResult


def bar_from_table(result: TableResult, destination: Path, column_id: str = "total") -> Path:
    """Write a bar chart of category estimates for one column.

    Args:
        result: Computed table.
        destination: PNG path.
        column_id: Column to plot.

    Returns:
        The path written.
    """
    labels = []
    values = []
    for row in result.rows:
        if row.row_kind != "category":
            continue
        cell = row.cells.get(column_id)
        if cell is None or cell.estimate is None:
            continue
        labels.append(row.label)
        values.append(cell.estimate)
    figure, axis = plt.subplots(figsize=(7, 4))
    axis.bar(labels, values, color="#1f4b4a")
    axis.set_ylabel("Percent" if result.percent_type else "Estimate")
    axis.set_title(result.title)
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination)
    plt.close(figure)
    return destination
