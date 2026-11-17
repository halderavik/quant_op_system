"""Market research guardrails: fix a plan before it runs and review results after.

``apply_standards`` changes the plan the planner wrote where a research
standard is not a matter of choice, and records each change on the plan.
``review_runs`` reads every method fit and returns pass or flag checks that
go into the result, the warnings, and the workbook.
"""

import re
from collections import Counter
from typing import Any

from app.engines.analysis import standards as std
from app.schemas.analysis import AnalysisResult, AnalysisStep, AnalysisWorkflow

_DRIVER = re.compile(
    r"\bdrivers?\b|\bwhat drives\b|\bdriving\b|\bimportance\b|\bkey factors?\b|\bimpact (?:on|of)\b",
    re.I,
)
_ASKS_REGRESSION = re.compile(r"\bregress|\bcoefficients?\b|\bbetas?\b", re.I)
_UNWEIGHTED = re.compile(r"\bunweighted\b|\bno weight|\bwithout weight", re.I)
_WEIGHTED = {"linear_regression", "binary_logistic_regression"}
_REGRESSIONS = {"linear_regression", "binary_logistic_regression", "ordinal_regression"}


def apply_standards(
    workflow: AnalysisWorkflow, request: str, columns: set[str]
) -> AnalysisWorkflow:
    """Return a copy of the plan with the research standards applied.

    Args:
        workflow: Planner or keyword plan.
        request: User text, used to tell a driver request from a regression request.
        columns: Dataset column names.

    Returns:
        Plan with ``standards`` listing what was applied or noticed.
    """
    if workflow.status != "ready" or not workflow.steps:
        return workflow.model_copy(update={"standards": []})
    from app.engines.analysis.compile import canonical_method
    from app.engines.analysis.procedures import family, is_segmentation
    from app.engines.tabspec_banners import is_weight_name

    notes: list[str] = []
    steps: list[AnalysisStep] = []
    segmented = False
    for step in workflow.steps:
        if step.kind != "method":
            steps.append(step)
            continue
        method = canonical_method(step.method)
        if (
            method == "linear_regression"
            and _DRIVER.search(request)
            and not _ASKS_REGRESSION.search(request)
            and not step.output
        ):
            step = step.model_copy(update={"method": "key_driver"})
            notes.append(
                f"Step {step.step_id} asks for drivers, so it runs as a key driver analysis "
                "with an importance ranking instead of a plain regression."
            )
        if is_segmentation(method) and family(method) != "dbscan":
            segmented = True
            step = _segment_range(step, notes)
        steps.append(step)
    if segmented and not any(step.kind == "profile_crosstab" for step in steps):
        notes.append(
            "The plan has no profile step, so segments are described only by their features. "
            "Ask for a profile by demographics or key measures to describe them."
        )
    if steps[-1].kind != "report":
        steps.append(AnalysisStep(step_id="report", kind="report", reason="Write the summary."))
    weights = sorted(name for name in columns if is_weight_name(name))
    if not workflow.weight_variable and weights and not _UNWEIGHTED.search(request):
        notes.append(
            f"The dataset has {', '.join(weights)}, but this plan is unweighted. "
            "Ask for a weighted run if the results should match weighted tables."
        )
    return workflow.model_copy(update={"steps": steps, "standards": list(dict.fromkeys(notes))})


def _segment_range(step: AnalysisStep, notes: list[str]) -> AnalysisStep:
    """Set the 4-8 segment search unless the user fixed k or a range."""
    if step.k:
        if not std.SEGMENT_K_MIN <= step.k <= std.SEGMENT_K_MAX:
            notes.append(
                f"k={step.k} was requested, outside the {std.SEGMENT_K_MIN}-"
                f"{std.SEGMENT_K_MAX} segment standard. It was kept because it was asked for."
            )
        return step
    if step.k_min or step.k_max:
        return step
    notes.append(f"Step {step.step_id} tests {std.SEGMENT_K_MIN} to {std.SEGMENT_K_MAX} segments.")
    return step.model_copy(update={"k_min": std.SEGMENT_K_MIN, "k_max": std.SEGMENT_K_MAX})


def review_runs(runs: list[Any], chosen: dict[str, Any], weight: str = "") -> list[dict[str, Any]]:
    """Check every method fit against the research standards.

    Args:
        runs: ``MethodRun`` objects with ``step``, ``group``, and ``result``.
        chosen: Segment-count choice, including the range and smallest shares tried.
        weight: Plan weight variable, if any.

    Returns:
        Checks with area, check, status (pass or flag), and detail.
    """
    from app.engines.analysis.compile import canonical_method
    from app.engines.analysis.procedures import family, is_segmentation

    checks: list[dict[str, Any]] = []
    for run in runs:
        method = canonical_method(run.result.method or run.step.method)
        area = method.replace("_", " ") + (f" ({run.group})" if run.group else "")
        result: AnalysisResult = run.result
        n = int(result.sample_flow.get("valid_n") or 0)
        checks.append(_base(area, "Base size", n))
        if weight and method not in _WEIGHTED:
            checks.append(
                _check(
                    area,
                    "Weighting",
                    False,
                    f"{weight} is not applied by this method, so these results are unweighted.",
                )
            )
        if is_segmentation(method) and family(method) != "dbscan":
            checks.extend(_segments(area, run.step, result, n, chosen))
        elif method == "key_driver":
            checks.extend(_drivers(area, run.step, result, n))
        elif method in _REGRESSIONS:
            checks.extend(_model_size(area, run.step, result, n))
        elif method in {"efa", "pca"}:
            checks.extend(_factors(area, result))
        elif method == "chi_square":
            checks.extend(_chi_square(area, result))
        elif method in {"t_test", "anova"}:
            checks.extend(_groups(area, method, result))
    return checks


def flag_warnings(checks: list[dict[str, Any]]) -> list[str]:
    """Return one warning per flagged check."""
    return [f"{item['area']}: {item['detail']}" for item in checks if item["status"] == "flag"]


def _check(area: str, name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"area": area, "check": name, "status": "pass" if ok else "flag", "detail": detail}


def _base(area: str, name: str, n: int) -> dict[str, Any]:
    """Classify a base against the reporting minimums."""
    if n < std.MIN_BASE:
        return _check(
            area, name, False, f"Base of {n} is under {std.MIN_BASE}; too small to report."
        )
    if n < std.LOW_BASE:
        return _check(
            area, name, False, f"Base of {n} is under {std.LOW_BASE}; treat as directional."
        )
    return _check(area, name, True, f"Base of {n}.")


def _segments(
    area: str, step: AnalysisStep, result: AnalysisResult, n: int, chosen: dict[str, Any]
) -> list[dict[str, Any]]:
    """Segment count range, smallest segment, and separation."""
    checks: list[dict[str, Any]] = []
    tested = chosen.get("tested") or []
    k = int(step.k or chosen.get("k") or 0)
    if tested:
        checks.append(
            _check(
                area,
                "Segment range",
                True,
                f"Tested k={tested[0]}-{tested[-1]}; k={k} was chosen.",
            )
        )
    else:
        inside = std.SEGMENT_K_MIN <= k <= std.SEGMENT_K_MAX
        checks.append(
            _check(
                area,
                "Segment range",
                inside,
                f"k={k} was set by the request"
                + (
                    "."
                    if inside
                    else f", outside the {std.SEGMENT_K_MIN}-{std.SEGMENT_K_MAX} standard."
                ),
            )
        )
    labels = [
        label for label in (result.descriptive or {}).get("labels") or [] if label is not None
    ]
    if labels:
        counts = Counter(labels)
        smallest = min(counts.values())
        share = smallest / len(labels)
        checks.append(
            _check(
                area,
                "Smallest segment",
                share >= std.MIN_SEGMENT_SHARE,
                f"Smallest segment is {smallest} respondents ({share:.1%} of {len(labels)})"
                + (
                    "."
                    if share >= std.MIN_SEGMENT_SHARE
                    else f", under {std.MIN_SEGMENT_SHARE:.0%}."
                ),
            )
        )
    silhouette = result.metrics.get("silhouette")
    if isinstance(silhouette, (int, float)):
        strong = silhouette >= std.WEAK_SILHOUETTE
        checks.append(
            _check(
                area,
                "Separation",
                strong,
                f"Silhouette {silhouette:.3f}"
                + (
                    "."
                    if strong
                    else f" is under {std.WEAK_SILHOUETTE}; segments overlap, so validate them "
                    "on the profile before using them."
                ),
            )
        )
    return checks


def _drivers(area: str, step: AnalysisStep, result: AnalysisResult, n: int) -> list[dict[str, Any]]:
    """Importance ranking, sample per driver, collinearity, and fit."""
    ranking = (result.descriptive or {}).get("importance_ranking") or []
    checks = [
        _check(
            area,
            "Importance ranking",
            bool(ranking),
            (
                f"{len(ranking)} drivers ranked; top driver {ranking[0]['driver']} "
                f"({ranking[0]['importance_pct']:.1f}% of explained variance)."
            )
            if ranking
            else "No importance ranking was produced.",
        )
    ]
    checks.extend(_model_size(area, step, result, n))
    r_squared = result.metrics.get("r_squared")
    if isinstance(r_squared, (int, float)):
        checks.append(
            _check(
                area,
                "Explained variance",
                r_squared >= std.LOW_R_SQUARED,
                f"R-squared {r_squared:.3f}"
                + (
                    "."
                    if r_squared >= std.LOW_R_SQUARED
                    else "; the drivers explain little of the outcome."
                ),
            )
        )
    return checks


def _model_size(
    area: str, step: AnalysisStep, result: AnalysisResult, n: int
) -> list[dict[str, Any]]:
    """Respondents per predictor and the largest VIF."""
    predictors = len(step.predictors) or len(
        [name for name in result.model_estimates if name != "const"]
    )
    checks: list[dict[str, Any]] = []
    if predictors:
        ratio = n / predictors
        checks.append(
            _check(
                area,
                "Respondents per predictor",
                ratio >= std.CASES_PER_PREDICTOR,
                f"{ratio:.0f} respondents per predictor"
                + (
                    "."
                    if ratio >= std.CASES_PER_PREDICTOR
                    else f", under {std.CASES_PER_PREDICTOR}."
                ),
            )
        )
    vif = result.metrics.get("vif") or {}
    if isinstance(vif, dict) and vif:
        name, worst = max(vif.items(), key=lambda item: item[1])
        high = sorted(key for key, value in vif.items() if value > std.MAX_VIF)
        checks.append(
            _check(
                area,
                "Collinearity",
                not high,
                f"Largest VIF is {worst:.2f} ({name})"
                + ("." if not high else f"; {', '.join(high)} overlap with other predictors."),
            )
        )
    return checks


def _factors(area: str, result: AnalysisResult) -> list[dict[str, Any]]:
    """KMO, Bartlett, variance explained, and weak items."""
    checks: list[dict[str, Any]] = []
    kmo = result.metrics.get("kmo")
    if isinstance(kmo, (int, float)):
        checks.append(
            _check(
                area,
                "Sampling adequacy (KMO)",
                kmo >= std.MIN_KMO,
                f"KMO {kmo:.3f}" + ("." if kmo >= std.MIN_KMO else f", under {std.MIN_KMO:g}."),
            )
        )
    bartlett = result.metrics.get("bartlett_p_value")
    if isinstance(bartlett, (int, float)):
        checks.append(
            _check(
                area,
                "Bartlett's test",
                bartlett < std.ALPHA,
                "Items correlate enough to factor."
                if bartlett < std.ALPHA
                else f"Bartlett p={bartlett:.3f}; the items may not share factors.",
            )
        )
    explained = result.metrics.get("total_variance_explained")
    if isinstance(explained, (int, float)):
        checks.append(
            _check(area, "Variance explained", True, f"{explained:.1%} of item variance explained.")
        )
    weak = result.metrics.get("weak_items") or []
    checks.append(
        _check(
            area,
            "Item loadings",
            not weak,
            f"Every item loads at least {std.MIN_LOADING:g} on a factor."
            if not weak
            else f"{', '.join(weak)} load under {std.MIN_LOADING:g} on every factor.",
        )
    )
    return checks


def _chi_square(area: str, result: AnalysisResult) -> list[dict[str, Any]]:
    """Sparse cells and effect size."""
    sparse = float(result.metrics.get("low_expected_share") or 0.0)
    checks = [
        _check(
            area,
            "Expected cell counts",
            sparse <= std.MAX_SPARSE_SHARE,
            f"{sparse:.0%} of cells expect fewer than 5"
            + (
                "."
                if sparse <= std.MAX_SPARSE_SHARE
                else "; merge small categories before reading p."
            ),
        )
    ]
    p_value = result.metrics.get("p_value")
    if isinstance(p_value, (int, float)):
        checks.append(_significance(area, p_value, result.metrics.get("cramers_v"), "Cramer's V"))
    return checks


def _groups(area: str, method: str, result: AnalysisResult) -> list[dict[str, Any]]:
    """Smallest group base and significance."""
    groups = (result.descriptive or {}).get("groups") or {}
    checks: list[dict[str, Any]] = []
    if groups:
        label, info = min(groups.items(), key=lambda item: item[1].get("n", 0))
        checks.append(_base(area, f"Smallest group ({label})", int(info.get("n", 0))))
    p_value = result.metrics.get("p_value")
    if isinstance(p_value, (int, float)):
        effect = result.metrics.get("eta_squared" if method == "anova" else "cohens_d")
        checks.append(
            _significance(
                area, p_value, effect, "eta squared" if method == "anova" else "Cohen's d"
            )
        )
    return checks


def _significance(area: str, p_value: float, effect: Any, effect_name: str) -> dict[str, Any]:
    """Report significance at the house confidence level."""
    significant = p_value < std.ALPHA
    size = f" {effect_name} {effect:.3f}." if isinstance(effect, (int, float)) else ""
    return {
        "area": area,
        "check": f"Significance at {std.CONFIDENCE:.0%}",
        "status": "pass",
        "detail": (
            f"p={p_value:.3f}: {'significant' if significant else 'not significant'} at "
            f"{std.CONFIDENCE:.0%} confidence.{size}"
        ),
    }
