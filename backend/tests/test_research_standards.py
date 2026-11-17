"""Quant market research guardrails on plans and results."""

import numpy as np
import pandas as pd

from app.engines.analysis.guardrails import apply_standards
from app.engines.analysis.workflow import execute_workflow
from app.schemas.analysis import AnalysisStep, AnalysisWorkflow
from tests.test_multistep_analysis import _frame, _variables, _workflow


def _checks(result: dict, name: str) -> list[dict]:
    return [item for item in result["diagnostics"]["quality_checks"] if item["check"] == name]


def _plan(*steps: AnalysisStep, weight: str = "") -> AnalysisWorkflow:
    return AnalysisWorkflow(objective="t", steps=list(steps), weight_variable=weight)


def test_plan_standards_set_segment_range_and_driver_method() -> None:
    plan = _plan(
        AnalysisStep(step_id="s1", kind="method", method="clustering", variables=["a"], reason="x"),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="linear_regression",
            dependent="y",
            predictors=["a", "b"],
            reason="x",
        ),
    )
    fixed = apply_standards(plan, "Segment on a, and what drives y?", {"a", "b", "y", "weight"})
    cluster, driver, report = fixed.steps
    assert (cluster.k_min, cluster.k_max) == (4, 8)
    assert driver.method == "key_driver"
    assert report.kind == "report"
    text = " ".join(fixed.standards)
    assert "tests 4 to 8 segments" in text
    assert "no profile step" in text
    assert "weight" in text and "unweighted" in text


def test_plan_standards_keep_what_the_user_asked_for() -> None:
    plan = _plan(
        AnalysisStep(
            step_id="s1", kind="method", method="kmeans", k=3, variables=["a"], reason="x"
        ),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="linear_regression",
            dependent="y",
            predictors=["a"],
            reason="x",
        ),
        AnalysisStep(step_id="r", kind="report", reason="x"),
    )
    fixed = apply_standards(plan, "Run a regression of y to find drivers; use 3 clusters", set())
    assert fixed.steps[0].k == 3 and fixed.steps[0].k_min == 0
    assert fixed.steps[1].method == "linear_regression"
    assert any("k=3 was requested" in item for item in fixed.standards)
    assert len(fixed.steps) == 3


def test_segmentation_tests_four_to_eight_segments() -> None:
    plan = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="clustering",
            variables=[f"img{index}" for index in range(2, 7)],
            reason="x",
        ),
    )
    result = execute_workflow(_frame(), plan, _variables())
    chosen = result["diagnostics"]["chosen_k"]
    assert chosen["tested"] == [4, 8]
    assert set(chosen["silhouette_by_k"]) == {"4", "5", "6", "7", "8"}
    assert 4 <= result["metrics"]["k"] <= 8
    assert _checks(result, "Segment range")[0]["status"] == "pass"
    assert _checks(result, "Smallest segment")
    assert any(item.startswith("Tested 4 to 8 segments") for item in result["warnings"])


def test_driver_analysis_always_ranks_importance() -> None:
    plan = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="key_driver",
            dependent="nps",
            predictors=["img2", "img3", "img5", "img6"],
            reason="x",
        ),
    )
    result = execute_workflow(_frame(), plan, _variables())
    ranking = result["descriptive"]["importance_ranking"]
    assert [row["rank"] for row in ranking] == [1, 2, 3, 4]
    shares = [row["importance_pct"] for row in ranking]
    assert shares == sorted(shares, reverse=True)
    assert abs(sum(shares) - 100) < 1e-6
    weights = sum(item["relative_weight"] for item in result["model_estimates"].values())
    assert abs(weights - result["metrics"]["r_squared"]) < 1e-6
    assert _checks(result, "Importance ranking")[0]["status"] == "pass"
    assert _checks(result, "Collinearity")


def test_group_tests_report_post_hoc_effect_size_and_small_bases() -> None:
    frame = _frame()
    # Reason: region 3 gets only 12 respondents, under the reporting minimum of 30.
    keep = (
        frame.index[frame["region"] != 3].tolist() + frame.index[frame["region"] == 3][:12].tolist()
    )
    frame = frame.loc[keep]
    plan = _workflow(
        AnalysisStep(
            step_id="s1", kind="method", method="anova", dependent="nps", group="region", reason="x"
        ),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="chi_square",
            var_a="gender",
            var_b="region",
            reason="x",
        ),
    )
    result = execute_workflow(frame, plan, _variables())
    anova = result["descriptive"]["anova"]
    assert len(anova["post_hoc"]) == 3
    assert anova["groups"]["3"]["n"] == 12
    assert "anova_eta_squared" in result["metrics"]
    assert "chi_square_cramers_v" in result["metrics"]
    small = _checks(result, "Smallest group (3)")
    assert small and small[0]["status"] == "flag"
    assert any("too small to report" in item for item in result["warnings"])


def test_factor_analysis_checks_adequacy_and_weak_items() -> None:
    frame = _frame()
    frame["noise"] = np.random.default_rng(3).normal(size=len(frame))
    variables = [*_variables(), {"name": "noise", "value_labels": {}, "user_missing_values": []}]
    plan = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="efa",
            k=2,
            variables=[*(f"img{index}" for index in range(2, 7)), "noise"],
            reason="x",
        ),
    )
    result = execute_workflow(frame, plan, variables)
    assert result["metrics"]["kmo"] > 0.5
    assert result["metrics"]["bartlett_p_value"] < 0.05
    assert "noise" in result["metrics"]["weak_items"]
    assert _checks(result, "Item loadings")[0]["status"] == "flag"


def test_weight_that_a_method_ignores_is_flagged() -> None:
    frame = _frame()
    frame["weight"] = 1.0
    variables = [*_variables(), {"name": "weight", "value_labels": {}, "user_missing_values": []}]
    plan = _workflow(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="t_test",
            dependent="nps",
            group="gender",
            reason="x",
        ),
    ).model_copy(update={"weight_variable": "weight"})
    result = execute_workflow(frame, plan, variables)
    assert _checks(result, "Weighting")[0]["status"] == "flag"
    assert "cohens_d" in result["metrics"]
    assert pd.notna(result["metrics"]["p_value"])


def test_planner_written_standards_are_replaced_by_server_notes() -> None:
    plan = _plan(
        AnalysisStep(
            step_id="s1", kind="method", method="t_test", dependent="y", group="g", reason="x"
        ),
    ).model_copy(update={"standards": ["Require 30 per segment."]})
    fixed = apply_standards(plan, "Compare y by g", {"y", "g"})
    assert "Require 30 per segment." not in fixed.standards


def test_difference_questions_go_to_the_analysis_planner() -> None:
    from app.agents.intent import build_contract

    contract = build_contract(
        task_id="t",
        project_id="p",
        conversation_id="c",
        text="Does BrewCo recommendation likelihood Q14r1 differ by region S6?",
        variable_names=["Q14r1", "S6"],
        has_dataset=True,
    )
    assert contract.intent == "run_analysis"
    assert not contract.missing_required


def test_router_crosstab_choice_yields_to_a_difference_question() -> None:
    from app.agents.intent import build_contract

    contract = build_contract(
        task_id="t",
        project_id="p",
        conversation_id="c",
        text="Does Q14r1 differ by region S6?",
        variable_names=["Q14r1", "S6"],
        has_dataset=True,
        chosen_intent="run_crosstab",
    )
    assert contract.intent == "run_analysis"
    assert not contract.missing_required
