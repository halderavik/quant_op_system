"""One project walks the core research path without a live model key."""

from pathlib import Path

import pytest

from app.engines.coding_agg import merge_checkpoint
from app.schemas.coding import Codeframe, CodeNode, CodingAssignment, NetNode
from app.schemas.questionnaire import Module, Objective, Option, Question, Questionnaire
from app.services.documents import aggregate_saved_coding
from tests.conftest import create_project

ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def _ask(client, project: dict, content: str) -> dict:
    """Send a chat turn and return the finished task.

    Args:
        client: Test client.
        project: Project payload.
        content: User message.

    Returns:
        Task JSON.
    """
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": content},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] in {"completed", "completed_with_warnings"}, task
    return task


def _upload(client, project_id: str, path: Path) -> str:
    """Upload an SPSS file and return the dataset id.

    Args:
        client: Test client.
        project_id: Project id.
        path: SAV path.

    Returns:
        Dataset id.
    """
    with path.open("rb") as handle:
        response = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def test_one_project_covers_the_core_journeys(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Notes, tables, a spec, a questionnaire, a model, coding, and a chart persist together."""
    project = create_project(client)
    _ask(client, project, "Remember that the project codename is Aurora")
    _ask(client, project, "What project codename did I give you?")
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "Aurora" in messages[-1]["content"]

    small_id = _upload(client, project["id"], ROOT / "survey_small.sav")
    _ask(client, project, "trust by gender weighted using weight")
    _ask(client, project, "chart the latest table")
    _ask(client, project, "Build a tab spec")

    async def _questionnaire(*_args, **_kwargs):
        return Questionnaire(
            id="q1",
            title="Brand trust",
            objectives=[Objective(id="o1", description="Measure trust", question_ids=["Q1"])],
            modules=[Module(id="m1", title="Core", question_ids=["Q1"])],
            questions=[
                Question(
                    id="Q1",
                    type="single_select",
                    text="How much do you trust the brand?",
                    options=[Option(code=1, label="Low"), Option(code=2, label="High")],
                )
            ],
        )

    monkeypatch.setattr("app.agents.orchestrator.run_structured", _questionnaire)
    _ask(client, project, "Draft a survey about brand trust")

    analysis_id = _upload(client, project["id"], ROOT / "survey_analysis.sav")
    switched = client.patch(
        f"/api/projects/{project['id']}",
        json={"active_dataset_id": analysis_id},
    )
    assert switched.status_code == 200, switched.text
    _ask(client, project, "Run a logistic regression of purchase on trust and age")
    back = client.patch(f"/api/projects/{project['id']}", json={"active_dataset_id": small_id})
    assert back.status_code == 200, back.text

    codeframe = Codeframe(
        codeframe_id="cf",
        response_variable="comment",
        respondent_id_variable="respondent_id",
        codes=[CodeNode(id="C01", label="Quality")],
        nets=[NetNode(id="N01", label="Any", child_ids=["C01"])],
    )
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "type": "codeframe",
            "name": "Comments",
            "content": codeframe.model_dump(mode="json"),
        },
    )
    assert created.status_code == 201, created.text

    async def _code(_settings, frame, prompt, _session_id, existing=None):
        rows = []
        for line in prompt.splitlines():
            if "\t" not in line:
                continue
            source, text = line.split("\t", 1)
            if not source.isdigit():
                continue
            rows.append(
                CodingAssignment(
                    respondent_id=source,
                    source_row_id=int(source),
                    response_text=text,
                    assigned_code_ids=["C01"],
                    sentiment="positive",
                )
            )
        merged = merge_checkpoint(existing or [], rows)
        _report, cleaned = aggregate_saved_coding(frame, merged)
        return cleaned, _report

    monkeypatch.setattr("app.services.coding_run.code_batch", _code)
    _ask(
        client,
        project,
        "code the open-end column comment using respondent id respondent_id",
    )
    kinds = {item["type"] for item in client.get(f"/api/projects/{project['id']}/artifacts").json()}
    assert {"crosstab", "chart", "tabspec", "questionnaire", "analysis", "coding"} <= kinds
