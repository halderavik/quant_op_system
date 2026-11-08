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
