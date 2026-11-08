"""Regression plugins. Coefficients come from statsmodels, not from a model narrative."""

from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from app.engines.analysis.common import prepare, script_for, versions
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan, AnalysisResult


def run_linear(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Ordinary least squares.

    Args:
        frame: Source data.
        plan: Plan with a dependent variable and predictors.

    Returns:
        Coefficients, fit, and VIF diagnostics.
    """
    dependent = plan.dependent.name if plan.dependent else ""
    data, flow = prepare(frame, plan, [dependent, *plan.predictors])
    model, used_weights = _fit_ols(data[dependent], data[plan.predictors], frame, plan, data.index)
    return _pack(plan, flow, model, used_weights, data[plan.predictors])


def run_logistic(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Binary logistic regression.

    Args:
        frame: Source data.
        plan: Plan whose dependent variable is binary.

    Returns:
        Coefficients and fit statistics.
    """
    dependent = plan.dependent.name if plan.dependent else ""
    data, flow = prepare(frame, plan, [dependent, *plan.predictors])
    outcome = data[dependent]
    unique = set(outcome.unique())
    if not unique.issubset({0.0, 1.0}):
        raise AppError(
            "Binary logistic regression needs a dependent variable coded 0 and 1.",
            "bad_plan",
        )
    exog = sm.add_constant(data[plan.predictors], has_constant="add")
    try:
        if plan.weight_variable:
            weights = _aligned_weights(frame, plan, data.index)
            model = sm.GLM(outcome, exog, family=sm.families.Binomial(), freq_weights=weights).fit()
            used_weights = True
        else:
            model = sm.Logit(outcome, exog).fit(disp=False)
            used_weights = False
    except Exception as exc:
        raise AppError(
            "Logistic regression did not converge. Check separation, empty cells, and coding.",
            "model_failed",
        ) from exc
    result = _pack(plan, flow, model, used_weights, data[plan.predictors])
    if not getattr(model, "mle_retvals", {}).get("converged", True):
        result.warnings.append("The logistic model reported a convergence problem.")
    return result


def run_ordinal(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Ordinal regression via statsmodels OrderedModel.

    Args:
        frame: Source data.
        plan: Plan with an ordered dependent variable.

    Returns:
        Coefficients. Thresholds are included in the estimates.
    """
    from statsmodels.miscmodels.ordinal_model import OrderedModel

    dependent = plan.dependent.name if plan.dependent else ""
    data, flow = prepare(frame, plan, [dependent, *plan.predictors])
    try:
        model = OrderedModel(data[dependent], data[plan.predictors], distr="logit").fit(
            method="bfgs", disp=False
        )
    except Exception as exc:
        raise AppError(
            "Ordinal regression failed. The dependent variable needs at least three ordered levels.",
            "model_failed",
        ) from exc
    estimates = {
        name: {"coefficient": float(model.params[name])}
        for name in model.params.index
        if name in plan.predictors
    }
    return AnalysisResult(
        method=plan.method,
        sample_flow=flow,
        model_estimates=estimates,
        metrics={"llf": float(model.llf)},
        warnings=["Ordinal thresholds are estimated. Do not read coefficients as linear effects."],
        software_versions=versions(),
        seed=plan.random_seed,
        script=script_for(plan),
    )


def run_key_driver(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Relative importance from absolute standardized regression coefficients, scaled to 100.

    Args:
        frame: Source data.
        plan: Plan with one dependent variable and predictors.

    Returns:
        Importance shares and the underlying standardized coefficients.
    """
    dependent = plan.dependent.name if plan.dependent else ""
    data, flow = prepare(frame, plan, [dependent, *plan.predictors])
    scaled = (data - data.mean()) / data.std(ddof=0).replace(0, np.nan)
    if scaled.isna().any().any():
        raise AppError("A key-driver variable has zero variance.", "bad_plan")
    model = sm.OLS(
        scaled[dependent], sm.add_constant(scaled[plan.predictors], has_constant="add")
    ).fit()
    coefs = {name: float(model.params[name]) for name in plan.predictors}
    absolute = {name: abs(value) for name, value in coefs.items()}
    total = sum(absolute.values())
    if total == 0:
        raise AppError("Key-driver coefficients are all zero.", "model_failed")
    shares = {name: 100.0 * value / total for name, value in absolute.items()}
    estimates = {
        name: {"standardized_coefficient": coefs[name], "importance_pct": shares[name]}
        for name in plan.predictors
    }
    return AnalysisResult(
        method=plan.method,
        sample_flow=flow,
        model_estimates=estimates,
        metrics={
            "r_squared": float(model.rsquared),
            "importance_definition": "abs_standardized_ols_share_of_100",
        },
        warnings=[
            "Importance is the absolute standardized OLS coefficient, normalized to sum to 100. "
            "It is regression-based, not a causal share."
        ],
        software_versions=versions(),
        seed=plan.random_seed,
        script=script_for(plan),
    )


def _fit_ols(
    outcome: pd.Series,
    predictors: pd.DataFrame,
    frame: pd.DataFrame,
    plan: AnalysisPlan,
    index: pd.Index,
) -> tuple[Any, bool]:
    """Fit OLS, using frequency weights only when a weight was requested.

    Args:
        outcome: Dependent series.
        predictors: Predictor frame.
        frame: Original frame, used for weights.
        plan: Analysis plan.
        index: Rows retained after listwise deletion.

    Returns:
        Fitted model and whether weights were applied.
    """
    exog = sm.add_constant(predictors, has_constant="add")
    if plan.weight_variable:
        weights = _aligned_weights(frame, plan, index)
        return sm.WLS(outcome, exog, weights=weights).fit(), True
    return sm.OLS(outcome, exog).fit(), False


def _aligned_weights(frame: pd.DataFrame, plan: AnalysisPlan, index: pd.Index) -> pd.Series:
    """Return positive finite weights for the analysis rows.

    Args:
        frame: Original data.
        plan: Analysis plan.
        index: Retained rows.

    Returns:
        Weights.
    """
    if plan.weight_variable not in frame.columns:
        raise AppError(
            f"Weight variable '{plan.weight_variable}' is not in the dataset", "missing_variable"
        )
    weights = pd.to_numeric(frame.loc[index, plan.weight_variable], errors="coerce")
    if (weights < 0).any():
        raise AppError("Negative weights are rejected.", "negative_weight")
    if weights.isna().any() or (weights <= 0).any():
        raise AppError(
            "Analysis weights must be positive and finite. Zero-weight rows need an explicit filter.",
            "bad_weight",
        )
    return weights


def _pack(
    plan: AnalysisPlan,
    flow: dict,
    model: Any,
    used_weights: bool,
    predictors: pd.DataFrame,
) -> AnalysisResult:
    """Convert a fitted model into the result contract.

    Args:
        plan: Analysis plan.
        flow: Sample flow.
        model: Fitted statsmodels result.
        used_weights: Whether weights entered the fit.
        predictors: Predictor frame used for VIF.

    Returns:
        Analysis result.
    """
    estimates = {}
    for name in model.params.index:
        estimates[str(name)] = {
            "coefficient": float(model.params[name]),
            "std_error": float(model.bse[name]),
            "p_value": float(model.pvalues[name]),
        }
    warnings = []
    if used_weights:
        warnings.append(
            "Weights were applied as frequency weights. Standard errors are not survey-design standard errors."
        )
    vif = _vif(predictors)
    if any(value > 10 for value in vif.values()):
        warnings.append(
            "A predictor has VIF above 10. Collinearity may make coefficients unstable."
        )
    metrics = {"vif": vif}
    if hasattr(model, "rsquared"):
        metrics["r_squared"] = float(model.rsquared)
    if hasattr(model, "prsquared"):
        metrics["pseudo_r_squared"] = float(model.prsquared)
    if hasattr(model, "llf"):
        metrics["llf"] = float(model.llf)
    return AnalysisResult(
        method=plan.method,
        sample_flow=flow,
        model_estimates=estimates,
        metrics=metrics,
        diagnostics={"nobs": int(model.nobs)},
        warnings=warnings,
        software_versions=versions(),
        seed=plan.random_seed,
        script=script_for(plan),
    )


def _vif(predictors: pd.DataFrame) -> dict[str, float]:
    """Variance inflation factors for predictors that have variance.

    Args:
        predictors: Predictor columns.

    Returns:
        VIF by column name.
    """
    if predictors.shape[1] < 2:
        return {}
    exog = sm.add_constant(predictors, has_constant="add")
    values: dict[str, float] = {}
    for index, name in enumerate(exog.columns):
        if name == "const":
            continue
        try:
            values[str(name)] = float(variance_inflation_factor(exog.to_numpy(), index))
        except Exception:
            continue
    return values
