"""SPSS metadata and data loading. Original codes are preserved."""

from pathlib import Path
from typing import Any

import pandas as pd
import pyreadstat

from app.errors import AppError


def read_spss(path: Path) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
    """Read a ``.sav`` or ``.zsav`` file.

    Args:
        path: File on disk.

    Returns:
        Data frame, variable dictionary, and weight-variable candidates.

    Raises:
        AppError: When the file cannot be decoded.
    """
    try:
        # Reason: user_missing=True keeps 98/99 in the data and reports them as missing codes.
        frame, meta = pyreadstat.read_sav(str(path), user_missing=True)
    except Exception as exc:
        raise AppError(
            "This SPSS file could not be read. Check that it is a valid .sav or .zsav export.",
            "bad_spss",
        ) from exc
    labels = list(getattr(meta, "column_labels", []) or [])
    value_labels = dict(getattr(meta, "variable_value_labels", {}) or {})
    measures = dict(getattr(meta, "variable_measure", {}) or {})
    ranges = dict(getattr(meta, "missing_ranges", {}) or {})
    discrete = dict(getattr(meta, "missing_user_values", {}) or {})
    storage = dict(getattr(meta, "readstat_variable_types", {}) or {})
    variables: list[dict[str, Any]] = []
    for index, name in enumerate(frame.columns):
        label = labels[index] if index < len(labels) and labels[index] else name
        kind = "text" if is_text_column(frame[name], storage.get(name)) else "numeric"
        variables.append(
            {
                "name": str(name),
                "label": str(label),
                "kind": kind,
                "measurement": str(
                    measures.get(name) or ("nominal" if kind == "text" else "scale")
                ),
                "value_labels": {
                    str(key): str(value) for key, value in dict(value_labels.get(name, {})).items()
                },
                "user_missing_values": _missing_codes(name, ranges, discrete),
                "is_text": kind == "text",
            }
        )
    weights = [
        item["name"]
        for item in variables
        if "weight" in item["name"].lower() or "weight" in item["label"].lower()
    ]
    return frame, variables, weights


def is_text_column(series: pd.Series, storage: str | None = None) -> bool:
    """Return whether an SPSS column holds strings.

    Args:
        series: Column as read by pyreadstat.
        storage: pyreadstat storage type for the column, when known.

    Returns:
        True for a string variable.
    """
    if storage:
        return storage == "string"
    # Reason: pandas 3 reads strings as the ``str`` dtype, not ``object``.
    return series.dtype == object or isinstance(series.dtype, pd.StringDtype)


def _missing_codes(
    name: str,
    ranges: dict[str, Any],
    discrete: dict[str, Any],
) -> list[Any]:
    """Collect user-missing codes declared for one variable.

    Args:
        name: Variable name.
        ranges: pyreadstat missing ranges.
        discrete: pyreadstat discrete missing values, when present.

    Returns:
        Missing codes. Inclusive integer ranges are expanded.
    """
    found: list[Any] = []
    for item in list(discrete.get(name) or []):
        found.append(item)
    for item in list(ranges.get(name) or []):
        if isinstance(item, dict) and "lo" in item and "hi" in item:
            lo = item["lo"]
            hi = item["hi"]
            try:
                start = int(lo)
                stop = int(hi)
            except (TypeError, ValueError):
                found.extend([lo, hi])
                continue
            if 0 <= stop - start <= 20:
                found.extend(list(range(start, stop + 1)))
            else:
                found.extend([lo, hi])
        else:
            found.append(item)
    unique: list[Any] = []
    for code in found:
        if code not in unique:
            unique.append(code)
    return unique
