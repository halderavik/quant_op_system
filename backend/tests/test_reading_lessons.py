"""Learning to read questionnaire files: from the importer's own fixes and from people's corrections."""

import pytest

from app.learning.lessons import correction_pairs
from app.schemas.questionnaire import Option, Question, Questionnaire
from app.services.questionnaire_import import QuestionnaireFrame
from tests.conftest import create_project
from tests.test_questionnaire_import import DOCX_TYPE, _questionnaire_docx, _section_from


def test_wording_and_lists_are_reading_lessons_logic_is_not() -> None:
    """A changed option list or type teaches reading; a changed base teaches programming."""
    from app.schemas.expression import Comparison

    planned = Questionnaire(
        id="p",
        title="T",
        questions=[
            Question(
                id="Q1",
                type="single_select",
                text="Which brands?",
                options=[Option(code=1, label="A"), Option(code=2, label="B")],
            )
        ],
    )
    approved = planned.model_copy(deep=True)
    approved.questions[0] = approved.questions[0].model_copy(
        update={
            "type": "multi_select",
            "options": [Option(code=1, label="A"), Option(code=99, label="None")],
            "display_if": Comparison(op="answered", ref="Q0"),
        }
    )
    stages = {(pair["stage"], pair["field"]) for pair in correction_pairs(planned, approved)}
    assert ("extraction", "type") in stages
    assert ("extraction", "options") in stages
    assert ("programming", "display_if") in stages


def test_the_importer_learns_from_its_own_fix_and_uses_it_next_time(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A section misread then fixed on the retry becomes a reading rule; the next import is given it."""
    prompts: list[str] = []

    def _fake_factory(wrong_first: list[bool]):
        async def _fake(*_args, **kwargs):
            prompts.append(kwargs["prompt"])
            if kwargs["output_type"] is QuestionnaireFrame:
                return QuestionnaireFrame(title="Coffee Habits Study")
            return _section_from(kwargs["prompt"], wrong_first)

        return _fake

    for name, wrong_first in (("First", [True]), ("Second", [False])):
        project = create_project(client, name)
        upload = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("coffee.docx", _questionnaire_docx(), DOCX_TYPE)},
        )
        monkeypatch.setattr(
            "app.services.questionnaire_import.run_structured", _fake_factory(wrong_first)
        )
        prompts.clear()
        response = client.post(
            f"/api/conversations/{project['conversation_id']}/messages",
            json={"content": "Use this questionnaire", "file_ids": [upload.json()["file_id"]]},
        )
        task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
        assert task["status"] in {"completed", "completed_with_warnings"}, task
        if name == "First":
            lessons = client.get("/api/learning/programming-lessons").json()
            reading = [lesson for lesson in lessons if lesson["stage"] == "extraction"]
            assert reading, "the first read's mistake should be stored as a reading rule"
            assert "drink coffee" in reading[0]["example_instruction"]
    # The second import of a similar file is told what was learned from the first.
    assert any("LESSONS FROM QUESTIONNAIRES READ BEFORE" in prompt for prompt in prompts)
