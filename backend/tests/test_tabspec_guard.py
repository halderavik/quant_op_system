"""The validator writes a tab spec only when each table has a base."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.engines.crosstab import run_table
from app.engines.tabspec_profile import build_profile
from app.schemas.expression import Comparison
from app.schemas.questionnaire import Option, Question, Questionnaire
from app.schemas.tabspec import PlanBanner, PlanExclusion, PlanTable, TabulationPlan
from app.services.tabspec_guard import author_executable_tabspec
from tests.conftest import create_project

ROOT_SAV = Path(__file__).resolve().parents[2] / "fixtures" / "survey_small.sav"


def _variables(*names: tuple[str, str, dict[str, str]]) -> list[dict]:
    """Build a small variable dictionary.

    Args:
        *names: Name, label, and value labels for each column.

    Returns:
        Dictionary entries.
    """
    return [
        {
            "name": name,
            "label": label,
            "value_labels": labels,
            "user_missing_values": [],
            "is_text": False,
        }
        for name, label, labels in names
    ]


async def test_multi_family_uses_the_punch_in_the_data(settings, monkeypatch) -> None:
    """An empty question id is not tabulated. The punch columns are, with their real code."""
    frame = pd.DataFrame(
        {
            "Q1": [None, None, None, None],
            "Q1r1": [2, None, 2, None],
            "Q1r2": [None, 2, 2, None],
            "gender": [1, 1, 2, 2],
        }
    )
    variables = _variables(
        ("Q1", "Brands", {}),
        ("Q1r1", "North", {"2": "North"}),
        ("Q1r2", "South", {"2": "South"}),
        ("gender", "Gender", {"1": "Male", "2": "Female"}),
    )
    questionnaire = Questionnaire(
        id="q1",
        title="Brands",
        questions=[
            Question(
                id="Q1",
                type="multi_select",
                text="Which brands have you used?",
                variable_names=["Q1r1", "Q1r2"],
                options=[Option(code=1, label="North"), Option(code=2, label="South")],
            ),
            Question(
                id="S1",
                type="single_select",
                text="Gender",
                variable_names=["gender"],
                options=[Option(code=1, label="Male"), Option(code=2, label="Female")],
            ),
        ],
    )
    profile = build_profile(frame, variables, questionnaire)
    by_name = {column.name: column for column in profile.columns}
    assert by_name["Q1"].shape == "empty"
    assert by_name["Q1r1"].shape == "multi"
    assert by_name["Q1r1"].family == "Q1"
    assert profile.families[0].members == ["Q1r1", "Q1r2"]

    async def plan(*_args, **kwargs):
        assert kwargs["role"] == "validator"
        assert "Q1r1" in kwargs["prompt"]
        return TabulationPlan(
            banners=[PlanBanner(variable_name="gender", plan="A", codes=[1, 2])],
            tables=[
                PlanTable(
                    title="Brands",
                    row_variable_names=["Q1r1", "Q1r2"],
                    table_type="multiple_response",
                    selected_codes=[2],
                    banner_plans=["A"],
                    base="All",
                )
            ],
            exclusions=[PlanExclusion(name="Q1", reason="Empty (n=0)")],
        )

    monkeypatch.setattr("app.services.tabspec_guard.run_structured", plan)
    spec, report, repairs = await author_executable_tabspec(
        settings,
        frame=frame,
        variables=variables,
        questionnaire=questionnaire,
        dataset_id="d1",
        questionnaire_ref=None,
        weight_variable=None,
        session_id="session",
        on_stage=lambda _message: None,
    )
    table = spec.tables[0]
    assert repairs == 1
    assert report.status == "passed"
    assert table.table_type == "multiple_response"
    assert table.row_variable_names == ["Q1r1", "Q1r2"]
    assert table.selected_codes == [2]
    assert spec.exclusions == [{"question_id": "Q1", "reason": "Empty (n=0)"}]
    result = run_table(frame, variables, table, spec.study_defaults, spec.banners)
    punched = int(((frame["Q1r1"] == 2) | (frame["Q1r2"] == 2)).sum())
    assert result.rows[0].cells["total"].unweighted_base == punched
    assert result.rows[0].cells["total"].unweighted_numerator > 0


async def test_base_that_matches_nobody_becomes_all(settings, monkeypatch) -> None:
    """A display rule that keeps no rows is stored as All, and the table base is not zero."""
    frame = pd.DataFrame({"trust": [1, 2, 1, 2], "gender": [1, 2, 1, 2]})
    variables = _variables(
        ("trust", "Trust", {"1": "Low", "2": "High"}),
        ("gender", "Gender", {"1": "Male", "2": "Female"}),
    )
    questionnaire = Questionnaire(
        id="q1",
        title="Trust",
        questions=[
            Question(
                id="Q1",
                type="single_select",
                text="How much do you trust it?",
                variable_names=["trust"],
                display_if=Comparison(op="eq", ref="gender", value=9),
                options=[Option(code=1, label="Low"), Option(code=2, label="High")],
            )
        ],
    )

    async def plan(*_args, **_kwargs):
        return TabulationPlan(
            banners=[PlanBanner(variable_name="gender", plan="A", codes=[1, 2])],
            tables=[
                PlanTable(
                    title="Trust",
                    row_variable_names=["trust"],
                    table_type="categorical",
                    banner_plans=["A"],
                    base="gender = 9",
                )
            ],
        )

    monkeypatch.setattr("app.services.tabspec_guard.run_structured", plan)
    spec, _report, repairs = await author_executable_tabspec(
        settings,
        frame=frame,
        variables=variables,
        questionnaire=questionnaire,
        dataset_id="d1",
        questionnaire_ref=None,
        weight_variable=None,
        session_id="session",
        on_stage=lambda _message: None,
    )
    table = spec.tables[0]
    assert repairs == 1
    assert table.base_text == "All"
    assert table.base.filter is None
    assert any("matched no respondents" in note for note in table.notes)
    result = run_table(frame, variables, table, spec.study_defaults, spec.banners)
    assert result.rows[0].cells["total"].unweighted_base == len(frame)


def test_unknown_variable_is_not_stored(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan that names a missing column is refused, and no tab spec is saved."""
    calls = 0

    async def missing(*_args, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["role"] == "validator"
        return TabulationPlan(
            tables=[
                PlanTable(
                    title="Missing",
                    row_variable_names=["NOT_A_COLUMN"],
                    table_type="categorical",
                )
            ]
        )

    monkeypatch.setattr("app.services.tabspec_guard.run_structured", missing)
    project = create_project(client)
    with ROOT_SAV.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("survey_small.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "build a tab spec"},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "failed", task
    assert calls == 2
    assert "NOT_A_COLUMN" in task["error"]
    assert "did not save" in task["error"]
    kinds = {item["type"] for item in client.get(f"/api/projects/{project['id']}/artifacts").json()}
    assert "tabspec" not in kinds
