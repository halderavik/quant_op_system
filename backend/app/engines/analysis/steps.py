"""Preparation steps for a multi-step analysis plan.

These functions change a copy of the frame. They record what they changed
and leave observed answers alone.
"""

from typing import Any

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.engines.analysis.common import prepare_clustering
from app.engines.analysis.procedures import family, is_segmentation, normalize_method, partition
from app.engines.derived import in_codes
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan, AnalysisStep, AnalysisWorkflow


def mask_user_missing(frame: pd.DataFrame, variables: list[dict[str, Any]]) -> pd.DataFrame:
    """Replace user-missing codes with nulls on a copy of the frame.

    Args:
        frame: Respondent data.
        variables: Variable dictionary, including user-missing codes.

    Returns:
        Copy with those codes set to null. Other values are unchanged.
    """
    out = frame.copy()
    for item in variables:
        name = str(item.get("name") or "")
        missing = list(item.get("user_missing_values") or [])
        if not name or name not in out.columns or not missing:
            continue
        mask = in_codes(out[name], missing)
        if bool(mask.any()):
            out.loc[mask, name] = pd.NA
    return out


def impute_missing(
    frame: pd.DataFrame, variables: list[str], strategy: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Fill nulls with the median or the mode. Observed values stay as they are.

    Args:
        frame: Working data.
        variables: Columns to fill.
        strategy: ``median`` or ``mode``.

    Returns:
        Updated frame and one log row per column.

    Raises:
        AppError: A column is missing or has no observed value to copy.
    """
    out = frame.copy()
    chosen = strategy if strategy in {"median", "mode"} else "median"
    log: list[dict[str, Any]] = []
    for name in variables:
        if name not in out.columns:
            raise AppError(f"'{name}' is not in the dataset.", "missing_variable")
        series = pd.to_numeric(out[name], errors="coerce")
        observed = series.dropna()
        if observed.empty:
            raise AppError(
                f"'{name}' has no observed values, so it cannot be imputed.",
                "small_sample",
            )
        fill = float(observed.mode().iloc[0]) if chosen == "mode" else float(observed.median())
        missing = series.isna()
        filled = series.copy()
        filled.loc[missing] = fill
        out[name] = filled
        log.append(
            {
                "variable": name,
                "strategy": chosen,
                "filled": int(missing.sum()),
                "fill_value": fill,
            }
        )
    return out, log


def apply_box(
    frame: pd.DataFrame,
    variables: list[str],
    *,
    box: int,
    high: bool,
    codes: list[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, str]]:
    """Recode each column to 1 when the answer is inside the box, else 0.

    Args:
        frame: Working data.
        variables: Source columns.
        box: How many scale points form the box.
        high: True for the top box, false for the bottom box.
        codes: Explicit codes, applied to every column. Empty means the
            favorable end of the observed numeric scale.

    Returns:
        Frame with new 0/1 columns, a recode log, and a map from source to output.

    Raises:
        AppError: A column is missing or has fewer than two observed codes.
    """
    out = frame.copy()
    log: list[dict[str, Any]] = []
    alias: dict[str, str] = {}
    width = box if box >= 1 else 2
    label = "top" if high else "bottom"
    for name in variables:
        if name not in out.columns:
            raise AppError(f"'{name}' is not in the dataset.", "missing_variable")
        series = pd.to_numeric(out[name], errors="coerce")
        selected = _box_codes(series, width, high, codes)
        output = _output_name(out, name, label, width)
        coded = pd.Series(pd.NA, index=out.index, dtype="Float64")
        known = series.notna()
        hit = in_codes(series, selected)
        coded.loc[known] = 0
        coded.loc[known & hit] = 1
        out[output] = coded.astype(float)
        observed = sorted({int(value) for value in out[output].dropna().unique()})
        alias[name] = output
        log.append(
            {
                "variable": name,
                "output": output,
                "rule": label,
                "box": width,
                "codes": selected,
                "values": observed,
            }
        )
    return out, log, alias


def choose_k(frame: pd.DataFrame, plan: AnalysisPlan) -> tuple[int, dict[str, float]]:
    """Pick k from 2 through 6 by the highest silhouette.

    Args:
        frame: Working data, already imputed and recoded.
        plan: Clustering plan. ``options.k`` is ignored.

    Returns:
        Chosen k and the silhouette at each k that was tried.

    Raises:
        AppError: Fewer than three complete rows remain.
    """
    data, _, _ = prepare_clustering(frame, plan)
    kind = family(plan.method)
    upper = min(6, len(data) - 1)
    if upper < 2:
        raise AppError(
            "Clustering needs at least three complete rows before k can be chosen.",
            "small_sample",
        )
    if kind in {None, "kmeans"}:
        return _kmeans_k(data, plan.random_seed, upper)
    categorical = set(plan.options.get("categorical") or [])
    scores: dict[str, float] = {}
    best_k = 2
    best_score = -1.0
    for k in range(2, upper + 1):
        _labels, metrics, _notes = partition(data, plan.method, k, plan.random_seed, categorical)
        score = metrics.get("silhouette")
        if score is None:
            continue
        scores[str(k)] = float(score)
        if float(score) > best_score:
            best_k = k
            best_score = float(score)
    if not scores:
        raise AppError(
            "Silhouette could not be computed for this segmentation.",
            "small_sample",
        )
    return best_k, scores


def _kmeans_k(data: pd.DataFrame, seed: int, upper: int) -> tuple[int, dict[str, float]]:
    """Pick k for k-means by silhouette on standardized features.

    Args:
        data: Complete numeric features.
        seed: Random seed.
        upper: Largest k to try.

    Returns:
        Chosen k and the silhouette at each k.
    """
    scaled = StandardScaler().fit_transform(data)
    scores: dict[str, float] = {}
    best_k = 2
    best_score = -1.0
    for k in range(2, upper + 1):
        labels = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(scaled)
        score = float(silhouette_score(scaled, labels))
        scores[str(k)] = score
        if score > best_score:
            best_k = k
            best_score = score
    return best_k, scores


def listwise_count(frame: pd.DataFrame, variables: list[str]) -> dict[str, Any]:
    """Count rows that are incomplete on the named columns.

    Args:
        frame: Working data.
        variables: Columns the later method will require.

    Returns:
        Incomplete-row count. This step does not drop rows.
    """
    present = [name for name in variables if name in frame.columns]
    if not present:
        return {"incomplete_rows": 0, "variables": []}
    numeric = frame[present].apply(pd.to_numeric, errors="coerce")
    incomplete = int((~numeric.notna().all(axis=1)).sum())
    return {"incomplete_rows": incomplete, "variables": present}


def rewrite_step(step: AnalysisStep, alias: dict[str, str]) -> AnalysisStep:
    """Point a step at recoded columns when the source was recoded.

    Args:
        step: Plan step.
        alias: Source name to output column.

    Returns:
        Copy of the step with names substituted.
    """

    def _one(name: str) -> str:
        return alias.get(name, name) if name else ""

    return step.model_copy(
        update={
            "variables": [_one(name) for name in step.variables],
            "predictors": [_one(name) for name in step.predictors],
            "dependent": _one(step.dependent),
            "group": _one(step.group),
            "var_a": _one(step.var_a),
            "var_b": _one(step.var_b),
        }
    )


def clustering_plan(
    workflow: AnalysisWorkflow, step: AnalysisStep, nominal: list[str] | None = None
) -> AnalysisPlan:
    """Build the plan ``prepare_clustering`` expects.

    Args:
        workflow: Parent workflow. Supplies the seed and the segmentation method.
        step: Clustering or choose-k step, after recode substitution.
        nominal: Columns Gower should treat as nominal.

    Returns:
        Analysis plan whose variables are the feature columns.
    """
    method = normalize_method(step.method) if is_segmentation(step.method) else ""
    if not method:
        method = _segmentation_method(workflow)
    options: dict[str, Any] = {}
    if step.k:
        options["k"] = step.k
    if nominal:
        options["categorical"] = list(nominal)
    return AnalysisPlan(
        analysis_id=workflow.analysis_id or "analysis",
        method=method,
        variables=list(step.variables),
        random_seed=workflow.random_seed,
        options=options,
    )


def _segmentation_method(workflow: AnalysisWorkflow) -> str:
    """Return the segmentation method named on the workflow.

    Args:
        workflow: Plan.

    Returns:
        Normalized method name, or ``clustering`` when the plan uses k-means.
    """
    for item in workflow.steps:
        if item.kind == "method" and is_segmentation(item.method):
            return normalize_method(item.method)
    return "clustering"


def _box_codes(series: pd.Series, box: int, high: bool, codes: list[str] | None) -> list[float]:
    """Return the codes that count as the box.

    Args:
        series: Numeric column.
        box: Box width.
        high: True to take the highest codes.
        codes: Explicit codes. Empty selects them from the observed scale.

    Returns:
        Codes as floats.

    Raises:
        AppError: The column does not have two observed codes.
    """
    if codes:
        parsed: list[float] = []
        for code in codes:
            try:
                parsed.append(float(code))
            except (TypeError, ValueError):
                continue
        if parsed:
            return parsed
    observed = sorted({float(value) for value in series.dropna().unique()})
    if len(observed) < 2:
        raise AppError(
            "A top or bottom box needs a scale with at least two observed codes.",
            "bad_plan",
        )
    width = min(box, len(observed))
    chosen = observed[-width:] if high else observed[:width]
    return chosen


def _output_name(frame: pd.DataFrame, source: str, label: str, box: int) -> str:
    """Return a new column name that does not collide with the frame.

    Args:
        frame: Working data.
        source: Source variable.
        label: ``top`` or ``bottom``.
        box: Box width.

    Returns:
        Output column name.
    """
    base = f"{source}__{label}{box}"
    name = base
    suffix = 2
    while name in frame.columns:
        name = f"{base}_{suffix}"
        suffix += 1
    return name
