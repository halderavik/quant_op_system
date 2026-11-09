"""Questionnaire flow, exports, tab specs, and external workbook detection."""

from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.engines.external_spec import external_workbook, preview_external
from app.engines.flow import validate_questionnaire
from app.engines.qexport import to_docx
from app.engines.tabspec_build import build_tabspec
from app.engines.tabspec_excel import export_tabspec, import_tabspec
from app.errors import AppError
from app.schemas.expression import Comparison
from app.schemas.questionnaire import (
    Module,
    Objective,
    Option,
    Question,
    Questionnaire,
    RoutingRule,
)
from app.schemas.tabspec import Banner, BannerCategory, StudyDefaults, TableSpec, TabSpec
from tests.conftest import create_project

ROOT_SAV = Path(__file__).resolve().parents[2] / "fixtures" / "survey_small.sav"


def _instrument(count: int = 22, broken: bool = False) -> Questionnaire:
    """Build a multi-module instrument.

    Args:
        count: Number of questions.
        broken: Add a route to a missing question when true.

    Returns:
        Questionnaire.
    """
    questions = []
    for index in range(1, count + 1):
        kind = "text" if index == count else "single_select"
        questions.append(
            Question(
                id=f"Q{index}",
                type=kind,
                text=f"Question {index} about trust and usage",
                options=(
                    []
                    if kind == "text"
                    else [Option(code=1, label="No"), Option(code=2, label="Yes")]
                ),
                routing=[RoutingRule(go_to="Q999")] if broken and index == 1 else [],
            )
        )
    return Questionnaire(
        id="q1",
        title="Brand health, NPS, path to purchase, tracking, and segmentation",
        objectives=[Objective(id="o1", description="Measure trust", question_ids=["Q1"])],
        modules=[
            Module(id="m1", title="Core", question_ids=[question.id for question in questions])
        ],
        questions=questions,
        estimated_minutes=12,
    )


def test_docx_keeps_programmer_notes_in_blue() -> None:
    """Programming notes are blue and terminate marks stay in the code table."""
    document = _instrument(count=2)
    document.sample_notes = ["Adults 18+ in the brief"]
    document.programming_notes = ["Show one question per screen."]
    document.questions[0].instruction = "Please select one."
    document.questions[0].programmer_notes = ["Ask all."]
    document.questions[0].options[0].terminate = True
    document.questions[0].options[1].anchor = True
    parsed = Document(BytesIO(to_docx(document)))
    text = "\n".join(paragraph.text for paragraph in parsed.paragraphs)
    assert "PROGRAMMING NOTES ARE IN BLUE" in text
    assert "Ask all." in text
    assert "Do not show this programming note to respondents." in text
    blue = []
    for paragraph in parsed.paragraphs:
        for run in paragraph.runs:
            if run.font.color and run.font.color.rgb and str(run.font.color.rgb) == "0432FF":
                blue.append(run.text)
    assert any("Ask all." in line for line in blue)
    assert any(
        "TERMINATE" in cell.text
        for table in parsed.tables
        for row in table.rows
        for cell in row.cells
    )


def test_long_instrument_validates_and_exports_docx() -> None:
    """A 22-question instrument validates, and the DOCX contains the first question."""
    document = _instrument()
    report = validate_questionnaire(document)
    assert report.status == "passed"
    assert len(document.questions) >= 20
    parsed = Document(BytesIO(to_docx(document)))
    text = "\n".join(paragraph.text for paragraph in parsed.paragraphs)
    assert "Q1" in text
    assert "not a verified timing study" in text


def test_broken_routing_is_flagged() -> None:
    """A route to an unknown question fails validation."""
    report = validate_questionnaire(_instrument(count=4, broken=True))
    assert report.status == "failed"
    assert any(issue.code == "bad_route" for issue in report.issues)


def test_show_if_names_the_missing_question_and_the_comparison() -> None:
    """A punch label used as a question id is rejected with the owning condition."""
    document = _instrument(count=3)
    document.questions[1].display_if = Comparison(op="eq", ref="Q3r99", value=0)
    report = validate_questionnaire(document)
    assert report.status == "failed"
    issue = next(item for item in report.issues if item.code == "bad_ref")
    assert issue.question_id == "Q2"
    assert "Q2 is shown only when Q3r99 equals 0" in issue.message
    assert "row punch on Q3" in issue.message


def test_hidden_variable_and_skip_are_rejected() -> None:
    """A hidden variable and a skip to a missing question are both named."""
    document = _instrument(count=3)
    document.questions[0].routing = [
        RoutingRule(when=Comparison(op="eq", ref="NOT_A_QUESTION", value=1), go_to="Q3")
    ]
    document.questions[2].display_if = Comparison(op="answered", ref="HV_MOST_BRAND")
    report = validate_questionnaire(document)
    messages = [issue.message for issue in report.issues if issue.code == "bad_ref"]
    assert any("Q1 skips to Q3 when NOT_A_QUESTION equals 1" in message for message in messages)
    assert any("hidden variable" in message and "HV_MOST_BRAND" in message for message in messages)


def test_condition_value_must_be_a_real_option_code() -> None:
    """A show-if cannot compare a question to a code it does not have."""
    document = _instrument(count=2)
    document.questions[1].display_if = Comparison(op="eq", ref="Q1", value=0)
    report = validate_questionnaire(document)
    issue = next(item for item in report.issues if item.code == "bad_code")
    assert issue.question_id == "Q2"
    assert "Q1 equals 0" in issue.message
    assert "Use one of: 1, 2." in issue.message


def test_numeric_comparison_on_a_choice_question_fails() -> None:
    """Greater-than is rejected on a single-select and allowed on a number."""
    choice = _instrument(count=2)
    choice.questions[1].display_if = Comparison(op="gt", ref="Q1", value=1)
    refused = validate_questionnaire(choice)
    assert any(issue.code == "bad_compare" for issue in refused.issues)
    number = _instrument(count=2)
    number.questions[0].type = "numeric"
    number.questions[0].options = []
    number.questions[1].display_if = Comparison(op="gte", ref="Q1", value=3)
    allowed = validate_questionnaire(number)
    assert not any(issue.code in {"bad_code", "bad_compare", "bad_ref"} for issue in allowed.issues)


def test_real_earlier_question_still_passes() -> None:
    """A show-if that names an earlier question is not a missing-question error."""
    document = _instrument(count=3)
    document.questions[1].display_if = Comparison(op="eq", ref="Q1", value=1)
    report = validate_questionnaire(document)
    assert not any(issue.code == "bad_ref" for issue in report.issues)


def test_chat_add_question_revises_instead_of_saving_a_note(
    client: TestClient, monkeypatch
) -> None:
    """A plain-language add request stores a new questionnaire revision."""
    project = create_project(client)
    original = _instrument(count=2)
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=original.model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    revised = original.model_copy(deep=True)
    revised.questions.append(
        Question(
            id="Q3",
            type="single_select",
            text="What is your household income?",
            options=[
                Option(code=1, label="Under $50,000"),
                Option(code=2, label="$50,000 or more"),
            ],
        )
    )
    revised.modules[0].question_ids.append("Q3")

    async def fake_revision(*_args, **_kwargs):
        return revised

    monkeypatch.setattr("app.agents.orchestrator.run_structured", fake_revision)
    message = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "can you add a income question with different income brackets"},
    )
    assert message.status_code == 201, message.text
    task = client.get(f"/api/tasks/{message.json()['task_id']}").json()
    assert task["status"] in {"completed", "completed_with_warnings"}
    history = client.get(f"/api/artifacts/{saved.json()['artifact_id']}/revisions").json()
    assert any(question["id"] == "Q3" for question in history[-1]["content"]["questions"])
    replies = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "Saved your note" not in replies[-1]["content"]
    assert "Q3" in replies[-1]["content"]


def test_chat_and_panel_edit_the_same_questionnaire(client: TestClient) -> None:
    """A panel save and a chat edit both increment the questionnaire version."""
    project = create_project(client)
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=_instrument(count=4).model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    artifact_id = saved.json()["artifact_id"]
    edited = client.post(
        f"/api/artifacts/{artifact_id}/patch",
        json={
            "expected_version": 1,
            "op": "set_question",
            "question_id": "Q2",
            "value": {"text": "Updated in the panel"},
        },
    )
    assert edited.status_code == 201
    message = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Change Q3 text to Updated in chat"},
    )
    assert message.status_code == 201
    history = client.get(f"/api/artifacts/{artifact_id}/revisions").json()
    assert history[-1]["version"] == 3
    assert any(
        question["text"] == "Updated in chat" for question in history[-1]["content"]["questions"]
    )
    exported = client.post(f"/api/projects/{project['id']}/questionnaires/export/docx")
    assert exported.status_code == 200
    download = client.get(f"/api/files/{exported.json()['file_id']}/download")
    assert download.content[:2] == b"PK"


def test_tabspec_covers_questions_and_round_trips() -> None:
    """Eligible questions are tabulated, open text stays on the plan, and Excel reloads."""
    from app.engines.tabspec_excel import export_legacy_tabspec

    document = _instrument(count=5)
    variables = [
        {"name": "Q1", "label": "Q1", "is_text": False, "value_labels": {"1": "No", "2": "Yes"}},
        {"name": "Q2", "label": "Q2", "is_text": False, "value_labels": {}},
        {
            "name": "gender",
            "label": "Gender",
            "is_text": False,
            "value_labels": {"1": "Male", "2": "Female"},
        },
    ]
    spec = build_tabspec(document, variables, dataset_id="d1")
    titles = {table.id for table in spec.tables}
    assert "T1" in titles
    assert any(table.plan_type == "Open end" for table in spec.tables)
    assert not any(item["question_id"] == "Q5" for item in spec.exclusions)
    restored = import_tabspec(export_tabspec(spec))
    assert [table.id for table in restored.tables] == [table.id for table in spec.tables]
    assert restored.banners[0].variable_name == "gender"
    legacy = import_tabspec(export_legacy_tabspec(spec))
    assert [table.id for table in legacy.tables] == [table.id for table in spec.tables]


def test_ambiguous_external_spec_requires_confirmation() -> None:
    """Two significance columns block execution instead of being guessed."""
    workbook = external_workbook(
        ["TableID", "Title", "Stub", "Banner", "sig_letters", "significance_letters"],
        [["T1", "Trust", "trust", "gender", "A", "B"]],
    )
    preview = preview_external(workbook)
    assert preview.requires_confirmation is True
    assert preview.mapping_confidence == "low"
    from app.engines.crosstab import run_tabspec

    with pytest.raises(AppError) as caught:
        run_tabspec(pd_frame(), [], TabSpec(spec_id="x", tables=[]), confirmed_external=False)
    assert caught.value.code == "mapping_review"


def pd_frame():
    """Return an empty frame for the blocked-run test.

    Returns:
        Empty data frame.
    """
    import pandas as pd

    return pd.DataFrame()


def test_upload_runs_canonical_spec_and_holds_an_ambiguous_one(client: TestClient) -> None:
    """A canonical workbook runs. An ambiguous layout is stored for review and does not run."""
    project = create_project(client)
    ambiguous = external_workbook(
        ["TableID", "Title", "Stub", "Banner", "sig_letters", "significance_letters"],
        [["T1", "Trust", "trust", "gender", "A", "B"]],
    )
    held = client.post(
        f"/api/projects/{project['id']}/files",
        files={
            "file": (
                "external.xlsx",
                ambiguous,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert held.status_code == 201, held.text
    assert held.json()["workbook"]["executed"] is False
    with (ROOT_SAV).open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("survey_small.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text
    spec = TabSpec(
        spec_id="reupload",
        study_defaults=StudyDefaults(weight_variable="weight"),
        banners=[
            Banner(
                id="bn1",
                label="Gender",
                variable_name="gender",
                categories=[
                    BannerCategory(label="Male", codes=[1]),
                    BannerCategory(label="Female", codes=[2]),
                ],
            )
        ],
        tables=[
            TableSpec(
                id="T001",
                title="Trust by gender",
                row_variable_names=["trust"],
                banner_ids=["bn1"],
                weight_variable="weight",
            )
        ],
    )
    ran = client.post(
        f"/api/projects/{project['id']}/files",
        files={
            "file": (
                "canonical.xlsx",
                export_tabspec(spec),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert ran.status_code == 201, ran.text
    assert ran.json()["workbook"]["executed"] is True
    download = client.get(f"/api/files/{ran.json()['workbook']['export_file_id']}/download")
    assert download.content[:2] == b"PK"


def test_forward_reference_fails() -> None:
    """A display rule cannot point at the same or a later question."""
    document = _instrument(count=2)
    document.questions[0].display_if = Comparison(op="eq", ref="Q2", value=1)
    report = validate_questionnaire(document)
    assert any(issue.code == "forward_ref" for issue in report.issues)
