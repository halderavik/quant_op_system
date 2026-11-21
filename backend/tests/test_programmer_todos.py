"""Programmer to-dos panel actions and the side-by-side XML comparison."""

from fastapi.testclient import TestClient

from app.engines.decipher import compile_decipher
from app.schemas.questionnaire import Option, ProgrammingSpec, Question, Questionnaire
from app.services import programmer_todos
from app.services.program_review import _review_item
from app.services.programming_spec import PlanBatch, QuestionPlan
from app.services.xml_compare import compare_xml, raw_element
from tests.conftest import create_project


def _document() -> Questionnaire:
    return Questionnaire(
        id="t",
        title="Todo Study",
        questions=[
            Question(
                id="S1",
                type="single_select",
                text="Are you 18 or older?",
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
                programming=ProgrammingSpec(
                    unresolved=["Quota: 50 per cell.", "Review: Code 2 must terminate."]
                ),
            ),
            Question(
                id="Q1",
                type="multi_select",
                text="Which brands do you know?",
                options=[Option(code=1, label="Alpha"), Option(code=2, label="Beta")],
                programming=ProgrammingSpec(unresolved=["Show 10 per page."]),
            ),
        ],
    )


def _setup(client: TestClient) -> str:
    project = create_project(client)
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=_document().model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    programmed = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
    assert programmed.status_code == 200, programmed.text
    return project["id"]


def _latest_xml(client: TestClient, project_id: str) -> str:
    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    survey = next(a for a in artifacts if a["type"] == "decipher_survey")
    return survey["latest"]["content"]["xml"]


def test_todos_are_listed_marked_done_and_reopened(client: TestClient) -> None:
    project_id = _setup(client)
    listed = client.get(f"/api/projects/{project_id}/decipher/todos").json()
    assert listed["open"] == 3 and listed["done"] == 0 and not listed["xml_stale"]
    review = next(row for row in listed["todos"] if row["source"] == "review")
    assert review["text"] == "Code 2 must terminate." and review["owner"] == "S1"

    quota = next(row for row in listed["todos"] if row["text"].startswith("Quota"))
    marked = client.post(
        f"/api/projects/{project_id}/decipher/todos/mark", json={"ids": [quota["id"]]}
    )
    assert marked.status_code == 200, marked.text
    body = marked.json()
    assert body["open"] == 2 and body["done"] == 1
    assert body["summary"] == "Marked 1 to-do."
    # The XML is rebuilt, so it is current and the done to-do is no longer a comment.
    assert not body["xml_stale"]
    xml = _latest_xml(client, project_id)
    assert "Quota: 50 per cell" not in xml and "Show 10 per page" in xml

    reopened = client.post(
        f"/api/projects/{project_id}/decipher/todos/mark",
        json={"ids": [quota["id"]], "done": False},
    ).json()
    assert reopened["open"] == 3 and reopened["done"] == 0

    missing = client.post(f"/api/projects/{project_id}/decipher/todos/mark", json={"ids": ["nope"]})
    assert missing.status_code == 404


def test_fix_with_ai_keeps_unpicked_todos_and_adds_what_the_reviewer_still_finds(
    client: TestClient, monkeypatch
) -> None:
    project_id = _setup(client)
    rows = client.get(f"/api/projects/{project_id}/decipher/todos").json()["todos"]
    pick = next(row for row in rows if row["text"] == "Code 2 must terminate.")

    async def fake_plan_batch(settings, document, group, problems, session_id, limit, lessons):
        assert problems == {"S1": ["Code 2 must terminate."]}
        return PlanBatch(
            questions=[
                QuestionPlan(question_id="S1", programming=ProgrammingSpec()),
                # A plan for a question that was not picked is ignored.
                QuestionPlan(question_id="Q1", programming=ProgrammingSpec()),
            ]
        )

    async def fake_review(settings, document, xml, session_id, limit, lessons=None, *, only=None):
        assert only == {"S1"}
        # The reviewer sees the chosen to-do as a change the person asked for.
        s1 = next(q for q in document.questions if q.id == "S1")
        assert "REQUESTED BY THE PERSON: Code 2 must terminate." in _review_item(s1, {})
        return {"S1": ["Terminate is still missing on code 2."]}

    import app.services.program_review as program_review
    import app.services.programming_spec as programming_spec

    monkeypatch.setattr(programming_spec, "_plan_batch", fake_plan_batch)
    monkeypatch.setattr(program_review, "review", fake_review)
    monkeypatch.setattr(type(client.app.state.settings), "llm_configured", property(lambda _: True))
    fixed = client.post(
        f"/api/projects/{project_id}/decipher/todos/fix", json={"ids": [pick["id"]]}
    )
    assert fixed.status_code == 200, fixed.text
    body = fixed.json()
    texts = {(row["owner"], row["text"]) for row in body["todos"] if not row["done"]}
    assert ("S1", "Quota: 50 per cell.") in texts  # not picked, so kept
    assert ("Q1", "Show 10 per page.") in texts  # other question untouched
    assert ("S1", "Terminate is still missing on code 2.") in texts
    assert ("S1", "Code 2 must terminate.") not in texts
    assert body["fixed"] == 1 and body["remaining"] == 2
    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    questionnaire = next(a for a in artifacts if a["type"] == "questionnaire")
    spec = questionnaire["latest"]["content"]["questions"][0]["programming"]
    assert spec["requested"] == ["Code 2 must terminate."]


def test_fix_needs_a_model(client: TestClient) -> None:
    project_id = _setup(client)
    rows = client.get(f"/api/projects/{project_id}/decipher/todos").json()["todos"]
    response = client.post(
        f"/api/projects/{project_id}/decipher/todos/fix", json={"ids": [rows[0]["id"]]}
    )
    assert response.status_code == 400


def test_compare_lines_up_questions_and_keeps_the_source_text() -> None:
    generated = compile_decipher(_document()).xml
    reference = generated.replace("Which brands do you know?", "Which brands have you heard of?")
    result = compare_xml(generated, reference, {"S1", "Q1"})
    rows = {row["label"]: row for row in result["questions"]}
    assert rows["S1"]["status"] == "match"
    assert rows["Q1"]["status"] == "differs"
    assert any(not c["passed"] and c["area"] == "Wording" for c in rows["Q1"]["checks"])
    assert rows["Q1"]["reference_xml"].startswith("<checkbox")
    assert "heard of" in rows["Q1"]["reference_xml"]
    assert result["match"] is not None and result["match"] < 100


def test_compare_marks_missing_and_extra_questions() -> None:
    generated = compile_decipher(_document()).xml
    reference = (
        '<survey><radio label="S1"><title>Are you 18 or older?</title>'
        '<row label="r1" value="1">Yes</row><row label="r2" value="2">No</row></radio>'
        '<text label="Q9"><title>Anything else?</title></text></survey>'
    )
    result = compare_xml(generated, reference, set())
    statuses = {row["label"]: row["status"] for row in result["questions"]}
    assert statuses["Q9"] == "missing" and statuses["Q1"] == "extra"


def test_compare_rejects_text_that_is_not_xml(client: TestClient) -> None:
    project_id = _setup(client)
    bad = client.post(f"/api/projects/{project_id}/decipher/compare", json={"xml": "<survey"})
    assert bad.status_code == 400
    ok = client.post(
        f"/api/projects/{project_id}/decipher/compare",
        json={"xml": _latest_xml(client, project_id)},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["match"] == 100.0


def test_raw_element_keeps_comments_and_strips_indent() -> None:
    xml = (
        '<survey>\n  <radio label="A">\n    <!-- note -->\n    <title>x</title>\n'
        "  </radio>\n</survey>"
    )
    expected = '<radio label="A">\n  <!-- note -->\n  <title>x</title>\n</radio>'
    assert raw_element(xml, "A", "radio") == expected


def test_todo_ids_are_stable() -> None:
    assert programmer_todos.todo_id("S1", "x") == programmer_todos.todo_id("S1", "x")
    assert programmer_todos.todo_id("S1", "x") != programmer_todos.todo_id("S2", "x")
