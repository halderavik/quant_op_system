"""Chained methods, subgroup fits, filters, bands, and off-scale codes."""

import numpy as np
import pandas as pd
import pytest

from app.agents.intent_roles import fill_roles
from app.engines.analysis.compile import direct_workflow, ensure_runnable
from app.engines.analysis.report import build_report, claims_match_result
from app.engines.analysis.workbook import workbook_bytes
from app.engines.analysis.workflow import execute_workflow
from app.errors import AppError
from app.schemas.analysis import AnalysisResult, AnalysisStep, AnalysisWorkflow, Band

_SCALE = {
    "1": "Poor",
    "2": "Fair",
    "3": "Good",
    "4": "Very good",
    "5": "Excellent",
    "97": "Don't know enough to say",
}


def _variables() -> list[dict]:
    """Return a dictionary where 97 is labeled but not declared missing."""
    items = [
        {"name": f"img{index}", "value_labels": dict(_SCALE), "user_missing_values": []}
        for index in range(1, 7)
    ]
    return items + [
        {"name": "nps", "value_labels": {}, "user_missing_values": []},
        {"name": "age", "value_labels": {}, "user_missing_values": []},
        {
            "name": "gender",
            "value_labels": {"1": "Male", "2": "Female"},
            "user_missing_values": [],
        },
        {
            "name": "region",
            "value_labels": {"1": "North", "2": "South", "3": "West"},
            "user_missing_values": [],
        },
    ]


def _frame(rows: int = 400) -> pd.DataFrame:
    """Two attitude factors drive six ratings; some answers are "Don't know" (97)."""
    rng = np.random.default_rng(7)
    first = rng.normal(size=rows)
    second = rng.normal(size=rows)
    data: dict[str, np.ndarray] = {}
    for index in range(1, 7):
        driver = first if index <= 3 else second
        raw = 3 + 1.1 * driver + rng.normal(scale=0.6, size=rows)
        data[f"img{index}"] = np.clip(np.round(raw), 1, 5)
    gender = rng.integers(1, 3, rows).astype(float)
    # Reason: the first factor matters more for men and the second for women.
    weight_first = np.where(gender == 1, 2.0, 0.3)
    weight_second = np.where(gender == 1, 0.3, 2.0)
    data["nps"] = np.clip(
        np.round(5 + weight_first * first + weight_second * second + rng.normal(size=rows)), 0, 10
    )
    data["age"] = rng.integers(18, 66, rows).astype(float)
    data["gender"] = gender
    data["region"] = rng.integers(1, 4, rows).astype(float)
    frame = pd.DataFrame(data)
    frame.loc[rng.choice(rows, 30, replace=False), "img1"] = 97.0
    return frame


def _workflow(*steps: AnalysisStep) -> AnalysisWorkflow:
    """Wrap steps in a plan with a report step at the end."""
    return AnalysisWorkflow(
        analysis_id="a1",
        objective="test",
        steps=[*steps, AnalysisStep(step_id="r", kind="report", reason="report")],
    )


def _columns() -> set[str]:
    return {item["name"] for item in _variables()}


def test_dont_know_is_not_a_top_box_rating_and_is_imputed() -> None:
    frame = _frame()
    plan = _workflow(
        AnalysisStep(
            step_id="s1", kind="impute_missing", variables=["img1"], strategy="median", reason="x"
        ),
        AnalysisStep(step_id="s2", kind="top_box", variables=["img1"], reason="x"),
        AnalysisStep(
            step_id="s3", kind="method", method="descriptive", variables=["img1"], reason="x"
        ),
    )
    result = execute_workflow(frame, plan, _variables())
    steps = {step["kind"]: step["detail"] for step in result["diagnostics"]["steps"]}
    assert steps["top_box"]["columns"][0]["codes"] == [4.0, 5.0]
    assert steps["impute_missing"]["columns"][0]["filled"] == 30
    assert any("Treated code 97 (Don't know enough to say)" in item for item in result["warnings"])


def test_factor_scores_feed_a_regression() -> None:
    plan = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="efa",
            variables=["img*"],
            output="F",
            reason="x",
        ),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="linear_regression",
            dependent="nps",
            predictors=["F*"],
            reason="x",
        ),
    )
    ensure_runnable(plan, _columns())
    result = execute_workflow(_frame(), plan, _variables())
    assert result["method"] == "multi_step"
    assert result["metrics"]["linear_regression_r_squared"] > 0.3
    assert {"linear_regression_F1", "linear_regression_F2"} <= set(result["model_estimates"])
    report = build_report("test", AnalysisResult.model_validate(result))
    assert claims_match_result(report, result) == []


def test_key_drivers_run_per_group_and_compare() -> None:
    plan = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="key_driver",
            dependent="nps",
            predictors=["img2", "img5"],
            split_by="gender",
            reason="x",
        ),
    )
    ensure_runnable(plan, _columns())
    result = execute_workflow(_frame(), plan, _variables())
    assert result["method"] == "key_driver"
    block = result["diagnostics"]["comparisons"][0]
    assert block["groups"] == ["Male", "Female"]
    share = {
        row["term"]: row["values"] for row in block["rows"] if row["field"] == "importance_pct"
    }
    assert share["img2"]["Male"] > share["img2"]["Female"]
    assert share["img5"]["Female"] > share["img5"]["Male"]
    assert result["sample_flow"]["valid_n"] == sum(block["bases"].values())
    book = workbook_bytes(plan, result, build_report("t", AnalysisResult.model_validate(result)))
    assert book[:2] == b"PK"


def test_bands_feed_anova_and_chi_square_inside_a_filter() -> None:
    plan = _workflow(
        AnalysisStep(
            step_id="s0", kind="filter", variables=["region"], codes=["1", "2"], reason="x"
        ),
        AnalysisStep(
            step_id="s1",
            kind="band",
            variables=["age"],
            output="age_band",
            bands=[
                Band(label="18-34", lower=18, upper=34),
                Band(label="35-49", lower=35, upper=49),
                Band(label="50-65", lower=50, upper=65),
            ],
            reason="x",
        ),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="anova",
            dependent="nps",
            group="age_band",
            reason="x",
        ),
        AnalysisStep(
            step_id="s3",
            kind="method",
            method="chi_square",
            var_a="age_band",
            var_b="gender",
            reason="x",
        ),
    )
    ensure_runnable(plan, _columns())
    frame = _frame()
    result = execute_workflow(frame, plan, _variables())
    kept = int(frame["region"].isin([1, 2]).sum())
    band = next(step for step in result["diagnostics"]["steps"] if step["kind"] == "band")
    assert sum(item["n"] for item in band["detail"]["bands"]) == kept
    assert result["diagnostics"]["methods"][0]["sample_flow"]["input_n"] == kept
    assert any(key.startswith("chi_square_") for key in result["metrics"])
    assert any(key.startswith("anova_") for key in result["metrics"])
    assert any("where region is North or South" in item for item in result["warnings"])


def test_plan_checks_follow_step_order() -> None:
    late = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="anova",
            dependent="nps",
            group="age_band",
            reason="x",
        ),
    )
    with pytest.raises(AppError, match="age_band"):
        ensure_runnable(late, _columns())
    unsaved = _workflow(
        AnalysisStep(step_id="s1", kind="method", method="efa", variables=["img1"], reason="x"),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="linear_regression",
            dependent="nps",
            predictors=["F*"],
            reason="x",
        ),
    )
    with pytest.raises(AppError, match="F\\*"):
        ensure_runnable(unsaved, _columns())


def test_multi_step_requests_reach_the_planner() -> None:
    text = (
        "Group S2 age into 18-34, 35-49 and 50-65, then run an ANOVA of Q14r1 by those age "
        "groups and a chi-square test of the age groups against S6 region."
    )
    fields: dict = {}
    missing: list[str] = []
    fill_roles(text, fields, missing, "chi_square")
    assert missing == []
    hints = {"method": "chi_square", "var_a": "S2", "var_b": "S6"}
    assert direct_workflow(text, hints, "d1") is None
    simple: list[str] = []
    fill_roles("Run a chi-square test", {}, simple, "chi_square")
    assert simple == ["var_a", "var_b"]


def test_common_method_names_map_to_built_in_methods() -> None:
    plan = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="factor analysis",
            variables=["img*"],
            output="F",
            reason="x",
        ),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="regression",
            dependent="nps",
            predictors=["F*"],
            reason="x",
        ),
    )
    ensure_runnable(plan, _columns())
    result = execute_workflow(_frame(), plan, _variables())
    assert "linear_regression_r_squared" in result["metrics"]
