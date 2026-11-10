"""Dimension reduction, clustering, correspondence, reliability, and discriminant."""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA, FactorAnalysis
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.engines.analysis.common import prepare, prepare_clustering, script_for, versions
from app.engines.expression import mask_frame
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan, AnalysisResult


def run_pca(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Principal components on standardized variables.

    Args:
        frame: Source data.
        plan: Plan with ``variables``.

    Returns:
        Variance ratios and loadings.
    """
    data, flow = prepare(frame, plan, plan.variables)
    n_components = int(plan.options.get("n_components") or min(3, data.shape[1]))
    model = PCA(n_components=n_components, random_state=plan.random_seed)
    model.fit(StandardScaler().fit_transform(data))
    loadings = {
        f"PC{index + 1}": {
            name: float(model.components_[index, col]) for col, name in enumerate(plan.variables)
        }
        for index in range(n_components)
    }
    return _done(
        plan,
        flow,
        metrics={"explained_variance_ratio": [float(v) for v in model.explained_variance_ratio_]},
        estimates=loadings,
    )


def run_efa(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Exploratory factor analysis via sklearn FactorAnalysis.

    Args:
        frame: Source data.
        plan: Plan with ``variables``.

    Returns:
        Loadings and communalities. This is not a principal-axis factor analysis.
    """
    data, flow = prepare(frame, plan, plan.variables)
    n_components = int(plan.options.get("n_components") or min(2, data.shape[1]))
    scaled = StandardScaler().fit_transform(data)
    model = FactorAnalysis(n_components=n_components, random_state=plan.random_seed)
    model.fit(scaled)
    loadings = model.components_.T
    communalities = np.sum(loadings**2, axis=1)
    estimates = {
        name: {"communality": float(communalities[index])}
        | {f"factor_{factor + 1}": float(loadings[index, factor]) for factor in range(n_components)}
        for index, name in enumerate(plan.variables)
    }
    warnings = [
        "EFA uses sklearn FactorAnalysis. It is not a minimum-residual or principal-axis extraction."
    ]
    if flow["valid_n"] < 5 * len(plan.variables):
        warnings.append("The sample is small relative to the number of items.")
    return _done(plan, flow, estimates=estimates, warnings=warnings)


def run_clustering(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """K-means on standardized features.

    Args:
        frame: Source data.
        plan: Plan with ``variables``. ``options.k`` defaults to 2.

    Returns:
        Labels, sizes, and silhouette. Sizes sum to the valid N.
    """
    data, flow, notes = prepare_clustering(frame, plan)
    k = int(plan.options.get("k") or 2)
    if k < 2 or k >= len(data):
        raise AppError(
            "Clustering k must be at least 2 and smaller than the valid sample.", "bad_plan"
        )
    scaled = StandardScaler().fit_transform(data)
    model = KMeans(n_clusters=k, random_state=plan.random_seed, n_init=10)
    labels = model.fit_predict(scaled)
    sizes = {str(cluster): int((labels == cluster).sum()) for cluster in range(k)}
    profiles = {}
    for cluster in range(k):
        profiles[str(cluster)] = {
            name: float(data.iloc[labels == cluster][name].mean()) for name in data.columns
        }
    score = float(silhouette_score(scaled, labels)) if len(set(labels)) > 1 else None
    return _done(
        plan,
        flow,
        estimates={"sizes": sizes, "profiles": profiles},
        metrics={"silhouette": score, "inertia": float(model.inertia_)},
        descriptive={"labels": [int(label) for label in labels]},
        warnings=[
            "Cluster labels depend on the seed and on standardizing features before K-means.",
            *notes,
        ],
    )


def run_correspondence(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Correspondence analysis of two categorical variables via SVD.

    Args:
        frame: Source data.
        plan: Plan with ``var_a`` and ``var_b``.

    Returns:
        Row and column coordinates and total inertia.
    """
    if not plan.var_a or not plan.var_b:
        raise AppError("Correspondence analysis needs two categorical variables.", "bad_plan")
    mask = mask_frame(plan.filter, frame)
    table = pd.crosstab(frame.loc[mask, plan.var_a], frame.loc[mask, plan.var_b])
    matrix = table.to_numpy(dtype=float)
    total = matrix.sum()
    if total == 0:
        raise AppError("The correspondence table is empty.", "small_sample")
    expected = np.outer(matrix.sum(axis=1), matrix.sum(axis=0)) / total
    residual = (matrix - expected) / np.sqrt(expected)
    _u, singular, _vt = np.linalg.svd(residual, full_matrices=False)
    inertia = float(np.sum(singular**2) / total)
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(mask.sum()),
        "valid_n": int(total),
        "exclusion_reason_counts": {"filtered_out": int((~mask).sum())},
    }
    return _done(
        plan,
        flow,
        metrics={"inertia": inertia, "singular_values": [float(value) for value in singular]},
        descriptive={"table": table.to_dict()},
    )


def run_reliability(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Cronbach's alpha for a set of items.

    Args:
        frame: Source data.
        plan: Plan with two or more items.

    Returns:
        Alpha and item counts.
    """
    if len(plan.variables) < 2:
        raise AppError("Reliability needs at least two items.", "bad_plan")
    data, flow = prepare(frame, plan, plan.variables)
    k = data.shape[1]
    item_var = data.var(axis=0, ddof=1).sum()
    total_var = data.sum(axis=1).var(ddof=1)
    alpha = float((k / (k - 1)) * (1 - item_var / total_var)) if total_var else None
    return _done(plan, flow, metrics={"cronbach_alpha": alpha, "items": k})


def run_discriminant(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult:
    """Linear discriminant analysis. Accuracy is in-sample and labelled as such.

    Args:
        frame: Source data.
        plan: Plan with a grouping dependent and predictors.

    Returns:
        In-sample accuracy and a warning that it is not cross-validated.
    """
    dependent = plan.dependent.name if plan.dependent else ""
    data, flow = prepare(frame, plan, [dependent, *plan.predictors])
    model = LinearDiscriminantAnalysis()
    model.fit(data[plan.predictors], data[dependent])
    accuracy = float(model.score(data[plan.predictors], data[dependent]))
    return _done(
        plan,
        flow,
        metrics={"in_sample_accuracy": accuracy},
        warnings=["Accuracy is the training-sample score, not a validated holdout."],
    )


def _done(
    plan: AnalysisPlan,
    flow: dict,
    *,
    estimates: dict | None = None,
    metrics: dict | None = None,
    descriptive: dict | None = None,
    warnings: list[str] | None = None,
) -> AnalysisResult:
    """Build a result for a multivariate plugin.

    Args:
        plan: Analysis plan.
        flow: Sample flow.
        estimates: Model estimates.
        metrics: Metrics.
        descriptive: Descriptives.
        warnings: Warnings.

    Returns:
        Analysis result.
    """
    return AnalysisResult(
        method=plan.method,
        sample_flow=flow,
        model_estimates=estimates or {},
        metrics=metrics or {},
        descriptive=descriptive or {},
        warnings=warnings or [],
        software_versions=versions(),
        seed=plan.random_seed,
        script=script_for(plan),
    )
