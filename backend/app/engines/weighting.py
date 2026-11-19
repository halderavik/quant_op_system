"""Rim weighting (raking) to target shares, with caps and an efficiency report.

Raking adjusts each respondent's weight one dimension at a time until every dimension's
weighted shares match its targets. Weights are kept between a floor and a ceiling
relative to a mean of 1, so no respondent counts for too much.
"""

from typing import Any

import numpy as np
import pandas as pd

from app.engines.derived import in_codes
from app.schemas.weighting import (
    AchievedShare,
    TargetCategory,
    WeightingDimension,
    WeightingSettings,
)

# A dimension's targets may be entered as whole percentages that round to 99.9 or 100.1.
SUM_TOLERANCE = 0.5
# Reason: a weighted share within 0.05 points of its target is met for reporting.
MET = 0.0005


def _code(raw: Any) -> int | float:
    """Turn a value-label key such as ``"2.0"`` into 2."""
    number = float(raw)
    return int(number) if number.is_integer() else number


def categories_from_labels(variable: dict[str, Any]) -> list[TargetCategory]:
    """One category per labelled answer code, leaving out user-missing codes.

    Args:
        variable: Dataset variable entry with ``value_labels`` and ``user_missing_values``.

    Returns:
        Categories without shares.
    """
    missing = {float(code) for code in variable.get("user_missing_values") or []}
    found: list[TargetCategory] = []
    for raw, label in (variable.get("value_labels") or {}).items():
        try:
            code = _code(raw)
        except (TypeError, ValueError):
            continue
        if float(code) in missing:
            continue
        found.append(TargetCategory(label=str(label), codes=[code], origin="sample"))
    return found


# Reason: the five- and ten-year bands statistics offices publish, so census figures match.
AGE_CUTS = (18, 25, 35, 45, 55, 65)


def age_bands(series: pd.Series) -> list[TargetCategory]:
    """Bands for a typed-in age, such as 18-24 ... 65+, within the ages in the data.

    Each band lists every whole age it covers as its codes. A last band of fewer than five
    ages (for example "65" in an 18-65 sample) joins the band before it.

    Args:
        series: Ages.

    Returns:
        Categories without shares. Empty when there are no ages.
    """
    ages = pd.to_numeric(series, errors="coerce").dropna()
    if ages.empty:
        return []
    low, high = int(np.floor(ages.min())), int(np.ceil(ages.max()))
    # Reason: start on the published boundary (18, not a youngest respondent of 19).
    low = max([cut for cut in AGE_CUTS if cut <= low], default=low)
    edges = [low] + [cut for cut in AGE_CUTS if low < cut <= high] + [high + 1]
    spans = [(start, end - 1) for start, end in zip(edges, edges[1:], strict=False)]
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] < 4:
        last = spans.pop()
        spans[-1] = (spans[-1][0], last[1])
    found: list[TargetCategory] = []
    for start, end in spans:
        label = f"{start}–{end}" if end > start else str(start)
        found.append(
            TargetCategory(label=label, codes=list(range(start, end + 1)), origin="sample")
        )
    return found


def fill_sample_shares(frame: pd.DataFrame, dimension: WeightingDimension) -> None:
    """Set each category's unweighted share, in percent of all respondents.

    Args:
        frame: Respondent data.
        dimension: Dimension to fill in place.
    """
    total = len(frame)
    series = frame[dimension.variable]
    for category in dimension.categories:
        count = int(in_codes(series, category.codes).sum()) if category.codes else 0
        category.sample_share = round(100.0 * count / total, 2) if total else 0.0


def target_problems(frame: pd.DataFrame, dimensions: list[WeightingDimension]) -> list[str]:
    """Return every reason the targets cannot be raked, in words a researcher can act on.

    Args:
        frame: Respondent data.
        dimensions: Dimensions with target shares.

    Returns:
        Problems. Empty when raking can run.
    """
    problems: list[str] = []
    if not dimensions:
        return ["Add at least one variable to weight on."]
    seen: set[str] = set()
    for dimension in dimensions:
        name = dimension.variable
        if name in seen:
            problems.append(f"{name} is listed twice.")
            continue
        seen.add(name)
        if name not in frame.columns:
            problems.append(f"{name} is not in the dataset.")
            continue
        if not dimension.categories:
            problems.append(f"{name} has no categories.")
            continue
        codes: list[float] = []
        total = 0.0
        series = frame[name]
        for category in dimension.categories:
            if category.target_share is None:
                problems.append(f"{name} '{category.label}' has no target.")
                continue
            if category.target_share < 0:
                problems.append(f"{name} '{category.label}' has a negative target.")
            total += category.target_share
            if not category.codes:
                problems.append(f"{name} '{category.label}' has no answer codes.")
                continue
            overlap = {float(code) for code in category.codes} & set(codes)
            if overlap:
                problems.append(
                    f"{name} '{category.label}' repeats a code used by another category."
                )
            codes.extend(float(code) for code in category.codes)
            if category.target_share > 0 and not in_codes(series, category.codes).any():
                problems.append(
                    f"{name} '{category.label}' has a target of {category.target_share:g}% but no "
                    "respondents. Merge it with a neighbouring category or set its target to 0."
                )
        if abs(total - 100.0) > SUM_TOLERANCE:
            problems.append(f"{name} targets add up to {total:.1f}%, not 100%.")
    return problems


def rake(
    frame: pd.DataFrame,
    dimensions: list[WeightingDimension],
    settings: WeightingSettings,
) -> tuple[pd.Series, dict[str, Any]]:
    """Rake respondents to the target shares.

    Respondents outside every category of a dimension (for example "prefer not to say")
    keep their own share on that dimension, and the targets are scaled to the rest.

    Args:
        frame: Respondent data.
        dimensions: Dimensions whose targets passed ``target_problems``.
        settings: Caps, iteration limit, and tolerance.

    Returns:
        Weights with a mean of 1, and run facts: ``converged``, ``iterations``,
        ``capped``, and ``warnings``.
    """
    count = len(frame)
    weights = np.ones(count)
    warnings: list[str] = []
    cells: list[list[tuple[np.ndarray, float]]] = []
    for dimension in dimensions:
        series = frame[dimension.variable]
        masks = [in_codes(series, category.codes).to_numpy() for category in dimension.categories]
        covered = np.logical_or.reduce(masks) if masks else np.zeros(count, dtype=bool)
        outside = ~covered
        rest = 1.0 - outside.sum() / count if count else 1.0
        total = sum(category.target_share or 0.0 for category in dimension.categories) or 100.0
        plan = [
            (mask, rest * (category.target_share or 0.0) / total)
            for mask, category in zip(masks, dimension.categories, strict=True)
        ]
        if outside.any():
            plan.append((outside, 1.0 - rest))
            warnings.append(
                f"{int(outside.sum())} respondents have no {dimension.variable} category "
                "(such as no answer); they keep their own share on that variable."
            )
        cells.append(plan)
    converged = False
    iteration = 0
    for iteration in range(1, settings.max_iterations + 1):
        before = weights.copy()
        for plan in cells:
            total = weights.sum()
            for mask, share in plan:
                current = weights[mask].sum() / total
                if current > 0:
                    weights[mask] *= share / current
        weights = _cap(weights, settings)
        if np.abs(weights - before).max() < settings.tolerance:
            converged = True
            break
    gap = max(
        (
            abs(weights[mask].sum() / weights.sum() - share)
            for plan in cells
            for mask, share in plan
        ),
        default=0.0,
    )
    met = gap <= MET
    # Reason: the final rescale to a mean of 1 can move a capped weight slightly off its cap.
    capped = int(
        np.sum(weights <= settings.min_weight * 1.01)
        + np.sum(weights >= settings.max_weight * 0.99)
    )
    if not met:
        warnings.append(
            f"Targets are missed by up to {gap * 100:.1f} points, because the weight caps "
            f"({settings.min_weight:g} to {settings.max_weight:g}) stop the weights from going "
            "further. Widen the caps or merge small categories."
        )
    facts = {
        "converged": bool(converged and met),
        "iterations": iteration,
        "capped": capped,
        "warnings": warnings,
    }
    return pd.Series(weights, index=frame.index), facts


def _cap(weights: np.ndarray, settings: WeightingSettings) -> np.ndarray:
    """Keep weights between the caps while their mean stays 1.

    Weights past a cap are set to it, and only the remaining weights are rescaled to
    restore the total. That can push another weight past a cap, so it repeats; each pass
    fixes at least one more weight, so it ends.

    Args:
        weights: Current weights.
        settings: Caps.

    Returns:
        Capped weights with a mean of 1.
    """
    count = len(weights)
    weights = weights * count / weights.sum()
    fixed = np.zeros(count, dtype=bool)
    for _ in range(count + 1):
        low = ~fixed & (weights < settings.min_weight)
        high = ~fixed & (weights > settings.max_weight)
        if not (low.any() or high.any()):
            break
        weights[low] = settings.min_weight
        weights[high] = settings.max_weight
        fixed |= low | high
        free = ~fixed
        room = count - weights[fixed].sum()
        if not free.any() or weights[free].sum() <= 0 or room <= 0:
            break
        weights[free] *= room / weights[free].sum()
    return weights


def efficiency(weights: pd.Series) -> float:
    """Weighting efficiency in percent: the effective base as a share of the sample."""
    values = weights.to_numpy(dtype=float)
    squares = float((values**2).sum())
    if squares <= 0:
        return 0.0
    return float(values.sum() ** 2 / (len(values) * squares) * 100.0)


def achieved_shares(
    frame: pd.DataFrame, dimensions: list[WeightingDimension], weights: pd.Series
) -> list[AchievedShare]:
    """Compare each category's target with the weighted share it reached.

    Shares are measured among respondents who have a category on that variable, the
    same base the targets apply to.

    Args:
        frame: Respondent data.
        dimensions: Dimensions with targets and sample shares.
        weights: Built weights.

    Returns:
        One row per category, in percent.
    """
    rows: list[AchievedShare] = []
    for dimension in dimensions:
        series = frame[dimension.variable]
        masks = [in_codes(series, category.codes) for category in dimension.categories]
        covered = pd.concat(masks, axis=1).any(axis=1) if masks else series.isna() & False
        total = float(weights[covered].sum())
        for mask, category in zip(masks, dimension.categories, strict=True):
            weighted = float(weights[mask].sum()) / total * 100.0 if total else 0.0
            rows.append(
                AchievedShare(
                    variable=dimension.variable,
                    label=category.label,
                    sample_share=float(category.sample_share or 0.0),
                    target_share=float(category.target_share or 0.0),
                    weighted_share=round(weighted, 2),
                )
            )
    return rows
