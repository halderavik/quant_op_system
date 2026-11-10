"""Multi-step analysis plans: preparation, sandbox execution, and refusals."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.agents.analysis_planner import planner_prompt
from app.config import Settings
from app.engines.analysis.compile import (
    compile_script,
    direct_workflow,
    ensure_runnable,
    render_plan,
)
from app.engines.analysis.registry import run_plan
from app.engines.analysis.report import build_report
from app.engines.analysis.segmenters import gower_distance
from app.engines.analysis.steps import impute_missing
from app.engines.analysis.workbook import workbook_bytes
from app.engines.analysis.workflow import execute_workflow
from app.errors import AppError
from app.sandbox.runner import run_script
from app.schemas.analysis import AnalysisPlan, AnalysisResult, AnalysisStep, AnalysisWorkflow
from app.services.analysis_run import require_analysis_output, run_compiled_workflow


def _labels() -> dict[str, str]:
    """Return a five-point agreement scale.

    Returns:
        Code to label.
    """
    return {
        "1": "Strongly disagree",
        "2": "Disagree",
        "3": "Neutral",
        "4": "Agree",
        "5": "Strongly agree",
    }


def _variables() -> list[dict]:
    """Return the dictionary for the segmentation fixture.

    Returns:
        Variable metadata.
    """
    scale = {"value_labels": _labels(), "user_missing_values": []}
    return [
        {"name": "q1", "label": "Quality", **scale},
        {"name": "q2", "label": "Service", **scale},
        {"name": "q3", "label": "Value", **scale},
        {
            "name": "gender",
            "label": "Gender",
            "value_labels": {"1": "Female", "2": "Male"},
            "user_missing_values": [],
        },
    ]


def _battery() -> pd.DataFrame:
    """Build two opinion groups and a few missing answers.

    Returns:
        Eighty-row frame.
    """
    rng = np.random.default_rng(0)
    low = rng.integers(1, 3, 40)
    high = rng.integers(4, 6, 40)
    frame = pd.DataFrame(
        {
            "q1": np.concatenate([low, high]).astype(float),
            "q2": np.concatenate([low, high]).astype(float),
            "q3": np.concatenate([rng.integers(1, 3, 40), rng.integers(4, 6, 40)]).astype(float),
            "gender": np.array([1, 2] * 40, dtype=float),
        }
    )
    frame.loc[0:5, "q1"] = np.nan
    return frame


def _segmentation() -> AnalysisWorkflow:
    """Return the imputation, top-2-box, cluster, and profile plan.

    Returns:
        Workflow.
    """
    return AnalysisWorkflow(
        analysis_id="seg",
        objective="Segment agreement and profile by gender",
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="impute_missing",
                variables=["q1", "q2", "q3"],
                strategy="median",
                reason="Missing answers would shrink the clustering base.",
            ),
            AnalysisStep(
                step_id="s2",
                kind="top_box",
                variables=["q1", "q2", "q3"],
                box=2,
                reason="The agreement scale is summarized as a top-2 box.",
            ),
            AnalysisStep(
                step_id="s3",
                kind="choose_k",
                variables=["q1", "q2", "q3"],
                reason="The request did not name k.",
            ),
            AnalysisStep(
                step_id="s4",
                kind="method",
                method="clustering",
                variables=["q1", "q2", "q3"],
                reason="Segment respondents on the recoded agreement items.",
            ),
            AnalysisStep(
                step_id="s5",
                kind="profile_crosstab",
                variables=["gender"],
                reason="Profile the segments on gender.",
            ),
            AnalysisStep(step_id="s6", kind="report", reason="Summarize the computed fields."),
        ],
        random_seed=7,
    )


def test_sandbox_segments_after_impute_and_top_2_box(settings: Settings, tmp_path: Path) -> None:
    """A Likert battery is imputed, recoded, clustered, and profiled in the sandbox."""
    workflow = _segmentation()
    payload = run_compiled_workflow(settings, tmp_path / "job", _battery(), workflow, _variables())
    sizes = payload["model_estimates"]["sizes"]
    assert sum(sizes.values()) == payload["sample_flow"]["valid_n"]
    assert payload["sample_flow"]["valid_n"] == 80
    recodes = next(step for step in payload["diagnostics"]["steps"] if step["kind"] == "top_box")
    for column in recodes["detail"]["columns"]:
        assert set(column["values"]) <= {0, 1}
        assert column["values"]
    resolved = payload["resolved_workflow"]
    choose = next(step for step in resolved["steps"] if step["kind"] == "choose_k")
    assert 2 <= choose["k"] <= 6
    profile = payload["diagnostics"]["profile_tables"][0]
    assert profile["variable"] == "gender"
    bases = profile["rows"][0]["bases"]
    segment_base = sum(value for label, value in bases.items() if label != "Total")
    assert segment_base == bases["Total"] == 80
    report = build_report(workflow.objective, AnalysisResult.model_validate(payload))
    plan = render_plan(workflow)
    book = workbook_bytes(workflow, payload, report)
    assert "top_box" in plan
    assert book[:2] == b"PK"
    assert "run_job_files" in compile_script(workflow)


def test_impute_leaves_complete_values_untouched() -> None:
    """An impute step fills nothing when the column is already complete."""
    original = pd.DataFrame({"q1": [1.0, 2.0, 3.0, 4.0], "q2": [1.0, 1.0, 2.0, 2.0]})
    filled, log = impute_missing(original, ["q1"], "median")
    assert log[0]["filled"] == 0
    assert filled["q1"].tolist() == original["q1"].tolist()
    workflow = AnalysisWorkflow(
        analysis_id="edge",
        objective="Correlation",
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="impute_missing",
                variables=["q1", "q2"],
                strategy="median",
                reason="Check missingness before the correlation.",
            ),
            AnalysisStep(
                step_id="s2",
                kind="method",
                method="correlation",
                variables=["q1", "q2"],
                reason="The request named a correlation.",
            ),
            AnalysisStep(step_id="s3", kind="report", reason="Summarize."),
        ],
    )
    result = execute_workflow(
        original,
        workflow,
        [
            {"name": "q1", "value_labels": {}, "user_missing_values": []},
            {"name": "q2", "value_labels": {}, "user_missing_values": []},
        ],
    )
    impute = next(
        step for step in result["diagnostics"]["steps"] if step["kind"] == "impute_missing"
    )
    assert [item["filled"] for item in impute["detail"]["columns"]] == [0, 0]


def test_one_step_correlation_plan_runs() -> None:
    """A named correlation stays a method step plus the summary."""
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [1.0, 2.0, 2.0, 4.0]})
    workflow = AnalysisWorkflow(
        analysis_id="corr",
        objective="Correlation of x and y",
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="method",
                method="correlation",
                variables=["x", "y"],
                reason="The request named the method and the variables.",
            ),
            AnalysisStep(step_id="s2", kind="report", reason="Summarize."),
        ],
    )
    result = execute_workflow(
        frame,
        workflow,
        [
            {"name": "x", "value_labels": {}, "user_missing_values": []},
            {"name": "y", "value_labels": {}, "user_missing_values": []},
        ],
    )
    assert result["method"] == "correlation"
    assert result["sample_flow"]["valid_n"] == 4
    assert [step["kind"] for step in result["diagnostics"]["steps"]] == ["method", "report"]


def test_unknown_variable_is_rejected_before_the_sandbox() -> None:
    """A plan that names a missing column never starts a job."""
    workflow = AnalysisWorkflow(
        analysis_id="bad",
        objective="Cluster a column that is not on the file",
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="method",
                method="clustering",
                variables=["not_a_column", "q1"],
                k=2,
                reason="These were the requested features.",
            ),
            AnalysisStep(step_id="s2", kind="report", reason="Summarize."),
        ],
    )
    with pytest.raises(AppError) as caught:
        ensure_runnable(workflow, {"q1", "q2"})
    assert caught.value.code == "missing_variable"
    assert "not_a_column" in caught.value.message


def test_failed_script_does_not_publish(settings: Settings, tmp_path: Path) -> None:
    """A nonzero sandbox exit does not produce a result to publish."""
    job = tmp_path / "job"
    outcome = run_script(settings, job, "import sys\nsys.exit(1)\n", force_subprocess=True)
    assert outcome["exit_code"] != 0
    with pytest.raises(AppError) as caught:
        require_analysis_output(job, outcome)
    assert caught.value.code == "sandbox_failed"
    assert "No report was published" in caught.value.message
    assert not (job / "result.json").exists()


def test_named_regression_skips_the_planner() -> None:
    """A request that already names the regression roles does not ask the model to plan."""
    ready = direct_workflow(
        "Run a logistic regression of purchase on trust and age",
        {
            "method": "binary_logistic_regression",
            "dependent": "purchase",
            "predictors": ["trust", "age"],
        },
        "dataset-1",
    )
    assert ready is not None
    assert [step.kind for step in ready.steps] == ["method", "report"]
    assert ready.steps[0].dependent == "purchase"
    assert (
        direct_workflow(
            "Segment the agreement items",
            {"method": "clustering", "variables": ["q1", "q2"]},
            "dataset-1",
        )
        is None
    )


def test_planner_prompt_lists_metadata_not_rows() -> None:
    """The planner sees column facts and not a respondent's answers."""
    prompt = planner_prompt(
        "Segment the agreement items",
        [{"name": "q1", "missing_n": 6, "shape": "single"}],
        {"method": "clustering"},
        0,
    )
    assert "q1" in prompt
    assert "missing_n" in prompt
    assert "respondent rows" in prompt


def _two_groups() -> pd.DataFrame:
    """Return two well-separated numeric groups.

    Returns:
        Sixty-row frame.
    """
    rng = np.random.default_rng(1)
    return pd.DataFrame(
        {
            "x": np.concatenate([rng.normal(0, 0.1, 30), rng.normal(5, 0.1, 30)]),
            "y": np.concatenate([rng.normal(0, 0.1, 30), rng.normal(5, 0.1, 30)]),
        }
    )


def test_pam_gower_recovers_two_groups() -> None:
    """PAM with Gower distance runs and its sizes sum to the valid sample."""
    result = run_plan(
        _two_groups(),
        AnalysisPlan(
            analysis_id="pam",
            method="pam_gower",
            variables=["x", "y"],
            options={"k": 2},
            random_seed=1,
        ),
    )
    sizes = result.model_estimates["sizes"]
    assert sum(sizes.values()) == 60
    assert set(sizes) == {"0", "1"}
    assert result.metrics["silhouette"] > 0.5


def test_gower_mismatch_ignores_code_spacing() -> None:
    """Nominal codes use mismatch, so a wide code gap is not a larger distance."""
    data = pd.DataFrame({"city": [1.0, 2.0, 1.0, 9.0]})
    distance = gower_distance(data, {"city"})
    assert distance[0, 1] == pytest.approx(distance[0, 3])
    assert distance[0, 2] == pytest.approx(0.0)


def test_unknown_method_is_not_limited_to_the_old_list() -> None:
    """A named procedure without an implementation publishes nothing, and does not list a menu."""
    workflow = AnalysisWorkflow(
        analysis_id="latent",
        objective="Latent class",
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="method",
                method="latent_class",
                variables=["x", "y"],
                k=2,
                reason="The features are mixed.",
            ),
            AnalysisStep(step_id="s2", kind="report", reason="Summarize."),
        ],
    )
    with pytest.raises(AppError) as caught:
        ensure_runnable(workflow, {"x", "y"})
    assert caught.value.code == "unsupported_method"
    assert "Registered methods" not in caught.value.message
    assert "no result was published" in caught.value.message


def test_supplied_procedure_runs_and_a_file_read_is_refused() -> None:
    """A compute function can assign segments. A procedure that opens a file cannot."""
    source = (
        "def compute(data, seed):\n"
        "    labels = [0 if float(data.iloc[i]['x']) < 1 else 1 for i in range(len(data))]\n"
        "    return {'labels': labels, 'estimates': {}, 'metrics': {'split': 1}, 'warnings': []}\n"
    )
    workflow = AnalysisWorkflow(
        analysis_id="custom",
        objective="Split x at 1",
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="method",
                method="median_split",
                variables=["x", "y"],
                procedure=source,
                reason="The request named a procedure that is not built in.",
            ),
            AnalysisStep(step_id="s2", kind="report", reason="Summarize."),
        ],
    )
    ensure_runnable(workflow, {"x", "y"})
    payload = execute_workflow(_two_groups(), workflow, [])
    assert sum(payload["model_estimates"]["sizes"].values()) == 60
    blocked = workflow.model_copy(deep=True)
    blocked.steps[0].procedure = "def compute(data, seed):\n    return open('secret')\n"
    with pytest.raises(AppError) as caught:
        ensure_runnable(blocked, {"x", "y"})
    assert caught.value.code == "bad_plan"
