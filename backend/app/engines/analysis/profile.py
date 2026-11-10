"""Compact dataset facts for the analysis planner. No respondent rows."""

from typing import Any

import pandas as pd

from app.engines.tabspec_profile import DatasetProfile, build_profile


def column_briefs(
    frame: pd.DataFrame, variables: list[dict[str, Any]], *, limit: int = 250
) -> tuple[list[dict[str, Any]], int]:
    """Describe columns the planner may name.

    Args:
        frame: Respondent data. Only counts are read.
        variables: Variable dictionary.
        limit: Maximum briefs returned.

    Returns:
        Briefs, and how many analyzable columns were left off the list.
    """
    profile = build_profile(frame, variables)
    return briefs_from_profile(profile, row_count=int(len(frame)), limit=limit)


def briefs_from_profile(
    profile: DatasetProfile, *, row_count: int, limit: int = 250
) -> tuple[list[dict[str, Any]], int]:
    """Turn a dataset profile into planner briefs.

    Args:
        profile: Column profile.
        row_count: Respondent count.
        limit: Maximum briefs returned.

    Returns:
        Briefs, and how many analyzable columns were left off the list.
    """
    briefs: list[dict[str, Any]] = []
    skipped = 0
    for column in profile.columns:
        if column.shape in {"empty", "text", "admin"}:
            continue
        if len(briefs) >= limit:
            skipped += 1
            continue
        labels = list(column.value_labels.items())[:8]
        briefs.append(
            {
                "name": column.name,
                "label": column.label,
                "shape": column.shape,
                "nonmissing_n": column.nonmissing_n,
                "missing_n": max(row_count - column.nonmissing_n, 0),
                "value_labels": dict(labels),
                "user_missing": column.user_missing[:6],
            }
        )
    return briefs, skipped
