"""Check a workflow, and render the script and the plan the user downloads."""

import re
from typing import Any

from app.engines.analysis.procedure_code import validate_procedure
from app.engines.analysis.procedures import family, is_segmentation
from app.engines.analysis.program_code import validate_program
from app.engines.analysis.registry import SUPPORTED_METHODS
from app.engines.tabspec_banners import is_weight_name
from app.errors import AppError
from app.schemas.analysis import AnalysisStep, AnalysisWorkflow, Band
from app.util import new_id

_BLOCKED = {"maxdiff", "max-diff", "conjoint", "cbc"}
_PREP = re.compile(r"imput|top[- ]?2|top box|bottom box|profil", re.I)
# Reason: these phrases mean more than one step, so a keyword shortcut would drop part of the request.
MULTI_STEP = re.compile(
    r"\bthen\b|\bafterwards?\b|\bseparately\b|\bfor each\b|\bwithin each\b|\bamong\b|"
    r"\bonly (?:for|among)\b|\bgroup(?:ed)?\s+[\w-]+(?:\s+[\w-]+)?\s+into\b|"
    r"\bband(?:s|ed|ing)?\b|\brecode|\bcompare\b|\bfactor scores?\b|"
    r"\bcomponent scores?\b|\bsplit by\b|\bsubgroups?\b",
    re.I,
)
_MAX_METHODS = 6
_SCORES = {"efa", "pca"}
# Reason: these methods need a look at scales and missingness before the steps are fixed.
_JUDGMENT = {"clustering", "pca", "efa"}


def direct_workflow(
    request: str, hints: dict[str, Any], dataset_id: str
) -> AnalysisWorkflow | None:
    """Build a one-method plan when the request already names every role.

    Args:
        request: User text.
        hints: Roles parsed from the request.
        dataset_id: Active dataset id.

    Returns:
        A method-and-report workflow, or None when the planner should read the
        profile and decide the steps.
    """
    method = str(hints.get("method") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if (
        method in _JUDGMENT
        or method not in SUPPORTED_METHODS
        or _PREP.search(request)
        or MULTI_STEP.search(request)
    ):
        return None
    if not _roles_ready(method, hints):
        return None
    return AnalysisWorkflow(
        analysis_id=new_id(),
        dataset_id=dataset_id,
        objective=request.strip() or method.replace("_", " "),
        data_facts=[
            "The request named the method and the variables, so no extra recoding was added."
        ],
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="method",
                method=method,
                variables=list(hints.get("variables") or []),
                dependent=str(hints.get("dependent") or ""),
                predictors=list(hints.get("predictors") or []),
                group=str(hints.get("group") or ""),
                var_a=str(hints.get("var_a") or ""),
                var_b=str(hints.get("var_b") or ""),
                k=int(hints.get("k") or 0),
                reason="The request named this method and its variables.",
            ),
            AnalysisStep(step_id="s2", kind="report", reason="Summarize the computed fields."),
        ],
        random_seed=int(hints.get("seed") or 42),
        weight_variable=str(hints.get("weight_variable") or ""),
    )


def _roles_ready(method: str, hints: dict[str, Any]) -> bool:
    """Return whether the parsed hints already contain the method's roles.

    Args:
        method: Registered method name.
        hints: Parsed roles.

    Returns:
        True when a model does not need to choose a variable.
    """
    if method in {"chi_square", "correspondence"}:
        return bool(hints.get("var_a") and hints.get("var_b"))
    if method in {"t_test", "anova"}:
        return bool(hints.get("dependent") and hints.get("group"))
    if method in {
        "linear_regression",
        "binary_logistic_regression",
        "ordinal_regression",
        "key_driver",
        "discriminant",
    }:
        return bool(hints.get("dependent") and hints.get("predictors"))
    if method == "descriptive":
        return bool(hints.get("variables"))
    if method in {"correlation", "reliability"}:
        return len(hints.get("variables") or []) >= 2
    return False


def needs_generated_program(workflow: AnalysisWorkflow) -> bool:
    """Return whether the runner should ask for a script.

    A built-in method, a supplied compute function, and a question for the
    user stay on their existing paths.

    Args:
        workflow: Planner output.

    Returns:
        True when the only method has no built-in runner and no script yet.
    """
    if workflow.status == "clarification_needed" or workflow.program.strip():
        return False
    return _custom_method(workflow)


def uses_generated_program(workflow: AnalysisWorkflow) -> bool:
    """Return whether the sandbox file is the generated script.

    Args:
        workflow: Plan, possibly with a script attached.

    Returns:
        True when that script should run instead of a built-in method.
    """
    if workflow.status == "clarification_needed" or not workflow.program.strip():
        return False
    return _custom_method(workflow)


def _custom_method(workflow: AnalysisWorkflow) -> bool:
    """Return whether the plan's single method has no built-in runner.

    Args:
        workflow: Plan.

    Returns:
        True for one method step that is not registered, not a known
        segmentation procedure, and not a supplied compute function.
    """
    methods = [step for step in workflow.steps if step.kind == "method"]
    if len(methods) != 1 or methods[0].procedure.strip():
        return False
    method = canonical_method(methods[0].method)
    if not method or method in _BLOCKED or method in SUPPORTED_METHODS or family(method):
        return False
    return True


def ensure_runnable(workflow: AnalysisWorkflow, columns: set[str]) -> None:
    """Reject a plan that cannot be executed, before the sandbox starts.

    Steps run in order, so a step may use a column that an earlier band or
    method step creates. ``name*`` stands for every column starting with
    ``name``, such as factor scores saved as F1, F2, F3.

    Args:
        workflow: Planner output.
        columns: Variable names on the dataset.

    Raises:
        AppError: The plan asks for a missing choice, an unknown variable,
            a blocked method, or a step the runner cannot perform.
    """
    if workflow.status == "clarification_needed":
        message = workflow.clarification or "I need a choice before I can run this analysis."
        if workflow.missing_choices:
            message = f"{message} I still need: {', '.join(workflow.missing_choices)}."
        raise AppError(message.strip(), "clarification_needed")
    if not workflow.steps:
        raise AppError("The analysis plan has no steps.", "bad_plan")
    methods = [step for step in workflow.steps if step.kind == "method"]
    if not methods:
        raise AppError("The plan needs an analysis method.", "bad_plan")
    if len(methods) > _MAX_METHODS:
        raise AppError(
            f"The plan has {len(methods)} methods. Split it into requests of "
            f"{_MAX_METHODS} methods or fewer.",
            "bad_plan",
        )
    for step in methods:
        _check_method(step, workflow, columns, chained=len(methods) > 1)
    if workflow.weight_variable and workflow.weight_variable not in columns:
        raise AppError(
            f"The plan names {workflow.weight_variable}, which is not in the dataset.",
            "missing_variable",
        )
    features: set[str] = set()
    for step in methods:
        if is_segmentation(_normal(step.method)):
            features.update(step.variables)
    available = set(columns)
    prefixes: set[str] = set()
    for step in workflow.steps:
        for name in _referenced(step):
            if not _known(name, available, prefixes):
                raise AppError(
                    f"The plan names {name}, which is not in the dataset.",
                    "missing_variable",
                )
        if step.kind == "impute_missing":
            for name in step.variables:
                if _protected(name, workflow.weight_variable):
                    raise AppError(
                        f"{name} is a weight or an id and is not imputed.",
                        "bad_plan",
                    )
        elif step.kind == "filter":
            _check_filter(step)
        elif step.kind == "band":
            _check_band(step, available)
            available.add(step.output.strip())
        elif step.kind == "method":
            _add_outputs(step, available, prefixes)
        elif step.kind == "profile_crosstab" and features:
            overlap = sorted(set(step.variables) & features)
            if overlap:
                raise AppError(
                    "Profile variables must be columns that were not used as clustering features: "
                    + ", ".join(overlap),
                    "bad_plan",
                )


_ALIASES = {
    "regression": "linear_regression",
    "linear": "linear_regression",
    "ols": "linear_regression",
    "ols_regression": "linear_regression",
    "multiple_regression": "linear_regression",
    "multiple_linear_regression": "linear_regression",
    "logistic_regression": "binary_logistic_regression",
    "logistic": "binary_logistic_regression",
    "logit": "binary_logistic_regression",
    "ordinal_logistic_regression": "ordinal_regression",
    "factor_analysis": "efa",
    "exploratory_factor_analysis": "efa",
    "principal_component_analysis": "pca",
    "principal_components_analysis": "pca",
    "principal_components": "pca",
    "kmeans": "clustering",
    "k_means": "clustering",
    "chi2": "chi_square",
    "chisquare": "chi_square",
    "chi_squared": "chi_square",
    "ttest": "t_test",
    "one_way_anova": "anova",
    "key_driver_analysis": "key_driver",
    "driver_analysis": "key_driver",
    "cronbach_alpha": "reliability",
    "correspondence_analysis": "correspondence",
    "discriminant_analysis": "discriminant",
    "descriptives": "descriptive",
}


def canonical_method(method: str) -> str:
    """Return the registered name for a method, mapping common names such as "regression".

    Args:
        method: Method name as the planner wrote it.

    Returns:
        Lower-case, underscored name, mapped to the built-in method when one matches.
    """
    name = method.strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(name, name)


def _normal(method: str) -> str:
    """Normalize a method name the way the runner does."""
    return canonical_method(method)


def _check_method(
    step: AnalysisStep, workflow: AnalysisWorkflow, columns: set[str], *, chained: bool
) -> None:
    """Reject a blocked, unknown, or badly combined method step.

    Args:
        step: Method step.
        workflow: Plan.
        columns: Dataset columns.
        chained: Whether the plan has more than one method.

    Raises:
        AppError: The method cannot run in this plan.
    """
    method = _normal(step.method)
    if method in _BLOCKED:
        raise AppError(
            "MaxDiff and conjoint are out of scope for this studio. No alternative model was run.",
            "unsupported_method",
        )
    if step.split_by and step.output:
        raise AppError(
            "A method that runs once per group cannot also save a new column.", "bad_plan"
        )
    if method in SUPPORTED_METHODS or family(method) is not None:
        return
    if chained:
        raise AppError(
            f"'{step.method}' has no built-in runner, so it cannot be chained with other "
            "methods. Ask for it on its own.",
            "unsupported_method",
        )
    if step.procedure.strip():
        validate_procedure(step.procedure)
    elif uses_generated_program(workflow):
        validate_program(workflow.program, columns, set(referenced_names(workflow)))
    else:
        raise AppError(
            f"'{step.method}' has no implementation, so no result was published.",
            "unsupported_method",
        )


def _check_filter(step: AnalysisStep) -> None:
    """Reject a filter without one variable and a rule."""
    if len(step.variables) != 1:
        raise AppError("A filter step names exactly one variable.", "bad_plan")
    has_range = bool(step.bands) and (
        step.bands[0].lower is not None or step.bands[0].upper is not None
    )
    if not step.codes and not has_range:
        raise AppError(f"The filter on {step.variables[0]} lists no codes or range.", "bad_plan")


def _check_band(step: AnalysisStep, available: set[str]) -> None:
    """Reject a band step that cannot write a new grouped column."""
    output = step.output.strip()
    if len(step.variables) != 1 or not output:
        raise AppError("A band step names one source variable and an output name.", "bad_plan")
    if output in available:
        raise AppError(f"{output} is already a column, so the bands need a new name.", "bad_plan")
    if len(step.bands) < 2:
        raise AppError(f"Banding {step.variables[0]} needs at least two groups.", "bad_plan")
    for band in step.bands:
        if not band.codes and band.lower is None and band.upper is None:
            raise AppError(f"The band '{band.label}' has no codes or range.", "bad_plan")


def _add_outputs(step: AnalysisStep, available: set[str], prefixes: set[str]) -> None:
    """Record the columns a method step leaves for later steps."""
    method = _normal(step.method)
    if step.split_by:
        return
    if is_segmentation(method) or step.procedure.strip():
        available.add(step.output.strip() or "segment")
    elif method in _SCORES and step.output.strip():
        prefixes.add(step.output.strip())


def _known(name: str, available: set[str], prefixes: set[str]) -> bool:
    """Return whether a step may use this name at this point in the plan."""
    if name in available:
        return True
    if name.endswith("*"):
        stem = name[:-1]
        return bool(stem) and (
            stem in prefixes or any(column.startswith(stem) for column in available)
        )
    return False


def compile_script(workflow: AnalysisWorkflow) -> str:
    """Return the Python file the sandbox executes.

    Args:
        workflow: Plan. The script reads ``workflow.json`` rather than
            inlining respondent data.

    Returns:
        Script source. A generated program is returned as the whole file.
    """
    if uses_generated_program(workflow):
        return workflow.program.strip() + "\n"
    lines = [
        '"""Analysis script. The sandbox executed this file."""',
        "",
        f"# objective: {workflow.objective}",
        f"# seed: {workflow.random_seed}",
    ]
    for index, step in enumerate(workflow.steps, start=1):
        lines.append(f"# Step {index}: {step.kind} — {step.reason}")
    procedure = next((step.procedure for step in workflow.steps if step.procedure.strip()), "")
    if procedure:
        lines.extend(["", "PROCEDURE = " + repr(procedure), ""])
    lines.extend(
        [
            "from app.engines.analysis.runtime import run_job_files",
            "",
            "run_job_files()",
            "",
        ]
    )
    return "\n".join(lines)


def render_plan(workflow: AnalysisWorkflow, columns: list[dict[str, Any]] | None = None) -> str:
    """Return the markdown plan the user downloads.

    Args:
        workflow: Plan, including a k chosen during the run when there is one.
        columns: Checked missing counts for the named variables.

    Returns:
        Markdown text.
    """
    lines = [
        f"# {workflow.objective}",
        "",
        "## Objective",
        "",
        workflow.objective,
        "",
        "## Data facts",
        "",
    ]
    facts = workflow.data_facts or ["The plan used the dataset profile."]
    lines.extend(f"- {fact}" for fact in facts)
    lines.extend(["", "## Steps", ""])
    for index, step in enumerate(workflow.steps, start=1):
        lines.append(f"{index}. **{step.kind}** — {step.reason}")
        if step.variables:
            lines.append(f"   - Variables: {', '.join(step.variables)}")
        detail = _step_settings(step)
        if detail:
            lines.append(f"   - Settings: {detail}")
    if columns:
        lines.extend(["", "## Checked counts", ""])
        for column in columns:
            lines.append(
                f"- `{column['name']}`: {column['nonmissing_n']} answered, "
                f"{column['missing_n']} missing."
            )
    lines.extend(["", "## Assumptions", ""])
    assumptions = workflow.assumptions or [
        "Associations describe this sample. They are not causal effects.",
        "The script that ran is the analysis.py download.",
    ]
    lines.extend(f"- {item}" for item in assumptions)
    if uses_generated_program(workflow):
        lines.extend(
            [
                "",
                "The analysis script was written for this request and checked before it ran.",
            ]
        )
    lines.extend(["", f"Seed: {workflow.random_seed}", ""])
    return "\n".join(lines)


def referenced_names(workflow: AnalysisWorkflow) -> list[str]:
    """Return the dataset columns the plan names, in first-seen order.

    Args:
        workflow: Plan.

    Returns:
        Variable names.
    """
    names: list[str] = []
    if workflow.weight_variable:
        names.append(workflow.weight_variable)
    for step in workflow.steps:
        for name in _referenced(step):
            if name not in names:
                names.append(name)
    return names


def _referenced(step: AnalysisStep) -> list[str]:
    """Return variable names a step uses.

    Args:
        step: Plan step.

    Returns:
        Names, excluding blanks.
    """
    names = list(step.variables)
    names.extend(step.predictors)
    for name in (step.dependent, step.group, step.var_a, step.var_b, step.split_by):
        if name:
            names.append(name)
    return names


def _protected(name: str, weight: str) -> bool:
    """Return whether a column must not be imputed.

    Args:
        name: Variable name.
        weight: Weight variable on the plan, or empty.

    Returns:
        True for a weight or an id.
    """
    lowered = name.lower()
    if weight and name == weight:
        return True
    if is_weight_name(name):
        return True
    return lowered in {"id", "respondent_id", "respid"} or lowered.endswith("_id")


def _step_settings(step: AnalysisStep) -> str:
    """Format the settings that change what a step computes.

    Args:
        step: Plan step.

    Returns:
        Short setting text, or empty.
    """
    parts: list[str] = []
    if step.method:
        parts.append(f"method={step.method}")
    if step.strategy:
        parts.append(f"strategy={step.strategy}")
    if step.kind in {"top_box", "bottom_box"}:
        parts.append(f"box={step.box or 2}")
    if step.codes:
        parts.append("codes=" + ",".join(step.codes))
    if step.k:
        parts.append(f"k={step.k}")
    if step.dependent:
        parts.append(f"dependent={step.dependent}")
    if step.predictors:
        parts.append("predictors=" + ",".join(step.predictors))
    if step.split_by:
        parts.append(f"separately for each {step.split_by} group")
    if step.output:
        parts.append(f"output={step.output}")
    if step.bands:
        parts.append("groups=" + "; ".join(_band_text(band) for band in step.bands))
    return ", ".join(parts)


def _band_text(band: Band) -> str:
    """Describe one band for the plan download."""
    if band.codes:
        return f"{band.label} (codes {','.join(band.codes)})"
    low = "" if band.lower is None else f"{band.lower:g}"
    high = "" if band.upper is None else f"{band.upper:g}"
    return f"{band.label} ({low}-{high})"
