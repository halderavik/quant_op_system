"""Pairwise unpooled proportion tests. Weighted designs are not given invented p-values."""

from dataclasses import dataclass
from math import sqrt
from statistics import NormalDist

import numpy as np
import pandas as pd

from app.schemas.crosstab import CellResult


@dataclass
class ColumnCounts:
    """Unweighted counts for one banner column."""

    column_id: str
    letter: str
    count: int
    base: int
    estimate: float | None


def apply_pairwise_letters(
    cells_by_column: dict[str, CellResult],
    columns: list[ColumnCounts],
    *,
    alpha: float,
    secondary_alpha: float = 0.10,
    correction: str,
    minimum_base: int,
    weighted: bool,
) -> list[str]:
    """Fill significance letters or mark a column that is too small to test.

    Uppercase letters are significant at ``alpha``. Lowercase letters are significant
    at ``secondary_alpha`` and not at ``alpha``. Letters are separated by spaces.
    A column whose unweighted base is below ``minimum_base`` is marked ``.`` and
    is left out of the tests. Other columns are still tested.

    Args:
        cells_by_column: Mutable cells keyed by column id.
        columns: Category columns that participate in pairwise tests.
        alpha: Two-sided alpha for uppercase letters.
        secondary_alpha: Two-sided alpha for lowercase letters.
        correction: ``none`` or ``holm``. Holm applies to the uppercase test only.
        minimum_base: Smallest unweighted base that may be tested.
        weighted: When true, tests are refused.

    Returns:
        Warnings to show on the table.
    """
    warnings: list[str] = []
    if weighted:
        warnings.append(
            "Significance was not calculated. Weighted percentages are not a "
            "survey-design variance estimate, and no design effect was supplied."
        )
        for cell in cells_by_column.values():
            cell.test_status = "not_tested"
            cell.p_value_if_tested = None
            cell.test_method = None
            cell.significance_letters = ""
        return warnings
    for column in columns:
        cell = cells_by_column.get(column.column_id)
        if cell is None:
            continue
        if column.base < minimum_base or column.estimate is None:
            cell.significance_letters = "."
            cell.test_status = "not_tested"
            cell.test_method = None
            cell.p_value_if_tested = None
    eligible = [
        column
        for column in columns
        if column.base >= minimum_base and column.estimate is not None and column.letter
    ]
    if len(eligible) < 2:
        warnings.append(
            f"Significance was not calculated because fewer than two columns "
            f"have a base of at least {minimum_base}."
        )
        return warnings
    pairs: list[tuple[int, int, float]] = []
    for left in range(len(eligible)):
        for right in range(left + 1, len(eligible)):
            p_value = _two_proportion(eligible[left], eligible[right])
            if p_value is None:
                continue
            pairs.append((left, right, p_value))
    if not pairs:
        for column in eligible:
            cell = cells_by_column[column.column_id]
            cell.test_status = "not_tested"
        return warnings
    primary = _reject_flags([item[2] for item in pairs], alpha, correction)
    chosen: dict[str, dict[str, str]] = {column.column_id: {} for column in eligible}
    best: dict[str, float] = {}
    letter_order = {column.letter.upper(): index for index, column in enumerate(eligible)}
    for (left, right, p_value), keep in zip(pairs, primary, strict=True):
        first = eligible[left]
        second = eligible[right]
        for column in (first, second):
            cell = cells_by_column[column.column_id]
            cell.test_status = "tested"
            cell.test_method = "unpooled_two_proportion_z"
            previous = best.get(column.column_id)
            if previous is None or p_value < previous:
                best[column.column_id] = p_value
                cell.p_value_if_tested = p_value
        if first.estimate is None or second.estimate is None or first.estimate == second.estimate:
            continue
        higher = first if first.estimate > second.estimate else second
        lower = second if higher is first else first
        token = lower.letter.upper() if keep else lower.letter.lower()
        if keep or p_value <= secondary_alpha:
            _remember(chosen[higher.column_id], token)
    for column in eligible:
        cell = cells_by_column[column.column_id]
        tokens = sorted(
            chosen[column.column_id].values(),
            key=lambda item: letter_order.get(item.upper(), 99),
        )
        cell.significance_letters = " ".join(tokens)
    return warnings


def _remember(bucket: dict[str, str], token: str) -> None:
    """Keep the uppercase form when a letter is significant at both alphas.

    Args:
        bucket: Tokens keyed by the uppercase letter.
        token: Letter to store.
    """
    key = token.upper()
    current = bucket.get(key)
    if current is None or token.isupper():
        bucket[key] = token


def _two_proportion(left: ColumnCounts, right: ColumnCounts) -> float | None:
    """Return a two-sided p-value for an unpooled two-proportion z-test.

    The standard error is ``sqrt(p1(1-p1)/n1 + p2(1-p2)/n2)``.

    Args:
        left: First column count and base.
        right: Second column count and base.

    Returns:
        P-value, or None when a test is undefined.
    """
    if min(left.base, right.base) <= 0:
        return None
    if left.count > left.base or right.count > right.base:
        return None
    p1 = left.count / left.base
    p2 = right.count / right.base
    variance = p1 * (1 - p1) / left.base + p2 * (1 - p2) / right.base
    if variance <= 0:
        return 1.0 if p1 == p2 else None
    z_score = (p1 - p2) / sqrt(variance)
    p_value = 2 * (1 - NormalDist().cdf(abs(z_score)))
    if not np.isfinite(p_value):
        return None
    return float(min(1.0, max(0.0, p_value)))


def _reject_flags(p_values: list[float], alpha: float, correction: str) -> list[bool]:
    """Return which pairwise tests are significant at the primary alpha.

    Args:
        p_values: Raw two-sided p-values.
        alpha: Family-wise or per-test alpha.
        correction: ``holm`` or ``none``.

    Returns:
        Boolean flags aligned with ``p_values``.
    """
    if correction != "holm":
        return [p_value <= alpha for p_value in p_values]
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    rejected = [False] * len(p_values)
    for rank, index in enumerate(order):
        threshold = alpha / (len(p_values) - rank)
        if p_values[index] <= threshold:
            rejected[index] = True
        else:
            break
    return rejected


def weights_vary(weights: pd.Series, mask: pd.Series) -> bool:
    """Return whether eligible weights are not all identically one.

    Args:
        weights: Weight column.
        mask: Eligible rows.

    Returns:
        True when any eligible finite weight is not 1.
    """
    sub = weights[mask]
    finite = sub[np.isfinite(sub.to_numpy(dtype=float, na_value=np.nan))]
    if finite.empty:
        return False
    return bool((np.abs(finite.to_numpy(dtype=float) - 1.0) > 1e-9).any())
