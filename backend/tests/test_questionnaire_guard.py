"""The validator corrects questionnaire logic before a draft is stored."""

import pytest

from app.schemas.expression import Comparison
from app.schemas.questionnaire import Option, Question, Questionnaire
from app.services.questionnaire_guard import blocking_logic, repair_questionnaire_logic
from tests.conftest import create_project


def _broken() -> Questionnaire:
    """Return a draft whose show-if rules name a punch and a hidden variable.

    Returns:
        Questionnaire that fails the logic check.
    """
    return Questionnaire(
        id="q1",
        title="Coffee",
        questions=[
            Question(
                id="Q1",
                type="multi_select",
                text="Which brands have you used?",
                options=[Option(code=1, label="Northstar"), Option(code=98, label="Other")],
            ),
            Question(
                id="Q2",
                type="single_select",
                text="Which brand have you used most often?",
                display_if=Comparison(op="eq", ref="Q3r99", value=0),
                options=[Option(code=1, label="Northstar")],
            ),
            Question(
                id="Q3",
                type="rating",
                text="How do you rate it?",
                display_if=Comparison(op="answered", ref="HV_MOST_BRAND"),
                options=[Option(code=1, label="Low")],
            ),
        ],
    )


def _fixed() -> Questionnaire:
    """Return the same draft with legal show-if rules.

    Returns:
        Questionnaire that passes the logic check.
    """
    document = _broken()
    document.questions[1].display_if = Comparison(op="answered", ref="Q1")
    document.questions[2].display_if = None
    return document


async def test_clean_logic_does_not_call_the_validator(settings, monkeypatch) -> None:
    """A valid draft is accepted without a correction call."""

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("The validator should not run for a clean draft.")

    monkeypatch.setattr("app.services.questionnaire_guard.run_structured", fail_if_called)
    _document, report, repairs = await repair_questionnaire_logic(
        settings,
        _fixed(),
        session_id="session",
        on_stage=lambda _message: None,
    )
    assert repairs == 0
    assert blocking_logic(report) == []


async def test_validator_corrects_punch_and_hidden_variable(settings, monkeypatch) -> None:
    """One validator pass removes both illegal conditions."""
    seen: dict[str, str] = {}

    async def fix(*_args, **kwargs):
        seen["role"] = kwargs["role"]
        seen["prompt"] = kwargs["prompt"]
        return _fixed()

    monkeypatch.setattr("app.services.questionnaire_guard.run_structured", fix)
    document, report, repairs = await repair_questionnaire_logic(
        settings,
        _broken(),
        session_id="session",
        on_stage=lambda _message: None,
    )
    assert repairs == 1
    assert seen["role"] == "validator"
    assert "Q3r99 equals 0" in seen["prompt"]
    assert "HV_MOST_BRAND" in seen["prompt"]
    assert blocking_logic(report) == []
    assert document.questions[1].display_if.ref == "Q1"


async def test_validator_stops_after_two_failed_corrections(settings, monkeypatch) -> None:
    """A draft that stays illegal is not corrected a third time."""
    calls = 0

    async def still_broken(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _broken()

    monkeypatch.setattr("app.services.questionnaire_guard.run_structured", still_broken)
    _document, report, repairs = await repair_questionnaire_logic(
        settings,
        _broken(),
        session_id="session",
        on_stage=lambda _message: None,
    )
    assert calls == 2
    assert repairs == 2
    assert any(issue.code == "bad_ref" for issue in blocking_logic(report))


def test_draft_is_stored_only_after_the_validator_corrects_it(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated punch label is corrected before the questionnaire is saved."""

    async def draft(*_args, **_kwargs):
        return _broken()

    async def fix(*_args, **kwargs):
        assert kwargs["role"] == "validator"
        return _fixed()

    monkeypatch.setattr("app.agents.orchestrator.run_structured", draft)
    monkeypatch.setattr("app.services.questionnaire_guard.run_structured", fix)
    project = create_project(client)
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Draft a questionnaire about home coffee"},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "completed", task
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "validator corrected" in messages[-1]["content"]
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    questionnaire = next(item for item in artifacts if item["type"] == "questionnaire")
    show_if = questionnaire["latest"]["content"]["questions"][1]["display_if"]
    assert show_if["ref"] == "Q1"
    assert "Q3r99" not in str(questionnaire["latest"]["content"])


def test_uncorrected_logic_is_not_stored(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """A draft the validator cannot fix is refused and is not saved."""

    async def draft(*_args, **_kwargs):
        return _broken()

    monkeypatch.setattr("app.agents.orchestrator.run_structured", draft)
    monkeypatch.setattr("app.services.questionnaire_guard.run_structured", draft)
    project = create_project(client)
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Draft a questionnaire about home coffee"},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "failed", task
    assert "Q3r99" in task["error"]
    assert "HV_MOST_BRAND" in task["error"]
    kinds = {item["type"] for item in client.get(f"/api/projects/{project['id']}/artifacts").json()}
    assert "questionnaire" not in kinds
