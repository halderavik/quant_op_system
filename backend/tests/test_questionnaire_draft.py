"""Questionnaire schema, DOCX guidelines, and draft prompts."""

import json
from io import BytesIO

import pytest
from agents.agent_output import AgentOutputSchema
from docx import Document
from pydantic import ValidationError

from app.engines.sow import extract_brief_bytes
from app.errors import AppError
from app.schemas.expression import BoolExpr, Comparison
from app.schemas.questionnaire import Module, Objective, Option, Question, Questionnaire
from app.services.study_materials import questionnaire_prompt
from tests.conftest import create_project


def _docx(*rows: tuple[str, ...], paragraph: str = "Objective: measure trust") -> bytes:
    """Build a small DOCX with one paragraph and one table.

    Args:
        rows: Cell texts for each table row.
        paragraph: Opening paragraph.

    Returns:
        DOCX bytes.
    """
    document = Document()
    document.add_paragraph(paragraph)
    width = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=width)
    for row_index, row in enumerate(rows):
        for column, text in enumerate(row):
            table.cell(row_index, column).text = text
    if width > 1:
        merged = table.cell(0, 0)
        # Reason: the first row is merged so the extractor must not repeat that cell.
        merged.merge(table.cell(0, 1))
        merged.text = rows[0][0]
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _instrument() -> Questionnaire:
    """Return a one-question instrument the fake model can save.

    Returns:
        Questionnaire.
    """
    return Questionnaire(
        id="q1",
        title="Brand tracker",
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


def test_questionnaire_schema_types_expression_values() -> None:
    """Strict output schema types comparison values and omits discriminator."""
    schema = AgentOutputSchema(Questionnaire).json_schema()
    assert "discriminator" not in json.dumps(schema)
    value = schema["$defs"]["Comparison"]["properties"]["value"]
    assert "anyOf" in value or "type" in value
    parsed = Comparison(op="eq", ref="Q2", value=1)
    assert parsed.value == 1
    tree = BoolExpr.model_validate(
        {
            "kind": "bool",
            "op": "and",
            "args": [{"kind": "cmp", "op": "in", "ref": "Q1", "value": [1, "other"]}],
        }
    )
    assert tree.args[0].value == [1, "other"]


def test_expression_value_rejects_objects() -> None:
    """A comparison value cannot be an open object."""
    with pytest.raises(ValidationError):
        Comparison(op="eq", ref="Q1", value={"bad": True})


def test_docx_extraction_includes_table_cells() -> None:
    """Paragraphs stay ahead of table rows, and a merged cell is kept once."""
    brief = extract_brief_bytes(
        _docx(("QUOTA_GRID_MARKER", "ignored duplicate"), ("150", "users")),
        "guide.docx",
    )
    assert brief.text.index("Objective: measure trust") < brief.text.index("QUOTA_GRID_MARKER")
    assert brief.text.count("QUOTA_GRID_MARKER") == 1
    assert "150 | users" in brief.text


def test_extract_rejects_unknown_type() -> None:
    """Spreadsheets are not study briefs."""
    with pytest.raises(AppError) as caught:
        extract_brief_bytes(b"not a document", "notes.xlsx")
    assert caught.value.code == "unsupported_file"


def test_draft_includes_uploaded_docx_table(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored DOCX table is part of the draft prompt, and a CSV is not."""
    project = create_project(client)
    csv_upload = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("skip.csv", b"SPREADSHEET_MARKER", "text/csv")},
    )
    assert csv_upload.status_code == 201, csv_upload.text
    docx_upload = client.post(
        f"/api/projects/{project['id']}/files",
        files={
            "file": (
                "prior.docx",
                _docx(("ROW_LIST_MARKER", "second")),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert docx_upload.status_code == 201, docx_upload.text
    seen: dict[str, str] = {}

    async def _fake(*_args, **kwargs):
        seen["prompt"] = kwargs["prompt"]
        return _instrument()

    monkeypatch.setattr("app.agents.orchestrator.run_structured", _fake)
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Draft a questionnaire using the uploaded file"},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] in {"completed", "completed_with_warnings"}, task
    assert "ROW_LIST_MARKER" in seen["prompt"]
    assert "SPREADSHEET_MARKER" not in seen["prompt"]
    assert seen["prompt"].index("ROW_LIST_MARKER") < seen["prompt"].index("User request:")
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "from prior.docx." in messages[-1]["content"]
    kinds = {item["type"] for item in client.get(f"/api/projects/{project['id']}/artifacts").json()}
    assert "questionnaire" in kinds


def test_explicit_file_limits_the_guideline(client) -> None:
    """A message file id uses that document and leaves the other upload out."""
    project = create_project(client)
    first = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("older.txt", b"OLDER_MARKER", "text/plain")},
    )
    second = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("newer.txt", b"NEWER_MARKER", "text/plain")},
    )
    assert first.status_code == 201 and second.status_code == 201
    db = client.app.state.session_factory()
    try:
        prompt, names = questionnaire_prompt(
            db,
            client.app.state.storage,
            project["id"],
            "Draft a questionnaire",
            [first.json()["file_id"]],
        )
    finally:
        db.close()
    assert names == ["older.txt"]
    assert "OLDER_MARKER" in prompt
    assert "NEWER_MARKER" not in prompt


def test_long_study_text_is_truncated(client) -> None:
    """A very long upload is cut off and the prompt says so."""
    project = create_project(client)
    uploaded = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("notes.txt", ("quota line\n" * 20000).encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    db = client.app.state.session_factory()
    try:
        prompt, names = questionnaire_prompt(
            db,
            client.app.state.storage,
            project["id"],
            "Draft a questionnaire",
        )
    finally:
        db.close()
    assert names == ["notes.txt"]
    assert "truncated to 80000 characters" in prompt
