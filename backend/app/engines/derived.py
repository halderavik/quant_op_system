"""Whitelist derived variables. Parameters are data, not executable code."""

import json
from typing import Any

import pandas as pd

from app.errors import AppError
from app.schemas.tabspec import DerivedVariable

_FORBIDDEN = ("__", "import", "eval", "exec", "os.", "sys.", "open(")


def apply_derived(frame: pd.DataFrame, derived: list[DerivedVariable]) -> pd.DataFrame:
    """Return a copy of ``frame`` with derived columns appended.

    Args:
        frame: Source respondent data.
        derived: Whitelist recipes.

    Returns:
        Copy including the new columns.
    """
    out = frame.copy()
    for item in derived:
        blob = json.dumps(item.params, default=str)
        if any(token in blob for token in _FORBIDDEN):
            raise AppError(
                f"Derived variable '{item.name}' contains disallowed content",
                "bad_expression",
            )
        if item.source not in out.columns:
            raise AppError(
                f"Derived variable '{item.name}' refers to missing source '{item.source}'",
                "missing_variable",
            )
        out[item.name] = _compute(out[item.source], item)
    return out


def _compute(source: pd.Series, item: DerivedVariable) -> pd.Series:
    """Compute one derived series.

    Args:
        source: Source column.
        item: Recipe and parameters.

    Returns:
        New series aligned to ``source``.
    """
    if item.recipe == "reverse":
        low = float(item.params["low"])
        high = float(item.params["high"])
        return low + high - pd.to_numeric(source, errors="coerce")
    if item.recipe == "recode":
        mapping = {str(key): value for key, value in dict(item.params.get("map", {})).items()}
        return source.map(lambda value: mapping.get(str(value), value))
    if item.recipe == "band":
        bins = list(item.params.get("bins", []))
        return source.map(lambda value: _band(value, bins))
    if item.recipe in {"top_box", "net_flag"}:
        codes = list(item.params.get("codes", []))
        return in_codes(source, codes).astype(int)
    raise AppError(f"Unsupported derived recipe '{item.recipe}'", "bad_expression")


def _band(value: Any, bins: list[dict[str, Any]]) -> Any:
    """Assign a numeric value to the first matching band.

    Args:
        value: Source value.
        bins: Dicts with ``label``, ``lo``, and ``hi``.

    Returns:
        Band label, or None when no band matches.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    for band in bins:
        if float(band["lo"]) <= number <= float(band["hi"]):
            return band["label"]
    return None


def in_codes(series: pd.Series, codes: list[Any]) -> pd.Series:
    """Return whether each value is in ``codes``, comparing numbers and text.

    Args:
        series: Column to test.
        codes: Accepted codes.

    Returns:
        Boolean series.
    """
    wanted_text = {str(code) for code in codes}
    wanted_num: set[float] = set()
    for code in codes:
        try:
            wanted_num.add(float(code))
        except (TypeError, ValueError):
            continue

    def _match(value: Any) -> bool:
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            return False
        if str(value) in wanted_text:
            return True
        try:
            return float(value) in wanted_num
        except (TypeError, ValueError):
            return False

    return series.map(_match)
