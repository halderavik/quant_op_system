"""Learning events from questionnaire edits, analysis follow-ups, downloads, and ratings."""

from pathlib import Path

from app.learning.diff import questionnaire_diff
from tests.conftest import create_project

ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def _scale(points: int, dont_know: bool = False) -> list[dict]:
    options = [{"code": code, "label": f"{code}"} for code in range(1, points + 1)]
    if dont_know:
        options.append({"code": 97, "label": "Don't know", "exclusive": True})
    return options


def _questionnaire(questions: list[dict], title: str = "Coffee brand health tracker") -> dict:
    return {
        "id": "qn",
        "title": title,
        "objectives": [{"id": "o1", "description": "Measure brand awareness and consideration"}],
        "questions": questions,
    }


def _q(qid: str, text: str, kind: str = "single_select", options: list | None = None) -> dict:
    return {"id": qid, "type": kind, "text": text, "options": options or []}


BEFORE = _questionnaire(
    [
        _q("S1", "How old are you?", "numeric"),
        _q("Q1", "Which coffee brands have you heard of?", "multi_select", _scale(4)),
        _q("Q2", "How likely are you to recommend BrewCo?", "rating", _scale(10)),
        _q("Q3", "Why did you give that score?", "text"),
        _q("Q4", "What is your household income?", "single_select", _scale(5)),
    ]
)
AFTER = _questionnaire(
    [
        _q("S1", "How old are you?", "numeric"),
        _q("Q1A", "Which coffee brands have you heard of?", "multi_select", _scale(4)),
        _q("Q1B", "Which of these brands have you heard of? (aided)", "multi_select", _scale(4)),
        _q("Q4", "What is your household income?", "single_select", _scale(5)),
        _q(
            "Q2",
            "How likely are you to recommend BrewCo to a friend?",
            "rating",
            _scale(5, dont_know=True),
        ),
    ]
)


def test_questionnaire_diff_reads_question_level_changes() -> None:
    diff = questionnaire_diff(BEFORE, AFTER)
    assert [item["id"] for item in diff["added"]] == ["Q1B"]
    assert diff["added"][0]["after_id"] == "Q1A"
    assert [item["id"] for item in diff["removed"]] == ["Q3"]
    changed = {item["id"]: item for item in diff["modified"]}
    assert changed["Q1A"]["renamed_from"] == "Q1"
    q2 = changed["Q2"]
    assert "text" in q2
    assert q2["options"]["scale_points"] == {"before": 10, "after": 5}
    assert q2["options"]["dont_know_added"] == ["Don't know"]
    assert [item["id"] for item in diff["moved"]] in (["Q2"], ["Q4"])
    assert any("scale 10 to 5 points" in line for line in diff["summary"])
    assert questionnaire_diff(BEFORE, BEFORE)["summary"] == []


def _events(client, project_id: str, kind: str | None = None) -> list[dict]:
    query = f"?kind={kind}" if kind else ""
    return client.get(f"/api/projects/{project_id}/learning-events{query}").json()


def test_a_user_edit_to_an_agent_questionnaire_is_recorded_with_context(client) -> None:
    project = create_project(client)
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "type": "questionnaire",
            "name": "Draft",
            "content": BEFORE,
            "created_by": "questionnaire",
        },
    )
    assert created.status_code == 201, created.text
    artifact_id = (
        created.json()["artifact_id"] if "artifact_id" in created.json() else created.json()["id"]
    )
    saved = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": AFTER, "expected_version": 1},
    )
    assert saved.status_code == 201, saved.text
    events = _events(client, project["id"], "questionnaire_edit")
    assert len(events) == 1
    event = events[0]
    assert (event["from_version"], event["to_version"], event["actor"]) == (1, 2, "user")
    assert event["payload"]["previous_author"] == "questionnaire"
    assert event["payload"]["counts"]["added"] == 1
    assert "brand_health" in event["context"]["study_types"]
    unchanged = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": AFTER, "expected_version": 2},
    )
    assert unchanged.status_code == 201
    assert len(_events(client, project["id"], "questionnaire_edit")) == 1


def test_ratings_and_downloads_are_recorded(client) -> None:
    project = create_project(client)
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"type": "note", "name": "Note", "content": {"text": "hi"}},
    )
    artifact_id = created.json().get("artifact_id") or created.json()["id"]
    rated = client.post(
        f"/api/artifacts/{artifact_id}/feedback",
        json={"rating": "down", "note": "Too long for a 10 minute survey"},
    )
    assert rated.status_code == 201, rated.text
    event = _events(client, project["id"], "feedback")[0]
    assert event["payload"] == {"rating": "down"}
    assert event["instruction"] == "Too long for a 10 minute survey"
    assert (
        client.post(f"/api/artifacts/{artifact_id}/feedback", json={"rating": "meh"}).status_code
        == 422
    )
    with (ROOT / "survey_analysis.sav").open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("survey_analysis.sav", handle, "application/octet-stream")},
        )
    file_id = uploaded.json().get("file_id") or uploaded.json().get("id")
    assert client.get(f"/api/files/{file_id}/download").status_code == 200
    downloads = _events(client, project["id"], "download")
    assert downloads and downloads[0]["payload"]["filename"] == "survey_analysis.sav"


def test_a_second_analysis_in_a_row_is_recorded_as_a_follow_up(client) -> None:
    project = create_project(client)
    with (ROOT / "survey_analysis.sav").open("rb") as handle:
        client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("survey_analysis.sav", handle, "application/octet-stream")},
        )
    for text in (
        "Run a logistic regression of purchase on trust and age",
        "Run a linear regression of trust on age",
    ):
        sent = client.post(
            f"/api/conversations/{project['conversation_id']}/messages", json={"content": text}
        )
        task = client.get(f"/api/tasks/{sent.json()['task_id']}").json()
        assert task["status"] in {"completed", "completed_with_warnings"}, task
    first = _events(client, project["id"], "analysis_run")
    follow = _events(client, project["id"], "analysis_followup")
    assert len(first) == 1 and len(follow) == 1
    assert first[0]["context"]["insight_types"] == ["regression"]
    assert follow[0]["instruction"] == "Run a linear regression of trust on age"
    previous = follow[0]["payload"]["previous"]["plan"]
    assert any(step.get("method") == "binary_logistic_regression" for step in previous)


def test_a_project_can_opt_out(client) -> None:
    project = create_project(client)
    client.patch(
        f"/api/projects/{project['id']}", json={"study_context": {"learning_opt_out": True}}
    )
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "type": "questionnaire",
            "name": "D",
            "content": BEFORE,
            "created_by": "questionnaire",
        },
    )
    artifact_id = created.json().get("artifact_id") or created.json()["id"]
    client.post(
        f"/api/artifacts/{artifact_id}/revisions", json={"content": AFTER, "expected_version": 1}
    )
    assert _events(client, project["id"]) == []


def test_a_questionnaire_edit_asked_for_in_chat_keeps_the_request(client, monkeypatch) -> None:
    from app.schemas.questionnaire import Questionnaire

    replies = [Questionnaire.model_validate(BEFORE), Questionnaire.model_validate(AFTER)]

    async def _model(*_args, **_kwargs):
        return replies.pop(0)

    monkeypatch.setattr("app.agents.orchestrator.run_structured", _model)
    project = create_project(client)
    for text in (
        "Draft a survey about coffee brand health",
        "Add an aided awareness question after Q1 and make Q2 a 5-point scale with Don't know",
    ):
        sent = client.post(
            f"/api/conversations/{project['conversation_id']}/messages", json={"content": text}
        )
        task = client.get(f"/api/tasks/{sent.json()['task_id']}").json()
        assert task["status"] in {"completed", "completed_with_warnings"}, task
    events = _events(client, project["id"], "questionnaire_edit")
    assert len(events) == 1
    assert events[0]["actor"] == "chat"
    assert events[0]["instruction"].startswith("Add an aided awareness question")
    assert events[0]["payload"]["counts"]["added"] == 1
