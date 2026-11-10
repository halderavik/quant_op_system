"""Segmentation procedures beyond k-means, plus a supplied compute function.

MaxDiff and conjoint are not handled here. Every number comes from this code.
"""

from typing import Any

import numpy as np
import pandas as pd

from app.engines.analysis.common import prepare_clustering, script_for, versions
from app.engines.analysis.multivariate import run_clustering
from app.engines.analysis.procedure_code import run_procedure
from app.engines.analysis.segmenters import dbscan, hierarchical, mixture, pam, spectral
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan, AnalysisResult


def normalize_method(method: str) -> str:
    """Return a method name in lower case with underscores.

    Args:
        method: Planner or user method name.

    Returns:
        Normalized name.
    """
    return method.strip().lower().replace(" ", "_").replace("-", "_")


def family(method: str) -> str | None:
    """Return the procedure family a method name selects.

    Args:
        method: Method name.

    Returns:
        ``kmeans``, ``pam_gower``, ``hierarchical``, ``dbscan``,
        ``gaussian_mixture``, ``spectral``, or None.
    """
    name = normalize_method(method)
    if name in {"clustering", "kmeans", "k_means"}:
        return "kmeans"
    if any(token in name for token in ("hierarch", "agglomerat", "ward", "linkage")):
        return "hierarchical"
    if any(token in name for token in ("pam", "medoid", "gower")):
        return "pam_gower"
    if "dbscan" in name:
        return "dbscan"
    if any(token in name for token in ("gaussian", "gmm", "mixture")):
        return "gaussian_mixture"
    if "spectral" in name:
        return "spectral"
    return None


def is_segmentation(method: str) -> bool:
    """Return whether the method assigns respondents to segments.

    Args:
        method: Method name.

    Returns:
        True for k-means and the other segmentation procedures.
    """
    return family(method) is not None


def nominal_columns(variables: list[dict[str, Any]], names: list[str]) -> list[str]:
    """Return named columns Gower should treat as nominal.

    A consecutive code run of length 4 or more stays numeric, which keeps an
    agreement scale on its order. A top or bottom box is numeric.

    Args:
        variables: Variable dictionary.
        names: Columns the step uses.

    Returns:
        Nominal column names.
    """
    by_name = {str(item.get("name") or ""): item for item in variables}
    nominal: list[str] = []
    for name in names:
        if "__top" in name or "__bottom" in name:
            continue
        labels = (by_name.get(name) or {}).get("value_labels") or {}
        if not labels:
            continue
        codes: list[int] = []
        blocked = False
        for key in labels:
            try:
                codes.append(int(float(key)))
            except (TypeError, ValueError):
                blocked = True
                break
        if blocked or not codes:
            nominal.append(name)
            continue
        ordered = sorted(set(codes))
        consecutive = ordered[-1] - ordered[0] + 1 == len(ordered)
        if not (consecutive and len(ordered) >= 4):
            nominal.append(name)
    return nominal


def partition(
    data: pd.DataFrame,
    method: str,
    k: int,
    seed: int,
    categorical: set[str],
) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    """Fit one segmentation procedure.

    Args:
        data: Complete numeric features.
        method: Method name.
        k: Requested segment count. DBSCAN ignores it.
        seed: Random seed.
        categorical: Nominal columns for Gower distance.

    Returns:
        Labels aligned to ``data``, metrics, and warnings.

    Raises:
        AppError: k is illegal or the procedure finds no segments.
    """
    kind = family(method) or ""
    if kind != "dbscan" and (k < 2 or k >= len(data)):
        raise AppError(
            "Clustering k must be at least 2 and smaller than the valid sample.",
            "bad_plan",
        )
    if kind == "pam_gower":
        return pam(data, k, seed, categorical)
    if kind == "hierarchical":
        return hierarchical(data, normalize_method(method), k, categorical)
    if kind == "dbscan":
        return dbscan(data, seed)
    if kind == "gaussian_mixture":
        return mixture(data, k, seed)
    if kind == "spectral":
        return spectral(data, k, seed)
    raise AppError(
        f"'{method}' has no implementation, so no result was published.",
        "unsupported_method",
    )


def run_extension(frame: pd.DataFrame, plan: AnalysisPlan) -> AnalysisResult | None:
    """Run a procedure that is not one of the original registered names.

    Args:
        frame: Source data.
        plan: Plan. ``options.procedure`` holds a supplied ``compute`` function.
            ``options.categorical`` lists nominal columns.

    Returns:
        Computed result, or None when this module does not own the method.
    """
    kind = family(plan.method)
    source = str(plan.options.get("procedure") or "")
    if kind == "kmeans" and normalize_method(plan.method) != "clustering":
        return run_clustering(frame, plan)
    if kind in {"pam_gower", "hierarchical", "dbscan", "gaussian_mixture", "spectral"}:
        return _finish_partition(frame, plan, kind)
    if source.strip():
        return _finish_custom(frame, plan, source)
    return None


def _finish_partition(frame: pd.DataFrame, plan: AnalysisPlan, kind: str) -> AnalysisResult:
    """Prepare features and store a segmentation result.

    Args:
        frame: Source data.
        plan: Analysis plan.
        kind: Procedure family.

    Returns:
        Analysis result. The method name is the one the plan asked for.
    """
    data, flow, notes = prepare_clustering(frame, plan)
    categorical = set(plan.options.get("categorical") or [])
    k = int(plan.options.get("k") or (0 if kind == "dbscan" else 2))
    labels, metrics, warnings = partition(data, plan.method, k, plan.random_seed, categorical)
    if categorical and kind == "pam_gower":
        warnings.append("Gower used mismatch distance for: " + ", ".join(sorted(categorical)) + ".")
    return _result(plan, flow, data, labels, metrics, [*notes, *warnings])


def _finish_custom(frame: pd.DataFrame, plan: AnalysisPlan, source: str) -> AnalysisResult:
    """Run a supplied function on the prepared columns.

    Args:
        frame: Source data.
        plan: Analysis plan.
        source: Procedure source.

    Returns:
        Analysis result built from the returned dictionary.
    """
    data, flow, notes = _custom_frame(frame, plan)
    returned = run_procedure(source, data, plan.random_seed)
    labels = returned.get("labels")
    parsed: np.ndarray | None = None
    if labels is not None:
        parsed = np.array([int(value) for value in labels], dtype=int)
        if len(parsed) != len(data):
            raise AppError(
                "The procedure returned a label count that does not match the valid sample.",
                "bad_plan",
            )
    estimates = dict(returned.get("estimates") or {})
    metrics = _plain_metrics(dict(returned.get("metrics") or {}))
    warnings = [str(item) for item in (returned.get("warnings") or [])]
    warnings.append(
        "This procedure was supplied for this run and executed on the prepared columns."
    )
    return _result(plan, flow, data, parsed, metrics, [*notes, *warnings], estimates=estimates)


def _custom_frame(
    frame: pd.DataFrame, plan: AnalysisPlan
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    """Return the columns a supplied procedure is allowed to see.

    Args:
        frame: Source data.
        plan: Analysis plan.

    Returns:
        Complete numeric frame, sample flow, and notes.

    Raises:
        AppError: The plan names no usable columns.
    """
    if len(plan.variables) >= 2:
        return prepare_clustering(frame, plan)
    names: list[str] = []
    if plan.dependent and plan.dependent.name:
        names.append(plan.dependent.name)
    names.extend(plan.predictors)
    for name in (plan.group, plan.var_a, plan.var_b):
        if name:
            names.append(name)
    names.extend(plan.variables)
    ordered = list(dict.fromkeys(names))
    if not ordered:
        raise AppError("The procedure needs the columns it should use.", "bad_plan")
    missing = [name for name in ordered if name not in frame.columns]
    if missing:
        raise AppError(
            f"These variables are not in the dataset: {', '.join(missing)}",
            "missing_variable",
        )
    subset = frame[ordered].apply(pd.to_numeric, errors="coerce")
    valid = subset.notna().all(axis=1)
    if int(valid.sum()) < 3:
        raise AppError(
            "Fewer than 3 complete rows remain after the filter and listwise deletion.",
            "small_sample",
        )
    flow = {
        "input_n": int(len(frame)),
        "filtered_n": int(len(frame)),
        "valid_n": int(valid.sum()),
        "exclusion_reason_counts": {"listwise_missing": int((~valid).sum())},
    }
    return subset.loc[valid].astype(float), flow, []


def _result(
    plan: AnalysisPlan,
    flow: dict[str, Any],
    data: pd.DataFrame,
    labels: np.ndarray | None,
    metrics: dict[str, Any],
    warnings: list[str],
    estimates: dict[str, Any] | None = None,
) -> AnalysisResult:
    """Build a result, adding segment sizes when labels exist.

    Args:
        plan: Analysis plan.
        flow: Sample flow.
        data: Prepared rows.
        labels: Segment labels, or None.
        metrics: Numeric metrics.
        warnings: Warnings.
        estimates: Estimates already returned by a supplied procedure.

    Returns:
        Analysis result.
    """
    body = dict(estimates or {})
    descriptive: dict[str, Any] = {}
    if labels is not None:
        listed = [int(value) for value in labels]
        descriptive["labels"] = listed
        body.setdefault("sizes", _sizes(listed))
        body.setdefault("profiles", _profiles(data, labels))
    return AnalysisResult(
        method=plan.method,
        sample_flow=flow,
        model_estimates=body,
        metrics=metrics,
        descriptive=descriptive,
        warnings=[item for item in warnings if item],
        software_versions=versions(),
        seed=plan.random_seed,
        script=script_for(plan),
    )


def _sizes(labels: list[int]) -> dict[str, int]:
    """Count respondents in each segment.

    Args:
        labels: Segment labels.

    Returns:
        Size by label.
    """
    counts: dict[str, int] = {}
    for label in labels:
        key = str(label)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _profiles(data: pd.DataFrame, labels: np.ndarray) -> dict[str, dict[str, float]]:
    """Return the mean of each feature inside each segment.

    Args:
        data: Prepared features.
        labels: Segment labels.

    Returns:
        Means keyed by segment.
    """
    profiles: dict[str, dict[str, float]] = {}
    for cluster in sorted(set(labels.tolist())):
        mask = labels == cluster
        profiles[str(cluster)] = {
            name: float(data.iloc[mask][name].mean()) for name in data.columns
        }
    return profiles


def _plain_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Keep numeric metrics and drop anything a claim cannot cite.

    Args:
        metrics: Values returned by a supplied procedure.

    Returns:
        JSON-safe numeric metrics.
    """
    plain: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            plain[str(key)] = float(value)
        elif isinstance(value, dict):
            nested = _plain_metrics(value)
            if nested:
                plain[str(key)] = nested
    return plain
