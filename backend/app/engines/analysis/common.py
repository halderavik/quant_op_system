"""Shared sample-flow and software-version helpers."""

from typing import Any

import numpy as np
import pandas as pd
import sklearn
import statsmodels

from app.engines.expression import mask_frame
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan


def versions() -> dict[str, str]:
    """Return library versions stamped on every analysis result.

    Returns:
        Package versions.
    """
    return {
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "statsmodels": statsmodels.__version__,
        "scikit-learn": sklearn.__version__,
    }


def prepare(
    frame: pd.DataFrame, plan: AnalysisPlan, columns: list[str]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply the filter and listwise deletion.

    Args:
        frame: Source data.
        plan: Analysis plan.
        columns: Columns required to be non-missing.

    Returns:
        Analysis frame and sample-flow counts.
    """
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise AppError(
            f"These variables are not in the dataset: {', '.join(missing)}",
            "missing_variable",
        )
    filtered = mask_frame(plan.filter, frame)
    subset = frame.loc[filtered, columns].apply(pd.to_numeric, errors="coerce")
    valid = subset.notna().all(axis=1)
    reasons = {
        "filtered_out": int((~filtered).sum()),
        "listwise_missing": int((filtered & ~valid).sum()),
    }
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(filtered.sum()),
        "valid_n": int(valid.sum()),
        "exclusion_reason_counts": reasons,
    }
    if flow["valid_n"] < 3:
        raise AppError(
            "Fewer than 3 complete rows remain after the filter and listwise deletion.",
            "small_sample",
        )
    return subset.loc[valid].astype(float), flow


def prepare_clustering(
    frame: pd.DataFrame, plan: AnalysisPlan
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    """Prepare k-means features when named variables are not on one base.

    Args:
        frame: Source data.
        plan: Analysis plan. ``variables`` are the requested features.

    Returns:
        Analysis frame, sample-flow counts, and notes about variables left out.

    Raises:
        AppError: A named variable is missing, fewer than two variables have
            answers, or fewer than three rows share the kept variables.
    """
    missing = [name for name in plan.variables if name not in frame.columns]
    if missing:
        raise AppError(
            f"These variables are not in the dataset: {', '.join(missing)}",
            "missing_variable",
        )
    filtered = mask_frame(plan.filter, frame)
    subset = frame.loc[filtered, plan.variables].apply(pd.to_numeric, errors="coerce")
    counts = subset.notna().sum()
    empty = [name for name in plan.variables if int(counts[name]) == 0]
    present = [name for name in plan.variables if name not in empty]
    if len(present) < 2:
        extra = _empty_note(empty)
        message = "Clustering needs at least two variables with numeric answers."
        raise AppError(f"{message} {extra}".strip(), "small_sample")
    kept, skipped, floor = _shared_base(subset[present])
    notes = _exclusion_notes(empty, skipped, counts, floor)
    if len(kept) < 2:
        if int(counts[present].max()) < 3:
            raise AppError(
                "Fewer than 3 complete rows remain after the filter and listwise deletion.",
                "small_sample",
            )
        detail = f" {' '.join(notes)}" if notes else ""
        raise AppError(
            "Clustering needs at least two variables with numeric answers on the same rows."
            + detail,
            "small_sample",
        )
    valid = subset[kept].notna().all(axis=1)
    if int(valid.sum()) < 3:
        raise AppError(
            "Fewer than 3 complete rows remain after the filter and listwise deletion.",
            "small_sample",
        )
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(filtered.sum()),
        "valid_n": int(valid.sum()),
        "exclusion_reason_counts": {
            "filtered_out": int((~filtered).sum()),
            "listwise_missing": int((~valid).sum()),
            "excluded_variables": len(empty) + len(skipped),
        },
        "variables_used": kept,
        "variables_excluded": [{"name": name, "reason": "no numeric answers"} for name in empty]
        + [
            {
                "name": name,
                "reason": (
                    f"answered by {int(counts[name])} respondents; "
                    f"kept base stays at least {floor}"
                ),
            }
            for name in skipped
        ],
    }
    return subset.loc[valid, kept].astype(float), flow, notes


def _shared_base(subset: pd.DataFrame) -> tuple[list[str], list[str], int]:
    """Keep variables that can share a base of at least half the fullest variable.

    Args:
        subset: Numeric columns that each have at least one observed value.

    Returns:
        Kept names in request order, skipped names, and the minimum accepted base.
    """
    groups: dict[bytes, list[str]] = {}
    for name in subset.columns:
        # Reason: items asked of the same respondents share a missingness pattern.
        signature = np.packbits(subset[name].notna().to_numpy(dtype=bool)).tobytes()
        groups.setdefault(signature, []).append(str(name))
    ordered = sorted(
        groups.values(),
        key=lambda columns: (
            -int(subset[columns[0]].notna().sum()),
            -len(columns),
            columns[0],
        ),
    )
    fullest = int(subset[ordered[0][0]].notna().sum())
    # Reason: a skip-group battery should not pull the segmentation down to that base.
    floor = max(3, fullest // 2)
    if fullest < 3:
        return [], [name for columns in ordered for name in columns], floor
    kept_mask = subset[ordered[0][0]].notna()
    kept = list(ordered[0])
    skipped: list[str] = []
    for columns in ordered[1:]:
        trial = kept_mask & subset[columns[0]].notna()
        if int(trial.sum()) >= floor:
            kept_mask = trial
            kept.extend(columns)
        else:
            skipped.extend(columns)
    kept_names = [name for name in subset.columns if name in set(kept)]
    return kept_names, skipped, floor


def _exclusion_notes(
    empty: list[str], skipped: list[str], counts: pd.Series, floor: int
) -> list[str]:
    """Describe variables that were not used as clustering features.

    Args:
        empty: Variables with no numeric answers.
        skipped: Variables on a base that would shrink the sample too far.
        counts: Observed counts on the filtered frame.
        floor: Smallest base that was still accepted.

    Returns:
        Sentences for the chat reply and the report caveats.
    """
    notes: list[str] = []
    if empty:
        notes.append(
            f"Left out {', '.join(empty)} because those variables have no numeric answers."
        )
    by_count: dict[int, list[str]] = {}
    for name in skipped:
        by_count.setdefault(int(counts[name]), []).append(name)
    for count, names in by_count.items():
        notes.append(
            f"Left out {', '.join(names)} because they are answered by {count} respondents "
            f"and including them would leave fewer than {floor} complete rows."
        )
    return notes


def _empty_note(empty: list[str]) -> str:
    """Name variables that contributed no numeric answers.

    Args:
        empty: Variable names.

    Returns:
        A sentence, or an empty string when nothing was empty.
    """
    if not empty:
        return ""
    return f"Left out {', '.join(empty)} because those variables have no numeric answers."


def script_for(plan: AnalysisPlan) -> str:
    """Return a short reproducible description of the run.

    Args:
        plan: Analysis plan.

    Returns:
        Python-like script text stored with the result.
    """
    return "\n".join(
        [
            f"# method={plan.method}",
            f"# seed={plan.random_seed}",
            f"# dependent={plan.dependent.name if plan.dependent else ''}",
            f"# predictors={plan.predictors}",
            f"# variables={plan.variables}",
            f"# weight={plan.weight_variable or ''}",
            "import statsmodels.api as sm",
            "import sklearn",
            "# Executed by the registered plugin, not by eval of this text.",
        ]
    )
