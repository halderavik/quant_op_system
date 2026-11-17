"""Learning programming rules from corrections made before a survey is programmed."""

import asyncio

import pytest

from app.learning.lessons import (
    active_lessons,
    correction_pairs,
    learn_from_approval,
    relevant_lessons,
)
from app.repositories.records import ArtifactRepository
from app.schemas.expression import Comparison
from app.schemas.questionnaire import (
    Option,
    ProgrammingSpec,
    Question,
    Questionnaire,
    RowCondition,
)
from app.services import programming_spec
from tests.conftest import create_project


class _NoModel:
    """Settings with no model key: rules are written from the correction itself."""

    llm_configured = False
    anthropic_api_key = ""


def _planned() -> Questionnaire:
    """The system's plan: brand rows filtered with a show-if instead of row piping."""
    return Questionnaire(
        id="p",
        title="Ad test",
        questions=[
            Question(
                id="qAID",
                type="grid",
                text="Have you heard of these brands?",
                matrix_items=["Boursin", "Alouette"],
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
                programming=ProgrammingSpec(),
            ),
            Question(
                id="qFAM",
                type="grid",
                text="How familiar are you with each brand?",
                matrix_items=["Boursin", "Alouette"],
                options=[Option(code=1, label="Very"), Option(code=2, label="Not at all")],
                programmer_notes=["ASK BRANDS AWARE IN qAID"],
                display_if=Comparison(op="answered", ref="qAID"),
                programming=ProgrammingSpec(unresolved=["Check the brand list"]),
            ),
        ],
    )


def _approved() -> Questionnaire:
    """What the person approved: row piping from qAID's Yes column, to-do ticked off."""
    document = _planned()
    fixed = document.questions[1].model_copy(
        update={
            "display_if": None,
            "programming": ProgrammingSpec(row_condition=RowCondition(source="qAID", column=1)),
        }
    )
    return document.model_copy(update={"questions": [document.questions[0], fixed]})


def test_corrections_are_logic_changes_not_ticked_todos() -> None:
    """The base and the row piping are corrections; marking a to-do done is not."""
    pairs = correction_pairs(_planned(), _approved())
    fields = sorted(pair["field"] for pair in pairs)
    assert fields == ["display_if", "programming.row_condition"]
    assert all(pair["instruction"] == "ASK BRANDS AWARE IN qAID" for pair in pairs)


def _save(client, project_id: str, document: Questionnaire, author: str) -> str:
    db = client.app.state.session_factory()
    try:
        repo = ArtifactRepository(db)
        existing = repo.latest_of_type(project_id, "questionnaire")
        revision = repo.create(
            project_id=project_id,
            artifact_type="questionnaire",
            name=document.title,
            content=document.model_dump(mode="json"),
            content_schema="questionnaire/1",
            created_by=author,
            artifact_id=existing.artifact_id if existing else None,
            expected_version=existing.version if existing else None,
        )
        db.commit()
        return revision.artifact_id
    finally:
        db.close()


def test_approval_stores_a_lesson_and_the_next_plan_uses_it(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correction becomes a lesson; seeing it again adds support; the planner is told about it."""
    project = create_project(client, "Learning")
    artifact_id = _save(client, project["id"], _planned(), "questionnaire_import")
    _save(client, project["id"], _approved(), "user")
    db = client.app.state.session_factory()
    try:
        learned = asyncio.run(
            learn_from_approval(db, _NoModel(), project["id"], artifact_id, _approved(), "s")
        )
        db.commit()
        assert learned == 2
        again = asyncio.run(
            learn_from_approval(db, _NoModel(), project["id"], artifact_id, _approved(), "s")
        )
        db.commit()
        assert again == 2
        lessons = active_lessons(db)
    finally:
        db.close()
    assert {lesson["support"] for lesson in lessons} == {2}
    assert any("row_condition" in lesson["rule"] for lesson in lessons)

    listed = client.get("/api/learning/programming-lessons").json()
    assert len(listed) == 2
    off = client.patch(
        f"/api/learning/programming-lessons/{listed[0]['id']}", json={"status": "disabled"}
    )
    assert off.json()["status"] == "disabled"

    new_question = Question(
        id="Q7",
        type="grid",
        text="How do you rate each brand?",
        matrix_items=["A", "B"],
        options=[Option(code=1, label="Good")],
        programmer_notes=["ASK BRANDS AWARE IN Q6"],
    )
    chosen = relevant_lessons(lessons, [new_question])
    assert chosen, "a similar instruction should bring back the lesson"
    seen: dict[str, str] = {}

    async def _fake(*_args, **kwargs):
        seen["prompt"] = kwargs["prompt"]
        return programming_spec.PlanBatch()

    monkeypatch.setattr(programming_spec, "run_structured", _fake)
    document = Questionnaire(id="n", title="Next", questions=[new_question])
    asyncio.run(
        programming_spec._plan_batch(
            _NoModel(), document, [new_question], None, "s", asyncio.Semaphore(1), lessons
        )
    )
    assert "LESSONS FROM SURVEYS PEOPLE CORRECTED" in seen["prompt"]
    assert "ASK BRANDS AWARE IN qAID" in seen["prompt"]


def test_opted_out_projects_teach_nothing(client) -> None:
    """A project that opts out of learning stores no lessons."""
    project = create_project(client, "Private")
    client.patch(
        f"/api/projects/{project['id']}", json={"study_context": {"learning_opt_out": True}}
    )
    artifact_id = _save(client, project["id"], _planned(), "questionnaire_import")
    db = client.app.state.session_factory()
    try:
        from app.models.tables import Project

        row = db.get(Project, project["id"])
        row.study_context = {**(row.study_context or {}), "learning_opt_out": True}
        db.commit()
        learned = asyncio.run(
            learn_from_approval(db, _NoModel(), project["id"], artifact_id, _approved(), "s")
        )
    finally:
        db.close()
    assert learned == 0
