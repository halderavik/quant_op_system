"""Importing a Word questionnaire exactly as written, or using it as a reference."""

from io import BytesIO

import pytest
from docx import Document
from docx.shared import RGBColor

from app.engines.docx_questionnaire import (
    looks_like_questionnaire,
    question_ids,
    questionnaire_text,
)
from app.engines.verbatim import check_exact
from app.schemas.questionnaire import Option, Question, Questionnaire
from app.services.questionnaire_import import (
    QuestionnaireFrame,
    SectionImport,
    SectionModule,
    StudyFile,
    choose_mode,
    split_sections,
)
from tests.conftest import create_project

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _questionnaire_docx() -> bytes:
    """A small questionnaire: list-numbered options, a red note, and a codes table."""
    document = Document()
    document.add_paragraph("Coffee Habits Study")
    document.add_paragraph("S1. How often do you drink coffee? Please select one.")
    for label in ("Daily", "Weekly", "Never"):
        document.add_paragraph(label, style="List Number")
    note = document.add_paragraph()
    note.add_run("Ask all. ")
    red = note.add_run("TERMINATE if Never.")
    red.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "S2. Which brands do you buy? Please select all that apply."
    codes = table.cell(1, 0)
    codes.text = "1"
    codes.add_paragraph("2")
    codes.add_paragraph("99")
    labels = table.cell(1, 1)
    labels.text = "Brand A"
    labels.add_paragraph("Brand B")
    labels.add_paragraph("None of these")
    for number in range(3, 7):
        document.add_paragraph(f"Q{number}. Question {number} wording?")
        document.add_paragraph(f"{number}0 Answer {number}")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _import(text: str = "How often do you drink coffee?") -> Questionnaire:
    """What a correct transcription of the test file looks like."""
    questions = [
        Question(
            id="S1",
            type="single_select",
            text=text,
            instruction="Please select one.",
            programmer_notes=["Ask all.", "TERMINATE if Never."],
            options=[
                Option(code=1, label="Daily"),
                Option(code=2, label="Weekly"),
                Option(code=3, label="Never", terminate=True),
            ],
        ),
        Question(
            id="S2",
            type="multi_select",
            text="Which brands do you buy?",
            instruction="Please select all that apply.",
            options=[
                Option(code=1, label="Brand A"),
                Option(code=2, label="Brand B"),
                Option(code=99, label="None of these", exclusive=True),
            ],
        ),
    ] + [
        Question(
            id=f"Q{n}",
            type="single_select",
            text=f"Question {n} wording?",
            options=[Option(code=n * 10, label=f"Answer {n}")],
        )
        for n in range(3, 7)
    ]
    return Questionnaire(id="x", title="Coffee Habits Study", questions=questions)


def test_word_reader_keeps_list_numbers_red_text_and_cells() -> None:
    """List numbers become codes, red runs are marked, and cell lines stay apart."""
    text = questionnaire_text(_questionnaire_docx())
    assert "1. Daily" in text and "3. Never" in text
    assert "Ask all. [RED: TERMINATE if Never.]" in text
    assert "| 1 // 2 // 99 | Brand A // Brand B // None of these |" in text
    assert question_ids(text) == ["S1", "S2", "Q3", "Q4", "Q5", "Q6"]
    assert looks_like_questionnaire(text)
    assert not looks_like_questionnaire("Objectives: measure trust\nAudience: adults")


def test_exact_check_accepts_a_faithful_import_and_names_each_change() -> None:
    """Wording, missing questions, order, and invented codes are all caught."""
    text = questionnaire_text(_questionnaire_docx())
    good = check_exact(_import(), text)
    assert good.ok, good.messages()
    assert good.checked > 15

    reworded = check_exact(_import("How often do you have coffee?"), text)
    assert not reworded.ok
    message = reworded.issues["S1"][0]
    assert 'the file has "drink coffee' in message and 'the import has "have coffee' in message

    document = _import()
    document.questions = [document.questions[1], document.questions[0]] + document.questions[3:]
    document.questions[0].options[2] = Option(code=3, label="None of these")
    report = check_exact(document, text)
    flat = " ".join(report.messages())
    assert "missing: Q3" in flat
    assert "order differs" in flat
    assert "has code 3, which the file does not give it" in flat


def test_mode_choice() -> None:
    """A lone questionnaire is used as written unless the user asks for a reference."""
    text = questionnaire_text(_questionnaire_docx())
    questionnaire = StudyFile("q.docx", text)
    brief = StudyFile("brief.docx", "Objectives: measure trust\nAudience: coffee drinkers")
    assert choose_mode("Use this questionnaire", [questionnaire])[0] == "exact"
    assert choose_mode("", [questionnaire])[0] == "exact"
    assert choose_mode("Use it as a reference for a tea study", [questionnaire])[0] == "reference"
    assert choose_mode("Draft a questionnaire", [brief, questionnaire])[0] == "reference"
    assert choose_mode("Use this questionnaire exactly", [brief, questionnaire])[0] == "exact"
    assert choose_mode("Draft a questionnaire", [brief])[0] == "reference"


def test_sections_start_at_questions_and_never_inside_a_table() -> None:
    """The front matter is kept apart and every section starts at a question."""
    text = questionnaire_text(_questionnaire_docx())
    header, sections = split_sections(text, budget=120)
    assert header == "Coffee Habits Study"
    assert len(sections) > 1
    assert all(question_ids(section) for section in sections)
    assert not any(section.startswith("|") for section in sections)
    assert "".join(sections).count("[TABLE]") == 1


def _section_from(prompt: str, wrong_first: list[bool]) -> SectionImport:
    """Transcribe the questions a section prompt asks for; S1 is reworded the first time."""
    wanted = prompt.split("transcribe these questions: ", 1)[1].split(")", 1)[0].split(", ")
    reword = "S1" in wanted and wrong_first[0]
    if reword:
        wrong_first[0] = False
    document = _import(
        "How often do you have coffee?" if reword else "How often do you drink coffee?"
    )
    return SectionImport(
        modules=[
            SectionModule(
                title="Screener",
                questions=[question for question in document.questions if question.id in wanted],
            )
        ]
    )


def test_use_this_questionnaire_imports_it_word_for_word(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat request saves the file's questionnaire after re-reading a reworded section."""
    project = create_project(client)
    upload = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("coffee.docx", _questionnaire_docx(), DOCX_TYPE)},
    )
    assert upload.status_code == 201, upload.text
    wrong_first = [True]
    prompts: list[str] = []

    async def _fake(*_args, **kwargs):
        prompts.append(kwargs["prompt"])
        if kwargs["output_type"] is QuestionnaireFrame:
            return QuestionnaireFrame(title="Coffee Habits Study")
        return _section_from(kwargs["prompt"], wrong_first)

    monkeypatch.setattr("app.services.questionnaire_import.run_structured", _fake)
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Use this questionnaire", "file_ids": [upload.json()["file_id"]]},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] in {"completed", "completed_with_warnings"}, task
    assert any("did not match the file" in prompt for prompt in prompts)
    saved = next(
        item
        for item in client.get(f"/api/projects/{project['id']}/artifacts").json()
        if item["type"] == "questionnaire"
    )["latest"]["content"]
    assert saved["source"]["mode"] == "exact" and saved["source"]["filename"] == "coffee.docx"
    assert saved["questions"][0]["text"] == "How often do you drink coffee?"
    assert [q["id"] for q in saved["questions"]] == ["S1", "S2", "Q3", "Q4", "Q5", "Q6"]
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "exactly as written" in messages[-1]["content"]


def test_import_that_never_matches_saves_nothing(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the transcription keeps changing the wording, the user is told and nothing is saved."""
    project = create_project(client)
    upload = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("coffee.docx", _questionnaire_docx(), DOCX_TYPE)},
    )

    async def _fake(*_args, **kwargs):
        if kwargs["output_type"] is QuestionnaireFrame:
            return QuestionnaireFrame(title="Coffee Habits Study")
        return _section_from(kwargs["prompt"], [True])

    monkeypatch.setattr("app.services.questionnaire_import.run_structured", _fake)
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Use this questionnaire as is", "file_ids": [upload.json()["file_id"]]},
    )
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "failed", task
    kinds = {item["type"] for item in client.get(f"/api/projects/{project['id']}/artifacts").json()}
    assert "questionnaire" not in kinds


def test_word_numbered_questions_padded_codes_and_scale_cells() -> None:
    """'1. ...?' lines are Q1, '01 - Yes' is code 1, and a scale cell's trailing number is its code."""
    from app.services.questionnaire_import import clean_cell_breaks

    text = (
        "Intro text\n"
        "1. How satisfied are you with the service overall?\n"
        "[TABLE]\n| Very Dissatisfied // 1 | 2 | Very Satisfied // 3 | Don't know // 99 |\n[/TABLE]\n"
        "2. Would you use it again in the future?\n01 - Yes\n02 - No\n"
    )
    assert question_ids(text) == ["Q1", "Q2"]
    imported = Questionnaire(
        id="g",
        title="G",
        questions=[
            Question(
                id="Q1",
                type="single_select",
                text="How satisfied are you with the service overall?",
                options=[
                    Option(code=1, label="Very Dissatisfied // 1"),
                    Option(code=2, label="2"),
                    Option(code=3, label="Very Satisfied // 3"),
                    Option(code=4, label="Don't know // 99"),
                ],
            ),
            Question(
                id="Q2",
                type="single_select",
                text="Would you use it again in the future?",
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
            ),
        ],
    )
    cleaned = clean_cell_breaks(imported)
    assert [(o.code, o.label) for o in cleaned.questions[0].options] == [
        (1, "Very Dissatisfied"),
        (2, "2"),
        (3, "Very Satisfied"),
        (99, "Don't know"),
    ]
    report = check_exact(cleaned, text)
    assert report.ok, report.messages()


def test_house_codes_for_other_none_and_refusal() -> None:
    """Position-numbered lists get Other 98 and None 99; codes the file writes stay."""
    from app.services.questionnaire_import import house_codes

    numbered = Question(
        id="S9",
        type="multi_select",
        text="Which genres?",
        options=[
            Option(code=1, label="Pop"),
            Option(code=2, label="Rock"),
            Option(code=3, label="Other (Specify)", open_text=True),
            Option(code=4, label="None of these", exclusive=True),
        ],
        exclusive_codes=[4],
    )
    explicit = Question(
        id="S2",
        type="single_select",
        text="Gender?",
        options=[
            Option(code=1, label="Male"),
            Option(code=2, label="Female"),
            Option(code=97, label="Other"),
            Option(code=99, label="Prefer not to answer"),
        ],
    )
    document = house_codes(Questionnaire(id="h", title="H", questions=[numbered, explicit]))
    assert [o.code for o in document.questions[0].options] == [1, 2, 98, 99]
    assert document.questions[0].exclusive_codes == [99]
    assert [o.code for o in document.questions[1].options] == [1, 2, 97, 99]


def test_use_this_questionnaire_is_a_fixed_route() -> None:
    """Short import requests always reach the questionnaire specialist."""
    from app.agents.intent import product_lock

    for text in ("Use this questionnaire", "Import this survey", "please use the attached file"):
        assert product_lock(text) == "create_questionnaire", text
    assert product_lock("show me the crosstab of Q1 by gender") is None
