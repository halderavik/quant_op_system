"""Logic test: simulated respondents through the XML, checked against the questionnaire."""

from fastapi.testclient import TestClient

from app.engines.decipher import compile_decipher
from app.engines.decipher_cond import condition_holds
from app.engines.logic_qa import holds, run_logic_qa
from app.schemas.expression import BoolExpr, Comparison
from app.schemas.questionnaire import (
    Computation,
    DerivedValue,
    DerivedVariable,
    Option,
    ProgrammingSpec,
    Question,
    Questionnaire,
)
from tests.conftest import create_project


def _document(terminate_after: str | None = None) -> Questionnaire:
    return Questionnaire(
        id="t",
        title="Logic Test",
        terminate_after=terminate_after,
        questions=[
            Question(
                id="S1",
                type="single_select",
                text="Age?",
                options=[
                    Option(code=1, label="18-34"),
                    Option(code=2, label="35+"),
                    Option(code=3, label="Under 18", terminate=True),
                ],
            ),
            Question(
                id="Q1",
                type="multi_select",
                text="Brands?",
                options=[
                    Option(code=1, label="A"),
                    Option(code=2, label="B"),
                    Option(code=99, label="None", exclusive=True),
                ],
            ),
            Question(
                id="Q2",
                type="single_select",
                text="Favourite?",
                display_if=Comparison(op="eq", ref="Q1", value=1),
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
                programming=ProgrammingSpec(
                    terminate_when=Comparison(op="eq", ref="Q2", value=2),
                    terminate_immediately=True,
                ),
            ),
            Question(
                id="Q3",
                type="numeric",
                text="How many?",
                display_if=Comparison(op="ne", ref="Q1", value=99),
                programming=ProgrammingSpec(min_value=0, max_value=10),
            ),
            Question(
                id="Q4",
                type="single_select",
                text="Heavy user?",
                display_if=Comparison(op="gte", ref="HV_COUNT", value=2),
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
            ),
        ],
        derived_variables=[
            DerivedVariable(
                id="HV_COUNT",
                definition="Brands known",
                after="Q1",
                compute=Computation(kind="count", sources=["Q1"], rows=[1, 2]),
            ),
            DerivedVariable(
                id="HV_SEG",
                definition="Segment",
                after="S1",
                values=[
                    DerivedValue(
                        code=1, label="Young", when=Comparison(op="eq", ref="S1", value=1)
                    ),
                    DerivedValue(
                        code=2, label="Older", when=Comparison(op="eq", ref="S1", value=2)
                    ),
                ],
            ),
        ],
    )


def _run(xml_edit=None, document: Questionnaire | None = None) -> dict:
    document = document or _document()
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    xml = xml_edit(program.xml) if xml_edit else program.xml
    return run_logic_qa(document, xml, [item.model_dump() for item in program.items])


def test_a_correct_xml_agrees_for_every_respondent() -> None:
    result = _run()
    assert result["agreement"] == 100.0
    assert result["issues"] == []
    assert result["terminated"]["expected"] == result["terminated"]["xml"] > 50
    shown = {row["question_id"]: row for row in result["questions"]}
    assert all(row["expected"] == row["xml"] for row in shown.values())
    assert shown["Q4"]["xml"] > 0  # the count variable was worked out and used


def test_a_wrong_base_is_found_with_the_answers_that_show_it() -> None:
    result = _run(lambda xml: xml.replace('cond="Q1.r1"', 'cond="Q1.r2"'))
    kinds = {(item["question_id"], item["kind"]) for item in result["issues"]}
    assert ("Q2", "xml_hides") in kinds and ("Q2", "xml_shows") in kinds
    hidden = next(item for item in result["issues"] if item["kind"] == "xml_hides")
    assert "Q1" in hidden["examples"][0]
    assert "base: Q1 equals 1" in hidden["message"]
    assert result["agreement"] < 90


def test_a_missing_terminate_is_found() -> None:
    result = _run(lambda xml: xml.replace('cond="Q2.r2"', 'cond="0"'))
    assert [item["kind"] for item in result["issues"]] == ["xml_continues"]
    assert result["issues"][0]["question_id"] == "Q2"


def test_an_extra_terminate_is_named() -> None:
    result = _run(lambda xml: xml.replace('cond="S1.r3"', 'cond="S1.r2 or S1.r3"'))
    item = result["issues"][0]
    assert item["kind"] == "xml_terminates" and item["question_id"] == "S1"
    assert item["examples"][0]["XML terminate"].startswith("Term_S1")


def test_flagged_terminates_wait_for_the_end_of_the_screener() -> None:
    result = _run(document=_document(terminate_after="Q1"))
    assert result["agreement"] == 100.0


def test_a_written_base_without_logic_is_listed() -> None:
    document = _document()
    document.questions[2] = document.questions[2].model_copy(
        update={"display_if": None, "programmer_notes": ["ASK IF Q1=1"]}
    )
    result = _run(document=document)
    assert result["written_base_without_logic"] == ["Q2"]


def test_questionnaire_logic_reads_select_all_and_grid_answers() -> None:
    answers = {"Q1": [1, 2], "G": {"1": 5, "2": 3}, "S": 2, "N": 7}
    assert holds(Comparison(op="eq", ref="Q1", value=2), answers, {})
    assert holds(Comparison(op="ne", ref="Q1", value=99), answers, {})
    assert not holds(Comparison(op="ne", ref="Missing", value=1), answers, {})
    assert holds(Comparison(op="eq", ref="G", row=1, value=5), answers, {})
    assert holds(Comparison(op="gt", ref="Q1", aggregate="count", value=1), answers, {})
    assert holds(Comparison(op="gt", ref="N", value_ref="S"), answers, {})
    assert holds(BoolExpr(op="not", args=[Comparison(op="in", ref="S", value=[1, 3])]), answers, {})


def test_conditions_after_a_false_part_are_still_read() -> None:
    """``a and (not b)`` with ``a`` false used to leave tokens unread and fail."""
    condition = "((h.r1 or h.r2)) and (not ((h.r3 or h.r4)))"
    assert condition_holds(condition, {}) is False
    assert condition_holds(condition, {"h.r1": True}) is True
    assert condition_holds("h.r1 or (h.r2 and h.r3)", {"h.r1": True}) is True


def test_logic_qa_endpoint(client: TestClient) -> None:
    project = create_project(client)
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=_document().model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    missing = client.post(f"/api/projects/{project['id']}/decipher/qa", json={})
    assert missing.status_code == 404
    client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
    response = client.post(f"/api/projects/{project['id']}/decipher/qa", json={"respondents": 200})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["respondents"] == 200 and body["agreement"] == 100.0
    assert body["questionnaire_version"] == 1
