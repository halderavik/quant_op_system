"""Column roles for fraud checks. Ids and weights stay out of the answer vector."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.engines.tabspec_banners import is_weight_name
from app.engines.tabspec_build import _is_admin

_DURATION = re.compile(
    r"\bloi\b|duration|elapsed|length of interview|interview_length|length_of_interview",
    re.I,
)
_AGE = re.compile(r"\bage\b", re.I)
_ATTENTION = re.compile(r"trap|attention|red herring|quality check", re.I)
_ID_NAMES = {"respondent_id", "respid", "uuid", "record", "id"}
_CODE = re.compile(r"[A-Z0-9][A-Z0-9 .\-]{0,9}")
_CODE_SHARE = 0.9
_SYSTEM_TEXT = re.compile(
    r"captured variable|hidden to store|hidden variable|participant identifier|panel id", re.I
)


@dataclass
class ColumnFact:
    """One variable prepared for the closed-end checks."""

    name: str
    label: str
    role: str
    missing: set[str]
    labels: dict[str, str]
    values: list[str | None]


def prepare_columns(frame: pd.DataFrame, variables: list[dict[str, Any]]) -> list[ColumnFact]:
    """Attach a role and cleaned values to each dictionary variable.

    Args:
        frame: Respondent rows.
        variables: SPSS dictionary.

    Returns:
        Column facts for variables that are present on the frame.
    """
    facts: list[ColumnFact] = []
    for item in variables:
        name = str(item.get("name") or "")
        if name not in frame.columns:
            continue
        label = str(item.get("label") or name)
        missing = {_token(code) for code in list(item.get("user_missing_values") or [])}
        labels = {
            _token(code): str(text) for code, text in dict(item.get("value_labels") or {}).items()
        }
        role = _role(name, label, bool(item.get("is_text")))
        values = [_cell(value, missing) for value in frame[name].tolist()]
        if role == "text" and _code_like(values):
            role = "coded"
        facts.append(ColumnFact(name, label, role, missing, labels, values))
    return facts


def respondent_ids(facts: list[ColumnFact], row_count: int) -> list[str]:
    """Return a display id for each row.

    Args:
        facts: Prepared columns.
        row_count: Number of respondent rows.

    Returns:
        Respondent ids. The row number is used when the id cell is blank.
    """
    column = next((item for item in facts if item.role == "id"), None)
    if column is None:
        return [str(index) for index in range(row_count)]
    return [value if value is not None else str(index) for index, value in enumerate(column.values)]


def column_weights(facts: list[ColumnFact]) -> list[float] | None:
    """Return the weight column as numbers.

    Args:
        facts: Prepared columns.

    Returns:
        Weights, or None when the file has no weight.
    """
    column = next((item for item in facts if item.role == "weight"), None)
    if column is None:
        return None
    weights: list[float] = []
    for value in column.values:
        if value is None:
            weights.append(0.0)
            continue
        try:
            weights.append(float(value))
        except ValueError:
            weights.append(0.0)
    return weights


def _role(name: str, label: str, is_text: bool) -> str:
    """Classify a column so ids and weights stay out of the duplicate vector.

    Args:
        name: Variable name.
        label: Variable label.
        is_text: Whether the dictionary marks the column as text.

    Returns:
        Role name.
    """
    blob = f"{name} {label}"
    # Reason: ids and captured panel fields are often strings. They are not open ends.
    if name.lower() in _ID_NAMES or "respondent id" in label.lower():
        return "id"
    if is_text:
        return "admin" if _is_admin(name) or _SYSTEM_TEXT.search(label) else "text"
    if is_weight_name(name) or "weight" in label.lower():
        return "weight"
    if _DURATION.search(blob):
        return "duration"
    if _AGE.search(blob):
        return "age"
    if _ATTENTION.search(blob):
        return "attention"
    if _is_admin(name):
        return "admin"
    return "closed"


def _code_like(values: list[str | None]) -> bool:
    """Return whether a text column stores codes, such as a ZIP, state, or region.

    Args:
        values: Cleaned cells.

    Returns:
        True when at least 90 percent of answered cells are short uppercase or numeric codes.
    """
    answered = [value for value in values if value]
    if not answered:
        return False
    codes = sum(bool(_CODE.fullmatch(value.strip())) for value in answered)
    return codes / len(answered) >= _CODE_SHARE


def _cell(value: Any, missing: set[str]) -> str | None:
    """Return a comparable token, or None when the cell is blank or user-missing.

    Args:
        value: Raw cell.
        missing: User-missing tokens.

    Returns:
        Token or None.
    """
    if _blank(value):
        return None
    token = _token(value)
    if token in missing:
        return None
    return token


def _blank(value: Any) -> bool:
    """Return whether a cell is empty.

    Args:
        value: Raw cell.

    Returns:
        True for None and NaN.
    """
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _token(value: Any) -> str:
    """Normalize a code so 5 and 5.0 compare equal.

    Args:
        value: Raw code.

    Returns:
        Text token.
    """
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int | np.integer):
        return str(int(value))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return text
