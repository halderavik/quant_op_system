"""Respondent preview driven by Decipher survey XML."""

from app.engines.decipher import compile_decipher
from app.engines.decipher_preview import step_preview
from app.schemas.preview import PreviewAnswer
from app.schemas.questionnaire import Questionnaire
from tests.conftest import create_project
from tests.test_decipher import _programmed


def test_preview_starts_on_the_first_question_and_hides_notes() -> None:
    """The first screen is the question text, not the programmer note."""
    screen = step_preview(compile_decipher(_programmed()).xml, {}, None)
    assert screen.status == "question"
    assert screen.label == "S1"
    assert screen.title == "Are you 18 or older?"
    assert screen.comment == "Please select one."
    assert "Ask all." not in screen.model_dump_json()


def test_selecting_the_terminate_row_ends_the_survey() -> None:
    """S1.r1 is the term condition written for the No row."""
    xml = compile_decipher(_programmed()).xml
    ended = step_preview(xml, {"S1": PreviewAnswer(rows=["r1"])}, "S1")
    assert ended.status == "terminated"
    assert ended.title == "Thank you for your time."
    assert "taking our survey" in ended.message


def test_yes_shows_the_conditional_question_and_keeps_the_anchor_fixed() -> None:
    """S1.r2 shows Q1, and the exclusive open row is marked so it will not shuffle."""
    xml = compile_decipher(_programmed()).xml
    screen = step_preview(xml, {"S1": PreviewAnswer(rows=["r2"])}, "S1")
    assert screen.label == "Q1"
    assert screen.element == "checkbox"
    assert screen.shuffle is True
    other = next(row for row in screen.rows if row.text == "Other")
    assert other.exclusive is True
    assert other.open is True
    assert other.randomize is False
    assert screen.rows[0].randomize is True


def test_skip_condition_hides_the_questions_the_xml_jumps_over() -> None:
    """Choosing skip-ahead makes the not (Qskip.r1) questions disappear."""
    xml = compile_decipher(_programmed()).xml
    answers = {
        "S1": PreviewAnswer(rows=["r2"]),
        "Q1": PreviewAnswer(rows=["r1"]),
        "Qskip": PreviewAnswer(rows=["r1"]),
    }
    brands = step_preview(xml, answers, "Q1")
    assert brands.label == "Qskip"
    skipped = step_preview(xml, answers, "Qskip")
    assert skipped.label == "Q4"
    assert skipped.element == "textarea"
    finished = step_preview(xml, {**answers, "Q4": PreviewAnswer(value="Because")}, "Q4")
    assert finished.status == "complete"
    assert "greatly appreciated" in finished.message


def test_goto_jumps_to_the_target_label() -> None:
    """A true goto skips the element between it and the target."""
    xml = """
    <survey>
      <radio label="Q1" optional="0">
        <title>First</title>
        <row label="r1">Go</row>
      </radio>
      <goto target="Q3" cond="Q1.r1"/>
      <radio label="Q2" optional="0">
        <title>Skipped</title>
        <row label="r1">No</row>
      </radio>
      <radio label="Q3" optional="0">
        <title>Landed</title>
        <row label="r1">Yes</row>
      </radio>
    </survey>
    """
    screen = step_preview(xml, {"Q1": PreviewAnswer(rows=["r1"])}, "Q1")
    assert screen.label == "Q3"
    assert screen.title == "Landed"


def test_unreadable_condition_stops_the_preview() -> None:
    """A condition outside the grammar is returned, not guessed."""
    xml = """
    <survey>
      <radio label="Q1" optional="0" cond="Q1 ?? bad">
        <title>Broken</title>
        <row label="r1">A</row>
      </radio>
    </survey>
    """
    screen = step_preview(xml, {}, None)
    assert screen.status == "error"
    assert "Q1 ?? bad" in screen.message


def test_preview_routes_compile_and_step_without_saving(client) -> None:
    """The preview endpoints do not write a questionnaire or Decipher artifact."""
    project = create_project(client)
    source = client.post(
        f"/api/projects/{project['id']}/questionnaires/decipher/preview-source",
        json=_programmed().model_dump(mode="json"),
    )
    assert source.status_code == 200, source.text
    body = source.json()
    assert body["validation_status"] == "passed"
    step = client.post(
        f"/api/projects/{project['id']}/questionnaires/decipher/preview",
        json={"xml": body["xml"], "answers": {}, "current_label": None},
    )
    assert step.status_code == 200, step.text
    assert step.json()["label"] == "S1"
    assert "Ask all." not in step.text
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts")
    assert artifacts.json() == []


def test_preview_source_reports_a_questionnaire_that_cannot_be_programmed(client) -> None:
    """An empty instrument returns programming issues and no survey to walk."""
    project = create_project(client)
    empty = Questionnaire(id="q-empty", title="Empty", questions=[])
    source = client.post(
        f"/api/projects/{project['id']}/questionnaires/decipher/preview-source",
        json=empty.model_dump(mode="json"),
    )
    assert source.status_code == 200, source.text
    body = source.json()
    assert body["validation_status"] == "failed"
    assert body["issues"]
    assert body["xml"] == ""
