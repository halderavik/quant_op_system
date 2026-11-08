"""Evaluate whitelist expressions against a row or an answer map."""

from typing import Any

import pandas as pd

from app.errors import AppError
from app.schemas.expression import BoolExpr, Comparison, Expr


def evaluate(expr: Expr | None, values: dict[str, Any], allowed: set[str] | None = None) -> bool:
    """Evaluate an expression. Missing expressions are true.

    Args:
        expr: Comparison or boolean tree.
        values: Variable or question values.
        allowed: If set, every reference must be in this set.

    Returns:
        Boolean result.
    """
    if expr is None:
        return True
    if isinstance(expr, Comparison):
        _check_ref(expr.ref, allowed)
        return _compare(expr, values.get(expr.ref))
    if isinstance(expr, BoolExpr):
        results = [evaluate(item, values, allowed) for item in expr.args]
        if expr.op == "and":
            return all(results)
        if expr.op == "or":
            return any(results)
        if expr.op == "not":
            return not results[0] if results else True
    raise AppError("Unsupported expression", "bad_expression")


def mask_frame(expr: Expr | None, frame: pd.DataFrame) -> pd.Series:
    """Return a boolean mask for each row of a dataframe.

    Args:
        expr: Filter expression, or None for all rows.
        frame: Respondent-level data.

    Returns:
        Boolean series aligned to ``frame``.
    """
    if expr is None:
        return pd.Series(True, index=frame.index)
    allowed = set(frame.columns)
    flags = [
        evaluate(expr, {col: row[col] for col in frame.columns}, allowed)
        for _, row in frame.iterrows()
    ]
    return pd.Series(flags, index=frame.index)


def _check_ref(ref: str, allowed: set[str] | None) -> None:
    """Reject references that are not in the allowlist.

    Args:
        ref: Identifier from the expression.
        allowed: Permitted names, or None to skip the membership check.
    """
    if allowed is not None and ref not in allowed:
        raise AppError(f"Unknown variable or question '{ref}'", "unknown_reference")


def _compare(expr: Comparison, current: Any) -> bool:
    """Compare one value using the expression operator.

    Args:
        expr: Comparison node.
        current: Observed value.

    Returns:
        Whether the comparison holds.
    """
    missing = (
        current is None or (isinstance(current, float) and pd.isna(current)) or pd.isna(current)
    )
    if expr.op == "answered":
        return not missing
    if expr.op == "not_answered":
        return bool(missing)
    if missing:
        return False
    if expr.op == "eq":
        return current == expr.value or str(current) == str(expr.value)
    if expr.op == "ne":
        return not (current == expr.value or str(current) == str(expr.value))
    if expr.op == "in":
        return current in (expr.value or []) or str(current) in {
            str(item) for item in (expr.value or [])
        }
    if expr.op == "not_in":
        return current not in (expr.value or []) and str(current) not in {
            str(item) for item in (expr.value or [])
        }
    try:
        left = float(current)
        right = float(expr.value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"Cannot compare '{expr.ref}' numerically", "bad_expression") from exc
    if expr.op == "gt":
        return left > right
    if expr.op == "gte":
        return left >= right
    if expr.op == "lt":
        return left < right
    if expr.op == "lte":
        return left <= right
    raise AppError(f"Unsupported operator {expr.op}", "bad_expression")
