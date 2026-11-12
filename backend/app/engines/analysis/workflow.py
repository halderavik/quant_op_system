"""Run a validated analysis workflow and return a JSON-ready result."""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.engines.analysis.common import prepare_clustering, versions
from app.engines.analysis.compile import canonical_method
from app.engines.analysis.procedures import family, is_segmentation, nominal_columns
from app.engines.analysis.registry import run_plan
from app.engines.analysis.steps import (
    apply_bands,
    apply_box,
    apply_filter,
    choose_k,
    clustering_plan,
    impute_missing,
    kaiser_count,
    listwise_count,
    mask_off_scale,
    mask_user_missing,
    rewrite_step,
)
from app.engines.crosstab import run_table
from app.engines.derived import in_codes
from app.errors import AppError
from app.schemas.analysis import (
    AnalysisPlan,
    AnalysisResult,
    AnalysisStep,
    AnalysisWorkflow,
    VariableRole,
)
from app.schemas.tabspec import Banner, BannerCategory, StudyDefaults, TableSpec

_MAX_GROUPS = 12
_COMPARE_ROWS = 400
_ROW_DATA = ("labels", "scores", "row_index")


@dataclass
class MethodRun:
    """One method fit: the step, the subgroup it ran on (or empty), and its result."""

    step: AnalysisStep
    group: str
    result: AnalysisResult


def execute_workflow(
    frame: pd.DataFrame, workflow: AnalysisWorkflow, variables: list[dict[str, Any]]
) -> dict[str, Any]:
    """Run each step in order and return the computed payload.

    Filters and bands change the rows and columns that later steps see.
    Every method step runs; segment labels and factor or component scores it
    saves become columns for the steps after it.

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
    working, off_scale = mask_off_scale(working, variables)
    meta = [dict(item) for item in variables]
    resolved = workflow.model_copy(deep=True)
    alias: dict[str, str] = {}
    step_logs: list[dict[str, Any]] = []
    warnings: list[str] = list(off_scale)
    metrics: dict[str, Any] = {}
    runs: list[MethodRun] = []
    comparisons: list[dict[str, Any]] = []
    profile_tables: list[dict[str, Any]] = []
    chosen: dict[str, Any] = {}
    steps: list[AnalysisStep] = []
    segment_column = ""

    for step in resolved.steps:
        current = _expand(rewrite_step(step, alias), working)
        if current.kind == "filter":
            working, detail = apply_filter(working, current)
            warnings.append(_filter_note(detail, meta))
            step_logs.append(_log(current, detail))
        elif current.kind == "band":
            working, detail, labels = apply_bands(working, current)
            meta.append(
                {
                    "name": detail["output"],
                    "label": f"{detail['source']} groups",
                    "value_labels": labels,
                    "user_missing_values": [],
                }
            )
            if detail["unassigned"]:
                warnings.append(
                    f"{detail['unassigned']} answers on {detail['source']} fell outside every "
                    f"group, so {detail['output']} is missing for them."
                )
            step_logs.append(_log(current, detail))
        elif current.kind == "impute_missing":
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
                nominal_columns(meta, features),
            )
            k, scores = choose_k(working, plan)
            chosen = {"k": k, "silhouette_by_k": scores}
            current = current.model_copy(update={"k": k})
            warnings.append(f"Silhouette chose k={k}.")
            step_logs.append(_log(current, chosen))
        elif current.kind == "method":
            if current.split_by:
                current, group_runs, extra = _run_split(working, resolved, current, chosen, meta)
                runs.extend(group_runs)
                comparisons.append(_compare(current, group_runs))
                warnings.extend(extra)
                detail: dict[str, Any] = {
                    "method": current.method,
                    "split_by": current.split_by,
                    "groups": [run.group for run in group_runs],
                }
            else:
                current, result, extra = _run_method(working, resolved, current, chosen, meta)
                runs.append(MethodRun(current, "", result))
                warnings.extend(extra)
                detail = {"method": current.method, "k": current.k}
                labels = (result.descriptive or {}).get("labels")
                if labels and (is_segmentation(current.method) or current.procedure):
                    segment_column = current.output.strip() or "segment"
                    working = _attach_segment(working, resolved, current, result, segment_column)
                    meta.append(_segment_meta(working, segment_column))
                    detail["saved"] = [segment_column]
                if (result.descriptive or {}).get("scores") and current.output.strip():
                    working, saved = _attach_scores(working, result, current.output.strip())
                    detail["saved"] = saved
                    warnings.append(
                        f"Saved {current.method.upper()} scores as {', '.join(saved)} for later steps."
                    )
            step_logs.append(_log(current, detail))
        elif current.kind == "profile_crosstab":
            banner = current.group or segment_column or "segment"
            profile_tables = _profile(working, current, meta, resolved.weight_variable, banner)
            _remember_profile(metrics, profile_tables)
            step_logs.append(_log(current, {"tables": len(profile_tables), "banner": banner}))
        elif current.kind == "report":
            step_logs.append(_log(current, {"status": "summary written from computed fields"}))
        steps.append(_saved_step(step, current))

    if not runs:
        raise AppError("The plan needs an analysis method.", "bad_plan")
    resolved = resolved.model_copy(update={"steps": steps})
    payload = _combine(runs, resolved, metrics, warnings, chosen)
    payload["diagnostics"].update(
        {
            "steps": step_logs,
            "profile_tables": profile_tables,
            "chosen_k": chosen,
            "comparisons": comparisons,
        }
    )
    payload["seed"] = workflow.random_seed
    payload["resolved_workflow"] = resolved.model_dump(mode="json")
    return _jsonable(payload)


def _saved_step(step: AnalysisStep, current: AnalysisStep) -> AnalysisStep:
    """Return the plan step with the method name and any chosen k filled in."""
    if current.kind == "method":
        return step.model_copy(update={"method": current.method, "k": current.k or step.k})
    if current.k and step.k != current.k:
        return step.model_copy(update={"k": current.k})
    return step


def _combine(
    runs: list[MethodRun],
    workflow: AnalysisWorkflow,
    metrics: dict[str, Any],
    warnings: list[str],
    chosen: dict[str, Any],
) -> dict[str, Any]:
    """Merge method results into one payload.

    A single fit keeps its own field names. Several fits, or one fit per
    subgroup, are prefixed with the method and the group so every number
    stays traceable to the model that produced it.

    Args:
        runs: Method fits in plan order.
        workflow: Resolved plan.
        metrics: Step metrics, such as fill counts and profile cells.
        warnings: Step warnings.
        chosen: Silhouette choice, if any.

    Returns:
        Payload without step diagnostics.
    """
    if len(runs) == 1 and not runs[0].group:
        result = runs[0].result
        estimates = dict(result.model_estimates)
        merged = {**dict(result.metrics), **metrics}
        descriptive = {
            key: value for key, value in result.descriptive.items() if key not in _ROW_DATA
        }
        method = result.method
        flow = result.sample_flow
        methods: list[dict[str, Any]] = []
        notes = list(result.warnings)
    else:
        estimates, merged, descriptive, notes = {}, {}, {}, []
        methods = []
        steps_by_method: dict[str, set[str]] = {}
        for run in runs:
            steps_by_method.setdefault(run.step.method, set()).add(run.step.step_id)
        for run in runs:
            tag = _tag(run, steps_by_method)
            for name, value in run.result.model_estimates.items():
                estimates[f"{tag}_{_key(str(name))}"] = value
            for name, value in run.result.metrics.items():
                merged[f"{tag}_{_key(str(name))}"] = value
            merged[f"{tag}_valid_n"] = run.result.sample_flow.get("valid_n")
            descriptive[tag] = {
                key: value for key, value in run.result.descriptive.items() if key not in _ROW_DATA
            }
            prefix = f"{run.group}: " if run.group else ""
            notes.extend(f"{prefix}{item}" for item in run.result.warnings)
            methods.append(
                {
                    "step_id": run.step.step_id,
                    "method": run.result.method,
                    "group": run.group,
                    "prefix": tag,
                    "sample_flow": run.result.sample_flow,
                }
            )
        merged.update(metrics)
        distinct = list(dict.fromkeys(run.step.step_id for run in runs))
        method = runs[0].result.method if len(distinct) == 1 else "multi_step"
        flow = _flow(runs)
    if chosen:
        merged["k"] = chosen["k"]
    return {
        "method": method,
        "sample_flow": flow,
        "model_estimates": estimates,
        "metrics": merged,
        "diagnostics": {"methods": methods},
        "warnings": list(dict.fromkeys(notes + warnings)),
        "descriptive": descriptive,
        "software_versions": versions(),
    }


def _tag(run: MethodRun, steps_by_method: dict[str, set[str]]) -> str:
    """Return the field prefix for one fit, such as ``key_driver_Male``.

    The step id is added when the same method appears in more than one step.
    """
    base = run.step.method
    if len(steps_by_method.get(base, set())) > 1:
        base = f"{base}_{run.step.step_id}"
    return _key(f"{base}_{run.group}" if run.group else base)


def _flow(runs: list[MethodRun]) -> dict[str, Any]:
    """Return the sample flow to headline when several fits ran.

    Subgroup fits of the last method add up; otherwise the last method's
    sample is the one the final answer rests on.
    """
    last = runs[-1].step.step_id
    final = [run for run in runs if run.step.step_id == last]
    if len(final) == 1:
        return dict(final[0].result.sample_flow)
    return {
        "input_n": sum(int(run.result.sample_flow.get("input_n") or 0) for run in final),
        "valid_n": sum(int(run.result.sample_flow.get("valid_n") or 0) for run in final),
        "groups": {run.group: run.result.sample_flow.get("valid_n") for run in final},
    }


def _expand(step: AnalysisStep, frame: pd.DataFrame) -> AnalysisStep:
    """Replace ``name*`` with the matching columns, in frame order.

    Recoded helper columns (``__top2``) are not matched, so ``Q7r*`` means
    the original items.
    """

    def names(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value.endswith("*") and value[:-1]:
                stem = value[:-1]
                out.extend(
                    column
                    for column in frame.columns
                    if str(column).startswith(stem) and "__" not in str(column)
                )
            else:
                out.append(value)
        return list(dict.fromkeys(out))

    return step.model_copy(
        update={"variables": names(step.variables), "predictors": names(step.predictors)}
    )


def _filter_note(detail: dict[str, Any], meta: list[dict[str, Any]]) -> str:
    """Describe a filter in words, using value labels when there are any."""
    name = detail["variable"]
    if "codes" in detail:
        labels = next(
            (item.get("value_labels") or {} for item in meta if item.get("name") == name), {}
        )
        shown = [str(labels.get(str(code), code)) for code in detail["codes"]]
        rule = "is " + " or ".join(shown)
    else:
        low, high = detail.get("lower"), detail.get("upper")
        rule = (
            f"is between {low} and {high}"
            if low is not None and high is not None
            else (f"is at least {low}" if low is not None else f"is at most {high}")
        )
    return f"Kept {detail['kept']} of {detail['before']} respondents where {name} {rule}."


def _run_split(
    frame: pd.DataFrame,
    workflow: AnalysisWorkflow,
    step: AnalysisStep,
    chosen: dict[str, Any],
    meta: list[dict[str, Any]],
) -> tuple[AnalysisStep, list[MethodRun], list[str]]:
    """Fit the method once for each group of ``split_by``.

    Args:
        frame: Working data.
        workflow: Parent workflow.
        step: Method step with ``split_by``.
        chosen: Silhouette choice, shared with the groups.
        meta: Variable dictionary, used for group labels.

    Returns:
        The step with its method normalized, one fit per group, and notes on skipped groups.

    Raises:
        AppError: The split variable has fewer than two groups or too many, or every group failed.
    """
    column = step.split_by
    labels = next(
        (item.get("value_labels") or {} for item in meta if item.get("name") == column), {}
    )
    values = frame[column].dropna().unique().tolist()
    try:
        values = sorted(values, key=float)
    except (TypeError, ValueError):
        values = sorted(values, key=str)
    if len(values) < 2:
        raise AppError(f"{column} has fewer than two groups to compare.", "small_sample")
    if len(values) > _MAX_GROUPS:
        raise AppError(
            f"{column} has {len(values)} groups. Band it into {_MAX_GROUPS} or fewer first.",
            "bad_plan",
        )
    base = step.model_copy(update={"split_by": ""})
    runs: list[MethodRun] = []
    notes: list[str] = []
    for value in values:
        label = _group_label(value, labels)
        subset = frame.loc[in_codes(frame[column], [value]).astype(bool)]
        try:
            current, result, extra = _run_method(subset, workflow, base, dict(chosen), meta)
        except AppError as error:
            notes.append(f"Skipped {column} = {label}: {error.message}")
            continue
        runs.append(MethodRun(current, label, result))
        notes.extend(f"{label}: {item}" for item in extra)
    if not runs:
        raise AppError(f"The method could not run in any {column} group.", "small_sample")
    return runs[0].step.model_copy(update={"split_by": column}), runs, notes


def _group_label(value: Any, labels: dict[Any, Any]) -> str:
    """Return a group's value label, or its code."""
    try:
        number = float(value)
        text = str(int(number)) if number.is_integer() else str(number)
    except (TypeError, ValueError):
        text = str(value)
    return str(labels.get(text) or labels.get(str(value)) or text)


def _compare(step: AnalysisStep, runs: list[MethodRun]) -> dict[str, Any]:
    """Line up the same estimate across subgroup fits.

    With two groups each row also carries the second group minus the first.
    The difference is descriptive; no test of it is run.

    Args:
        step: Split method step.
        runs: One fit per group.

    Returns:
        Comparison table.
    """
    groups = [run.group for run in runs]
    rows: list[dict[str, Any]] = []
    terms = list(dict.fromkeys(name for run in runs for name in run.result.model_estimates))
    for term in terms:
        fields = list(
            dict.fromkeys(
                key
                for run in runs
                for key, value in _fields(run.result.model_estimates.get(term)).items()
            )
        )
        for field in fields:
            values = {
                run.group: _fields(run.result.model_estimates.get(term)).get(field) for run in runs
            }
            rows.append(_compare_row(term, field, values, groups))
    for name in dict.fromkeys(key for run in runs for key in run.result.metrics):
        values = {run.group: _number(run.result.metrics.get(name)) for run in runs}
        if any(value is not None for value in values.values()):
            rows.append(_compare_row("model", name, values, groups))
    return {
        "step_id": step.step_id,
        "method": step.method,
        "split_by": step.split_by,
        "groups": groups,
        "bases": {run.group: run.result.sample_flow.get("valid_n") for run in runs},
        "rows": rows[:_COMPARE_ROWS],
    }


def _fields(estimate: Any) -> dict[str, float]:
    """Return the numeric fields of one estimate."""
    if isinstance(estimate, dict):
        return {
            str(key): number
            for key, value in estimate.items()
            if (number := _number(value)) is not None
        }
    number = _number(estimate)
    return {} if number is None else {"value": number}


def _number(value: Any) -> float | None:
    """Return a finite number, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return None if value != value else float(value)


def _compare_row(
    term: str, field: str, values: dict[str, float | None], groups: list[str]
) -> dict[str, Any]:
    """Build one comparison row, with a difference when there are two groups."""
    row: dict[str, Any] = {"term": term, "field": field, "values": values}
    if len(groups) == 2:
        first, second = values.get(groups[0]), values.get(groups[1])
        if first is not None and second is not None:
            row["difference"] = second - first
    return row


def _attach_scores(
    frame: pd.DataFrame, result: AnalysisResult, prefix: str
) -> tuple[pd.DataFrame, list[str]]:
    """Write factor or component scores onto the rows that entered the model.

    Rows with a missing item get no score.

    Args:
        frame: Working data.
        result: EFA or PCA result with ``scores`` and ``row_index``.
        prefix: Column prefix. Scores become prefix1, prefix2, ...

    Returns:
        Frame with the score columns and their names.

    Raises:
        AppError: A score column would overwrite a dataset column.
    """
    scores = result.descriptive.get("scores") or []
    index = result.descriptive.get("row_index") or []
    out = frame.copy()
    names: list[str] = []
    for number, values in enumerate(scores, start=1):
        name = f"{prefix}{number}"
        if name in out.columns:
            raise AppError(
                f"{name} is already a column, so the scores need another name.", "bad_plan"
            )
        column = pd.Series(float("nan"), index=out.index, dtype=float)
        if len(values) == len(index):
            column.loc[index] = values
        out[name] = column
        names.append(name)
    return out, names


def _segment_meta(frame: pd.DataFrame, name: str) -> dict[str, Any]:
    """Return a variable-dictionary entry for saved segment labels."""
    present = sorted({int(value) for value in frame[name].dropna().unique()})
    return {
        "name": name,
        "label": "Segment",
        "value_labels": {str(label): f"Segment {label}" for label in present},
        "user_missing_values": [],
    }


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
    method = canonical_method(step.method)
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
    if method in {"efa", "pca"}:
        if not step.k and step.output.strip():
            count = kaiser_count(frame, list(step.variables))
            step = step.model_copy(update={"k": count})
            notes.append(
                f"Kept {count} {'factor' if method == 'efa' else 'component'}{'' if count == 1 else 's'} "
                "with eigenvalues above 1."
            )
        if step.k:
            options["n_components"] = step.k
        if step.output.strip():
            options["save_scores"] = True
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
    name: str = "segment",
) -> pd.DataFrame:
    """Write cluster labels onto the rows that entered the segmentation.

    Args:
        frame: Working data.
        workflow: Parent workflow.
        step: Clustering step.
        result: Clustering result. Labels follow the prepared row order.
        name: Column that receives the labels.

    Returns:
        Frame with the segment column.
    """
    data, _, _ = prepare_clustering(frame, clustering_plan(workflow, step))
    labels = [int(value) for value in result.descriptive.get("labels") or []]
    out = frame.copy()
    out[name] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    if len(labels) == len(data):
        out.loc[data.index, name] = labels
    return out


def _profile(
    frame: pd.DataFrame,
    step: AnalysisStep,
    variables: list[dict[str, Any]],
    weight: str,
    banner_name: str = "segment",
) -> list[dict[str, Any]]:
    """Cross the segment, or another grouping column, against each profiling variable.

    Args:
        frame: Working data including the grouping column.
        step: Profile step. ``variables`` are the profilers.
        variables: Variable dictionary.
        weight: Weight variable, or empty.
        banner_name: Grouping column across the top.

    Returns:
        One table dictionary per profiler.

    Raises:
        AppError: No segmentation or grouping column has values.
    """
    if banner_name not in frame.columns or not bool(frame[banner_name].notna().any()):
        raise AppError("A profile cross-tab needs a clustering step before it.", "bad_plan")
    clustered = frame.loc[frame[banner_name].notna()].copy()
    by_name = {str(item.get("name")): item for item in variables}
    known = (by_name.get(banner_name) or {}).get("value_labels") or {}
    present = sorted({int(float(value)) for value in clustered[banner_name].dropna().unique()})
    banner = Banner(
        id="segment",
        label="Segment" if banner_name == "segment" else banner_name,
        variable_name=banner_name,
        categories=[
            BannerCategory(
                label=str(known.get(str(label)) or f"Segment {label}"),
                codes=[label],
                order=index,
            )
            for index, label in enumerate(present)
        ],
        include_total=True,
    )
    meta = [item for item in variables if str(item.get("name")) != banner_name] + [
        {
            "name": banner_name,
            "label": "Segment" if banner_name == "segment" else banner_name,
            "value_labels": {
                str(label): str(known.get(str(label)) or f"Segment {label}") for label in present
            },
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
            title=f"{name} by {banner.label.lower()}",
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
