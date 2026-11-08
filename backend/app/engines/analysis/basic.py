"""Descriptive, association, and group-comparison plugins."""

from typing import Any

import pandas as pd
from scipy import stats

from app.engines.analysis.common import prepare, script_for, versions
from app.schemas.analysis import AnalysisPlan, AnalysisResult


def run_descriptive(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Summarise numeric variables.

    Args:
        frame: Source data.
        plan: Plan with ``variables``.

    Returns:
        Means, standard deviations, and sample flow.
    """
    data, flow = prepare(frame, plan, plan.variables)
    descriptive = {}
    for name in plan.variables:
        descriptive[name] = {
            "mean": float(data[name].mean()),
            "std": float(data[name].std(ddof=1)),
            "n": int(data[name].shape[0]),
        }
    return _result(plan, flow, descriptive=descriptive)


def run_correlation(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Pearson correlations among numeric variables.

    Args:
        frame: Source data.
        plan: Plan with at least two variables.

    Returns:
        Correlation matrix and pairwise p-values.
    """
    data, flow = prepare(frame, plan, plan.variables)
    corr = data.corr(method="pearson")
    p_values: dict[str, float] = {}
    for left in range(len(plan.variables)):
        for right in range(left + 1, len(plan.variables)):
            a = plan.variables[left]
            b = plan.variables[right]
            _coef, p_value = stats.pearsonr(data[a], data[b])
            p_values[f"{a}__{b}"] = float(p_value)
    return _result(
        plan,
        flow,
        metrics={"correlation": corr.round(6).to_dict(), "p_values": p_values},
    )


def run_chi_square(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Chi-square test of two categorical variables.

    Args:
        frame: Source data.
        plan: Plan with ``var_a`` and ``var_b``.

    Returns:
        Chi-square statistic, p-value, and expected counts warning when sparse.
    """
    from app.engines.expression import mask_frame

    mask = mask_frame(plan.filter, frame)
    table = pd.crosstab(frame.loc[mask, plan.var_a], frame.loc[mask, plan.var_b])
    chi2, p_value, dof, expected = stats.chi2_contingency(table)
    warnings = []
    if (expected < 5).any():
        warnings.append("Some expected cell counts are below 5. Treat the p-value cautiously.")
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(mask.sum()),
        "valid_n": int(table.to_numpy().sum()),
        "exclusion_reason_counts": {"filtered_out": int((~mask).sum())},
    }
    return _result(
        plan,
        flow,
        metrics={"chi2": float(chi2), "p_value": float(p_value), "dof": int(dof)},
        descriptive={"table": table.to_dict()},
        warnings=warnings,
    )


def run_t_test(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Independent-samples t-test for exactly two groups.

    Args:
        frame: Source data.
        plan: Plan with a numeric dependent and a grouping variable.

    Returns:
        t statistic and p-value.
    """
    return _group_test(frame, plan, kind="t_test")


def run_anova(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """One-way ANOVA across groups.

    Args:
        frame: Source data.
        plan: Plan with a numeric dependent and a grouping variable.

    Returns:
        F statistic and p-value.
    """
    return _group_test(frame, plan, kind="anova")


def _group_test(frame: pd.DataFrame, plan: AnalysisPlan, *, kind: str) -> AnalysisResult:
    """Run a t-test or ANOVA.

    Args:
        frame: Source data.
        plan: Analysis plan.
        kind: ``t_test`` or ``anova``.

    Returns:
        Test result.
    """
    from app.engines.expression import mask_frame
    from app.errors import AppError

    dependent = plan.dependent.name if plan.dependent else ""
    group = plan.group or ""
    mask = mask_frame(plan.filter, frame)
    data = frame.loc[mask, [dependent, group]].dropna()
    groups = [
        data.loc[data[group] == level, dependent].astype(float) for level in data[group].unique()
    ]
    groups = [series for series in groups if len(series)]
    if kind == "t_test" and len(groups) != 2:
        raise AppError("A t-test needs exactly two groups in the grouping variable.", "bad_plan")
    if kind == "anova" and len(groups) < 2:
        raise AppError("ANOVA needs at least two groups.", "bad_plan")
    if kind == "t_test":
        stat, p_value = stats.ttest_ind(groups[0], groups[1], equal_var=False)
        metrics = {"t": float(stat), "p_value": float(p_value)}
    else:
        stat, p_value = stats.f_oneway(*groups)
        metrics = {"f": float(stat), "p_value": float(p_value)}
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(mask.sum()),
        "valid_n": int(len(data)),
        "exclusion_reason_counts": {"filtered_out": int((~mask).sum())},
    }
    return _result(plan, flow, metrics=metrics)


def _result(
    plan: AnalysisPlan,
    flow: dict[str, Any],
    *,
    descriptive: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> AnalysisResult:
    """Assemble a result object.

    Args:
        plan: Analysis plan.
        flow: Sample flow.
        descriptive: Optional descriptives.
        metrics: Optional metrics.
        warnings: Optional warnings.

    Returns:
        Analysis result.
    """
    return AnalysisResult(
        method=plan.method,
        sample_flow=flow,
        descriptive=descriptive or {},
        metrics=metrics or {},
        warnings=warnings or [],
        software_versions=versions(),
        seed=plan.random_seed,
        script=script_for(plan),
    )
