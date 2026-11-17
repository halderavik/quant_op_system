"""Descriptive, association, and group-comparison plugins."""

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.engines.analysis.common import prepare, script_for, versions
from app.engines.analysis.standards import ALPHA
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
    total = float(table.to_numpy().sum())
    smaller = min(table.shape) - 1
    cramers_v = float(np.sqrt(chi2 / (total * smaller))) if total and smaller > 0 else 0.0
    low_share = float((expected < 5).mean()) if expected.size else 0.0
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(mask.sum()),
        "valid_n": int(table.to_numpy().sum()),
        "exclusion_reason_counts": {"filtered_out": int((~mask).sum())},
    }
    return _result(
        plan,
        flow,
        metrics={
            "chi2": float(chi2),
            "p_value": float(p_value),
            "dof": int(dof),
            "cramers_v": cramers_v,
            "low_expected_share": low_share,
        },
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
    levels = [level for level in sorted(data[group].unique()) if (data[group] == level).any()]
    groups = [data.loc[data[group] == level, dependent].astype(float) for level in levels]
    if kind == "t_test" and len(groups) != 2:
        raise AppError("A t-test needs exactly two groups in the grouping variable.", "bad_plan")
    if kind == "anova" and len(groups) < 2:
        raise AppError("ANOVA needs at least two groups.", "bad_plan")
    summary = {
        _level(level): {"n": int(len(series)), "mean": float(series.mean()), "std": _sd(series)}
        for level, series in zip(levels, groups, strict=True)
    }
    descriptive: dict[str, Any] = {"groups": summary}
    if kind == "t_test":
        stat, p_value = stats.ttest_ind(groups[0], groups[1], equal_var=False)
        metrics = {"t": float(stat), "p_value": float(p_value), "cohens_d": _cohens_d(*groups)}
    else:
        stat, p_value = stats.f_oneway(*groups)
        values = data[dependent].astype(float)
        total = float(((values - values.mean()) ** 2).sum())
        between = float(sum(len(item) * (item.mean() - values.mean()) ** 2 for item in groups))
        metrics = {
            "f": float(stat),
            "p_value": float(p_value),
            "eta_squared": between / total if total else 0.0,
        }
        if all(len(item) > 1 for item in groups):
            tukey = stats.tukey_hsd(*groups)
            descriptive["post_hoc"] = [
                {
                    "pair": f"{_level(levels[i])} vs {_level(levels[j])}",
                    "difference": float(groups[i].mean() - groups[j].mean()),
                    "p_value": float(tukey.pvalue[i, j]),
                    "significant": bool(tukey.pvalue[i, j] < ALPHA),
                }
                for i in range(len(groups))
                for j in range(i + 1, len(groups))
            ]
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(mask.sum()),
        "valid_n": int(len(data)),
        "exclusion_reason_counts": {"filtered_out": int((~mask).sum())},
    }
    return _result(plan, flow, metrics=metrics, descriptive=descriptive)


def _level(value: Any) -> str:
    """Return a group code as text, without a trailing .0."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _sd(series: pd.Series) -> float:
    """Sample standard deviation, or 0 for one value."""
    return float(series.std(ddof=1)) if len(series) > 1 else 0.0


def _cohens_d(first: pd.Series, second: pd.Series) -> float:
    """Cohen's d with a pooled standard deviation."""
    pooled_n = len(first) + len(second) - 2
    if pooled_n <= 0:
        return 0.0
    pooled = ((len(first) - 1) * _sd(first) ** 2 + (len(second) - 1) * _sd(second) ** 2) / pooled_n
    return float((first.mean() - second.mean()) / np.sqrt(pooled)) if pooled > 0 else 0.0


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
