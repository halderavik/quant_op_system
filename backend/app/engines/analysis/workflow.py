"""Run a validated analysis workflow and return a JSON-ready result."""

from typing import Any

import pandas as pd

from app.engines.analysis.common import prepare_clustering, versions
from app.engines.analysis.procedures import family, is_segmentation, nominal_columns
from app.engines.analysis.registry import run_plan
from app.engines.analysis.steps import (
    apply_box,
    choose_k,
    clustering_plan,
    impute_missing,
    listwise_count,
    mask_user_missing,
    rewrite_step,
)
from app.engines.crosstab import run_table
from app.errors import AppError
from app.schemas.analysis import (
    AnalysisPlan,
    AnalysisResult,
    AnalysisStep,
    AnalysisWorkflow,
    VariableRole,
)
from app.schemas.tabspec import Banner, BannerCategory, StudyDefaults, TableSpec


def execute_workflow(
    frame: pd.DataFrame, workflow: AnalysisWorkflow, variables: list[dict[str, Any]]
) -> dict[str, Any]:
    """Run each step in order and return the computed payload.

    Args:
        frame: Respondent data. This function copies it.
        workflow: Plan written before the run.
        variables: Variable dictionary used for missing codes and labels.

    Returns:
        Result dictionary, including the workflow with a chosen k filled in.

    Raises:
        AppError: A step cannot be computed.
    """
    working = mask_user_missing(frame, variables)
    resolved = workflow.model_copy(deep=True)
    alias: dict[str, str] = {}
    step_logs: list[dict[str, Any]] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    method_result: AnalysisResult | None = None
    profile_tables: list[dict[str, Any]] = []
    chosen: dict[str, Any] = {}
    steps: list[AnalysisStep] = []

    for step in resolved.steps:
        current = rewrite_step(step, alias)
        if current.kind == "impute_missing":
            working, log = impute_missing(working, current.variables, current.strategy or "median")
            _remember_impute(metrics, warnings, log)
            step_logs.append(_log(current, {"columns": log}))
        elif current.kind in {"top_box", "bottom_box"}:
            working, log, created = apply_box(
                working,
                current.variables,
                box=current.box or 2,
                high=current.kind == "top_box",
                codes=current.codes,
            )
            alias.update(created)
            step_logs.append(_log(current, {"columns": log}))
        elif current.kind == "listwise":
            detail = listwise_count(working, current.variables)
            step_logs.append(_log(current, detail))
        elif current.kind == "choose_k":
            features = current.variables or _cluster_features(resolved, alias)
            plan = clustering_plan(
                resolved,
                current.model_copy(update={"variables": features}),
                nominal_columns(variables, features),
            )
            k, scores = choose_k(working, plan)
            chosen = {"k": k, "silhouette_by_k": scores}
            current = current.model_copy(update={"k": k})
            warnings.append(f"Silhouette chose k={k}.")
            step_logs.append(_log(current, chosen))
        elif current.kind == "method":
            current, method_result, extra = _run_method(
                working, resolved, current, chosen, variables
            )
            warnings.extend(extra)
            labels = (method_result.descriptive or {}).get("labels") if method_result else None
            if labels and (is_segmentation(current.method) or current.procedure):
                working = _attach_segment(working, resolved, current, method_result)
            step_logs.append(_log(current, {"method": current.method, "k": current.k}))
        elif current.kind == "profile_crosstab":
            profile_tables = _profile(working, current, variables, resolved.weight_variable)
            _remember_profile(metrics, profile_tables)
            step_logs.append(_log(current, {"tables": len(profile_tables)}))
        elif current.kind == "report":
            step_logs.append(_log(current, {"status": "summary written from computed fields"}))
        if current.kind == "method":
            saved = step.model_copy(update={"method": current.method, "k": current.k or step.k})
        elif current.k and step.k != current.k:
            saved = step.model_copy(update={"k": current.k})
        else:
            saved = step
        steps.append(saved)

    if method_result is None:
        raise AppError("The plan needs one analysis method.", "bad_plan")
    resolved = resolved.model_copy(update={"steps": steps})
    estimates = dict(method_result.model_estimates)
    metrics = {**dict(method_result.metrics), **metrics}
    if chosen:
        metrics["k"] = chosen["k"]
    descriptive = dict(method_result.descriptive)
    descriptive.pop("labels", None)
    payload = {
        "method": method_result.method,
        "sample_flow": method_result.sample_flow,
        "model_estimates": estimates,
        "metrics": metrics,
        "diagnostics": {
            "steps": step_logs,
            "profile_tables": profile_tables,
            "chosen_k": chosen,
        },
        "warnings": list(method_result.warnings) + warnings,
        "descriptive": descriptive,
        "software_versions": versions(),
        "seed": workflow.random_seed,
        "resolved_workflow": resolved.model_dump(mode="json"),
    }
    return _jsonable(payload)


def _run_method(
    frame: pd.DataFrame,
    workflow: AnalysisWorkflow,
    step: AnalysisStep,
    chosen: dict[str, Any],
    variables: list[dict[str, Any]],
) -> tuple[AnalysisStep, AnalysisResult, list[str]]:
    """Execute the planned method on the prepared frame.

    Args:
        frame: Working data.
        workflow: Parent workflow.
        step: Method step after recode substitution.
        chosen: Silhouette choice, when a choose_k step already ran.
        variables: Variable dictionary, used to tell nominal columns from scales.

    Returns:
        The step with k filled in, the method result, and extra warnings.
    """
    notes: list[str] = []
    method = step.method.strip().lower().replace(" ", "_").replace("-", "_")
    step = step.model_copy(update={"method": method})
    if is_segmentation(step.method) and family(step.method) != "dbscan" and not step.k:
        if chosen.get("k"):
            step = step.model_copy(update={"k": int(chosen["k"])})
        else:
            plan = clustering_plan(workflow, step, nominal_columns(variables, step.variables))
            k, scores = choose_k(frame, plan)
            step = step.model_copy(update={"k": k})
            chosen["k"] = k
            chosen["silhouette_by_k"] = scores
            notes.append(f"Silhouette chose k={k}.")
    weight = workflow.weight_variable or None
    dependent = step.dependent or None
    options: dict[str, Any] = {"k": step.k} if step.k else {}
    if step.procedure.strip():
        options["procedure"] = step.procedure
    nominal = nominal_columns(variables, step.variables)
    if nominal:
        options["categorical"] = nominal
    plan = AnalysisPlan(
        analysis_id=workflow.analysis_id or "analysis",
        method=step.method,
        variables=list(step.variables),
        predictors=list(step.predictors),
        dependent=VariableRole(name=dependent, role="dependent") if dependent else None,
        group=step.group or None,
        var_a=step.var_a or None,
        var_b=step.var_b or None,
        weight_variable=weight,
        random_seed=workflow.random_seed,
        options=options,
    )
    return step, run_plan(frame, plan), notes


def _attach_segment(
    frame: pd.DataFrame,
    workflow: AnalysisWorkflow,
    step: AnalysisStep,
    result: AnalysisResult,
) -> pd.DataFrame:
    """Write cluster labels onto the rows that entered k-means.

    Args:
        frame: Working data.
        workflow: Parent workflow.
        step: Clustering step.
        result: Clustering result. Labels follow the prepared row order.

    Returns:
        Frame with a ``segment`` column.
    """
    data, _, _ = prepare_clustering(frame, clustering_plan(workflow, step))
    labels = [int(value) for value in result.descriptive.get("labels") or []]
    out = frame.copy()
    out["segment"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    if len(labels) == len(data):
        out.loc[data.index, "segment"] = labels
    return out


def _profile(
    frame: pd.DataFrame,
    step: AnalysisStep,
    variables: list[dict[str, Any]],
    weight: str,
) -> list[dict[str, Any]]:
    """Cross the segment against each profiling variable.

    Args:
        frame: Working data including ``segment``.
        step: Profile step. ``variables`` are the profilers.
        variables: Variable dictionary.
        weight: Weight variable, or empty.

    Returns:
        One table dictionary per profiler.

    Raises:
        AppError: Clustering did not write a segment.
    """
    if "segment" not in frame.columns or not bool(frame["segment"].notna().any()):
        raise AppError("A profile cross-tab needs a clustering step before it.", "bad_plan")
    clustered = frame.loc[frame["segment"].notna()].copy()
    present = sorted({int(value) for value in clustered["segment"].dropna().unique()})
    banner = Banner(
        id="segment",
        label="Segment",
        variable_name="segment",
        categories=[
            BannerCategory(label=f"Segment {label}", codes=[label], order=index)
            for index, label in enumerate(present)
        ],
        include_total=True,
    )
    meta = list(variables) + [
        {
            "name": "segment",
            "label": "Segment",
            "value_labels": {str(label): f"Segment {label}" for label in present},
            "user_missing_values": [],
        }
    ]
    by_name = {str(item.get("name")): item for item in meta}
    tables: list[dict[str, Any]] = []
    for name in step.variables:
        info = by_name.get(name, {"name": name, "value_labels": {}, "user_missing_values": []})
        kind = "categorical" if _categorical(clustered[name], info) else "numeric"
        table = TableSpec(
            id=f"profile-{name}",
            title=f"{name} by segment",
            row_variable_names=[name],
            table_type=kind,
            banner_ids=["segment"],
            weight_variable=weight or None,
            statistics=["unweighted_base", "column_pct" if kind == "categorical" else "mean"],
        )
        computed = run_table(
            clustered,
            meta,
            table,
            StudyDefaults(weight_variable=weight or None),
            [banner],
        )
        tables.append(_table_dump(name, kind, computed.columns, computed.rows))
    return tables


def _categorical(series: pd.Series, info: dict[str, Any]) -> bool:
    """Return whether a profiler should be shown as column percentages.

    Args:
        series: Column.
        info: Variable dictionary entry.

    Returns:
        True when the column has value labels or few distinct numbers.
    """
    if info.get("value_labels"):
        return True
    numeric = pd.to_numeric(series, errors="coerce")
    return int(numeric.dropna().nunique()) <= 8


def _table_dump(name: str, kind: str, columns: list[Any], rows: list[Any]) -> dict[str, Any]:
    """Convert a computed table into plain values.

    Args:
        name: Profiler name.
        kind: ``categorical`` or ``numeric``.
        columns: Table columns.
        rows: Table rows.

    Returns:
        JSON-ready table.
    """
    dumped_rows = []
    for row in rows:
        values: dict[str, Any] = {}
        bases: dict[str, Any] = {}
        for column in columns:
            cell = row.cells.get(column.id)
            if cell is None:
                continue
            values[column.label] = cell.estimate
            bases[column.label] = cell.unweighted_base
        dumped_rows.append(
            {"label": row.label, "kind": row.row_kind, "values": values, "bases": bases}
        )
    return {
        "variable": name,
        "kind": kind,
        "columns": [column.label for column in columns],
        "rows": dumped_rows,
    }


def _cluster_features(workflow: AnalysisWorkflow, alias: dict[str, str]) -> list[str]:
    """Return the clustering features, after recode substitution.

    Args:
        workflow: Plan.
        alias: Recode map.

    Returns:
        Feature names.
    """
    for step in workflow.steps:
        if step.kind == "method" and is_segmentation(step.method):
            return [alias.get(name, name) for name in step.variables]
    return []


def _remember_impute(
    metrics: dict[str, Any], warnings: list[str], log: list[dict[str, Any]]
) -> None:
    """Copy fill counts into metrics and warnings.

    Args:
        metrics: Metric dictionary to update.
        warnings: Warning list to update.
        log: Imputation log.
    """
    for item in log:
        key = f"imputed_{_key(str(item['variable']))}"
        metrics[key] = int(item["filled"])
        warnings.append(
            f"Filled {item['filled']} missing values on {item['variable']} "
            f"with the {item['strategy']} {item['fill_value']}."
        )


def _remember_profile(metrics: dict[str, Any], tables: list[dict[str, Any]]) -> None:
    """Copy a bounded set of profile cells into metrics so the report can cite them.

    Args:
        metrics: Metric dictionary to update.
        tables: Profile tables.
    """
    added = 0
    for table in tables:
        for row in table["rows"]:
            for column, value in row["values"].items():
                if column == "Total" or value is None or added >= 24:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                key = _key(f"profile_{table['variable']}_{row['label']}_{column}")
                metrics[key] = float(value)
                added += 1


def _log(step: AnalysisStep, detail: dict[str, Any]) -> dict[str, Any]:
    """Build one step record for the diagnostics.

    Args:
        step: Step that ran.
        detail: Computed detail.

    Returns:
        Step record.
    """
    return {
        "step_id": step.step_id,
        "kind": step.kind,
        "reason": step.reason,
        "variables": list(step.variables),
        "detail": detail,
    }


def _key(text: str) -> str:
    """Return a metric name with no spaces or dots.

    Args:
        text: Raw label.

    Returns:
        Safe key.
    """
    cleaned = "".join(character if character.isalnum() else "_" for character in text)
    return cleaned.strip("_") or "value"


def _jsonable(value: Any) -> Any:
    """Convert numpy values so ``json.dumps`` can write the result.

    Args:
        value: Nested result.

    Returns:
        Plain Python value.
    """
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, float) and value != value:
        return None
    return value
