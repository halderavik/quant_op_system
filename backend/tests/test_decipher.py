"""Decipher programming, PDF export, and the unconfigured launch hook."""

import xml.etree.ElementTree as ET
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import Settings
from app.engines.decipher import compile_decipher
from app.engines.qpdf import to_pdf
from app.errors import AppError
from app.schemas.expression import Comparison
from app.schemas.questionnaire import Module, Option, Question, Questionnaire, RoutingRule
from app.services.decipher_launch import NotConfiguredLauncher, launcher_from_settings
from tests.conftest import create_project


def _programmed() -> Questionnaire:
    """Build an instrument that uses the main Decipher mappings.

    Returns:
        Questionnaire with routing, a grid, and a terminate option.
    """
    return Questionnaire(
        id="q-coffee",
        title="Coffee study",
        modules=[Module(id="screener", title="Screener", question_ids=["S1", "Q1"])],
        sample_notes=["Adults 18+"],
        programming_notes=["One question per screen."],
        questions=[
            Question(
                id="S1",
                type="screener",
                text="Are you 18 or older?",
                instruction="Please select one.",
                programmer_notes=["Ask all."],
                options=[
                    Option(code=1, label="No", terminate=True),
                    Option(code=2, label="Yes"),
                ],
            ),
            Question(
                id="Q1",
                type="multi_select",
                text="Which brands have you bought?",
                randomize_options=True,
                exclusive_codes=[98],
                display_if=Comparison(op="eq", ref="S1", value=2),
                options=[
                    Option(code=1, label="Northstar"),
                    Option(code=98, label="Other", open_text=True, anchor=True),
                ],
            ),
            Question(
                id="Qskip",
                type="single_select",
                text="Continue to the ratings?",
                options=[
                    Option(code=1, label="Skip ahead"),
                    Option(code=2, label="Continue"),
                ],
                routing=[
                    RoutingRule(
                        when=Comparison(op="eq", ref="Qskip", value=1),
                        go_to="Q4",
                    )
                ],
            ),
            Question(
                id="Q2",
                type="grid",
                text="Rate each attribute",
                matrix_items=["Taste", "Price"],
                options=[Option(code=1, label="Poor"), Option(code=2, label="Good")],
            ),
            Question(id="Q3", type="numeric", text="How many cups in a week?"),
            Question(id="Q4", type="text", text="Why did you recommend it?"),
        ],
    )


def test_compiler_programs_structured_questions() -> None:
    """Choice, grid, skip, and terminate logic become Decipher elements."""
    result = compile_decipher(_programmed())
    assert result.validation_status == "passed", result.issues
    root = ET.fromstring(result.xml)
    assert root.get("compat") == "153"
    assert root.get("delphi") == "1"
    assert "<note>" not in result.xml
    screener = root.find("./block")
    assert screener is not None
    radio = screener.find("./radio[@label='S1']")
    assert radio is not None
    assert radio.find("./title").text == "Are you 18 or older?"
    assert radio.find("./comment").text == "Please select one."
    assert radio.find("./note") is None
    assert "<!-- S1: Ask all. -->" in result.xml
    assert any(term.get("cond") == "S1.r1" for term in root.iter("term"))
    brands = screener.find("./checkbox[@label='Q1']")
    assert brands is not None
    assert brands.get("atleast") == "1"
    assert brands.get("shuffle") == "rows"
    assert brands.get("cond") == "S1.r2"
    other = brands.find("./row[@label='r2']")
    assert other is not None
    assert other.get("exclusive") == "1"
    assert other.get("open") == "1"
    assert other.get("randomize") == "0"
    grid = root.find("./radio[@label='Q2']")
    assert grid is not None
    assert grid.get("cond") == "not (Qskip.r1)"
    assert grid.find("./row[@label='r1']").text == "Taste"
    assert grid.find("./col[@label='c1']").text == "Poor"
    assert root.find("./number[@label='Q3']").get("cond") == "not (Qskip.r1)"
    assert root.find("./textarea[@label='Q4']").get("cond") is None
    q1 = next(item for item in result.items if item.question_id == "Q1")
    assert any(punch.code == "98" and punch.row_label == "r2" for punch in q1.punches)
    assert "Adults 18+" in result.xml


def test_partial_types_warn_without_inventing_structure() -> None:
    """Loops, dates, ranks, and empty grids are flagged instead of guessed."""
    document = Questionnaire(
        id="q-edge",
        title="Edge cases",
        questions=[
            Question(
                id="Q1",
                type="loop",
                text="For each brand",
                options=[Option(code=1, label="Northstar")],
            ),
            Question(id="Q2", type="date", text="When did you last buy coffee?"),
            Question(
                id="Q3",
                type="rank",
                text="Rank these brands",
                options=[Option(code=1, label="Northstar"), Option(code=2, label="Harbor")],
            ),
            Question(id="Q4", type="grid", text="Rate the brands"),
            Question(
                id="Q5",
                type="allocation",
                text="Allocate 100 points",
                options=[Option(code=1, label="Taste"), Option(code=2, label="Price")],
            ),
            Question(
                id="Q6",
                type="single_select",
                text="Unused",
                unsupported=True,
                options=[Option(code=1, label="Yes")],
            ),
        ],
    )
    result = compile_decipher(document)
    assert result.validation_status == "passed_with_warnings"
    root = ET.fromstring(result.xml)
    assert root.find(".//loop[@label='Q1']") is not None
    assert root.find(".//loop[@label='Q1']/block") is not None
    assert "YYYY-MM-DD" in result.xml
    assert root.find(".//select[@label='Q3']").get("unique") == "none,cols"
    assert "total != 100" in result.xml
    assert any("loop body is empty" in warning for warning in result.warnings)
    assert any("calendar" in warning for warning in result.warnings)
    assert any("rank-sort" in warning for warning in result.warnings)
    assert any("no grid cells were invented" in warning for warning in result.warnings)
    assert any("unsupported" in warning for warning in result.warnings)


def test_unknown_condition_stops_programming_with_the_comparison() -> None:
    """Programming refuses a punch label and a hidden variable before writing XML."""
    document = _programmed()
    document.questions[1].display_if = Comparison(op="eq", ref="Q3r99", value=0)
    document.questions[4].display_if = Comparison(op="answered", ref="HV_MOST_BRAND")
    failed = compile_decipher(document)
    assert failed.validation_status == "failed"
    assert failed.xml == ""
    assert any("Q1 is shown only when Q3r99 equals 0" in issue for issue in failed.issues)
    assert any("HV_MOST_BRAND" in issue and "hidden variable" in issue for issue in failed.issues)


def test_program_endpoint_lists_every_unknown_condition(client: TestClient) -> None:
    """The panel error names each condition that points at a missing question."""
    project = create_project(client)
    document = _programmed()
    document.questions[1].display_if = Comparison(op="eq", ref="Q3r99", value=0)
    document.questions[4].display_if = Comparison(op="answered", ref="HV_MOST_BRAND")
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=document.model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    programmed = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
    assert programmed.status_code == 400
    message = programmed.json()["error"]["message"]
    assert "Q3r99 equals 0" in message
    assert "HV_MOST_BRAND" in message
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    questionnaire = next(item for item in artifacts if item["type"] == "questionnaire")
    issues = questionnaire["latest"]["validation"]["issues"]
    assert any(issue["code"] == "bad_ref" and "Q3r99" in issue["message"] for issue in issues)


def test_duplicate_ids_and_missing_routes_fail() -> None:
    """Programming stops when a label or a route target is ambiguous."""
    duplicate = _programmed()
    duplicate.questions[1].id = "S1"
    failed = compile_decipher(duplicate)
    assert failed.validation_status == "failed"
    assert failed.xml == ""
    assert any("unique" in issue for issue in failed.issues)

    missing = _programmed()
    missing.questions[0].routing = [RoutingRule(go_to="Q999")]
    routed = compile_decipher(missing)
    assert routed.validation_status == "failed"
    assert any("Q999" in issue for issue in routed.issues)


def test_pdf_contains_the_question_text() -> None:
    """A PDF export is a real file and keeps the question wording."""
    document = _programmed()
    document.questions[0].options[0].label = "Café"
    payload = to_pdf(document)
    assert payload.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)
    normalized = " ".join(text.split())
    assert "Are you 18 or older?" in normalized
    assert "Café" in normalized
    assert "PROGRAMMING NOTES ARE IN BLUE" in normalized


def test_pdf_export_requires_a_questionnaire(client: TestClient) -> None:
    """PDF and an unknown format do not invent a file."""
    project = create_project(client)
    missing = client.post(f"/api/projects/{project['id']}/questionnaires/export/pdf")
    assert missing.status_code == 404
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=_programmed().model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    unknown = client.post(f"/api/projects/{project['id']}/questionnaires/export/pptx")
    assert unknown.status_code == 400


def test_program_endpoint_downloads_xml_and_marks_stale(client: TestClient) -> None:
    """The panel action stores XML, and a later questionnaire edit marks it stale."""
    project = create_project(client)
    document = _programmed()
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=document.model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    programmed = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
    assert programmed.status_code == 200, programmed.text
    download = client.get(f"/api/files/{programmed.json()['file_id']}/download")
    assert download.status_code == 200
    assert b"<survey" in download.content
    assert download.content.startswith(b"<?xml")
    edited = document.model_copy(deep=True)
    edited.questions[0].text = "Updated after programming"
    revision = client.post(
        f"/api/artifacts/{saved.json()['artifact_id']}/revisions",
        json={"content": edited.model_dump(mode="json"), "expected_version": 1},
    )
    assert revision.status_code == 201, revision.text
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    survey = next(item for item in artifacts if item["type"] == "decipher_survey")
    assert survey["latest"]["stale"] is True
    assert survey["latest"]["content"]["launch"] == "not_configured"


def test_chat_program_does_not_revise_the_questionnaire(client: TestClient) -> None:
    """A Decipher request programs XML and leaves the instrument version alone."""
    project = create_project(client)
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=_programmed().model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    message = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "program this survey in decipher"},
    )
    assert message.status_code == 201, message.text
    task = client.get(f"/api/tasks/{message.json()['task_id']}").json()
    assert task["status"] in {"completed", "completed_with_warnings"}
    history = client.get(f"/api/artifacts/{saved.json()['artifact_id']}/revisions").json()
    assert history[-1]["version"] == 1
    replies = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "Decipher" in replies[-1]["content"]
    assert "not connected" in replies[-1]["content"]


def test_chat_without_a_questionnaire_asks_first(client: TestClient) -> None:
    """Programming is refused until a questionnaire exists."""
    project = create_project(client)
    message = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "generate the survey XML"},
    )
    assert message.status_code == 201, message.text
    task = client.get(f"/api/tasks/{message.json()['task_id']}").json()
    assert task["status"] == "clarification_needed"
    replies = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "questionnaire" in replies[-1]["content"].lower()


def test_launcher_is_not_configured(tmp_path) -> None:
    """A blank API key does not call Forsta."""
    settings = Settings(
        openai_api_key="",
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        storage_root=tmp_path / "storage",
        session_db_path=tmp_path / "sessions.db",
        cors_origins="http://localhost:5173",
        decipher_api_base="",
        decipher_api_key="",
        decipher_company="",
    )
    launcher = launcher_from_settings(settings)
    assert isinstance(launcher, NotConfiguredLauncher)
    with pytest.raises(AppError) as caught:
        launcher.launch("<survey/>", "Coffee")
    assert caught.value.code == "decipher_not_configured"
