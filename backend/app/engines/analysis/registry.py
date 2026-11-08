"""Method registry. Unsupported names, MaxDiff, and conjoint never produce numbers."""

from collections.abc import Callable

import pandas as pd

from app.engines.analysis.basic import (
    run_anova,
    run_chi_square,
    run_correlation,
    run_descriptive,
    run_t_test,
)
from app.engines.analysis.multivariate import (
    run_clustering,
    run_correspondence,
    run_discriminant,
    run_efa,
    run_pca,
    run_reliability,
)
from app.engines.analysis.regression import run_key_driver, run_linear, run_logistic, run_ordinal
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan, AnalysisResult

Runner = Callable[[pd.DataFrame, AnalysisPlan], AnalysisResult]

SUPPORTED_METHODS: dict[str, Runner] = {
    "descriptive": run_descriptive,
    "correlation": run_correlation,
    "chi_square": run_chi_square,
    "t_test": run_t_test,
    "anova": run_anova,
    "linear_regression": run_linear,
    "binary_logistic_regression": run_logistic,
    "ordinal_regression": run_ordinal,
    "key_driver": run_key_driver,
    "pca": run_pca,
    "efa": run_efa,
    "clustering": run_clustering,
    "discriminant": run_discriminant,
    "correspondence": run_correspondence,
    "reliability": run_reliability,
}

_BLOCKED = {"maxdiff", "max-diff", "conjoint", "cbc"}

_REQUIRED: dict[str, list[str]] = {
    "descriptive": ["variables"],
    "correlation": ["variables"],
    "chi_square": ["var_a", "var_b"],
    "t_test": ["dependent", "group"],
    "anova": ["dependent", "group"],
    "linear_regression": ["dependent", "predictors"],
    "binary_logistic_regression": ["dependent", "predictors"],
    "ordinal_regression": ["dependent", "predictors"],
    "key_driver": ["dependent", "predictors"],
    "pca": ["variables"],
    "efa": ["variables"],
    "clustering": ["variables"],
    "discriminant": ["dependent", "predictors"],
    "correspondence": ["var_a", "var_b"],
    "reliability": ["variables"],
}


def validate_roles(plan: AnalysisPlan) -> list[str]:
    """Return the names of required roles that are still empty.

    Args:
        plan: Analysis plan.

    Returns:
        Missing role names. This does not choose a dependent variable.
    """
    method = plan.method.lower().replace(" ", "_")
    if method in _BLOCKED:
        return []
    missing = []
    for role in _REQUIRED.get(method, []):
        if role == "dependent" and (plan.dependent is None or not plan.dependent.name):
            missing.append("dependent")
        elif role == "predictors" and not plan.predictors:
            missing.append("predictors")
        elif role == "variables" and len(plan.variables) < 2 and method != "descriptive":
            missing.append("variables")
        elif role == "variables" and method == "descriptive" and not plan.variables:
            missing.append("variables")
        elif role == "group" and not plan.group:
            missing.append("group")
        elif role == "var_a" and not plan.var_a:
            missing.append("var_a")
        elif role == "var_b" and not plan.var_b:
            missing.append("var_b")
    return missing


def run_plan(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Execute a registered method.

    Args:
        frame: Source data.
        plan: Validated plan.

    Returns:
        Computed result.

    Raises:
        AppError: For blocked, unsupported, or incomplete plans.
    """
    method = plan.method.lower().replace(" ", "_")
    if method in _BLOCKED:
        raise AppError(
            "MaxDiff and conjoint are out of scope for this studio. No alternative model was run.",
            "unsupported_method",
        )
    if method not in SUPPORTED_METHODS:
        raise AppError(
            f"'{plan.method}' is not a registered method. Registered methods: "
            + ", ".join(sorted(SUPPORTED_METHODS)),
            "unsupported_method",
        )
    missing = validate_roles(plan)
    if missing:
        raise AppError(
            "The analysis needs these fields before it can run: " + ", ".join(missing),
            "missing_roles",
        )
    plan.method = method
    return SUPPORTED_METHODS[method](frame, plan)
