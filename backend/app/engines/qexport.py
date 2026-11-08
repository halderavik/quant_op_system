"""Export a questionnaire to DOCX, Markdown, and JSON."""

import json
from io import BytesIO

from docx import Document
from docx.shared import Pt, RGBColor

from app.schemas.questionnaire import Option, Question, Questionnaire

_BLUE = RGBColor(0x04, 0x32, 0xFF)
_RULE = "PROGRAMMING NOTES ARE IN BLUE TEXT. DO NOT SHOW PROGRAMMING NOTES TO RESPONDENTS."
_RESPONDENT = {
    "single_select": "Please select one.",
    "screener": "Please select one.",
    "multi_select": "Please select all that apply.",
    "rating": "Please select one.",
    "numeric": "Please enter a number.",
    "text": "Please type your answer.",
    "grid": "Please select one answer per row.",
    "matrix": "Please select one answer per row.",
    "rank": "Please rank the items.",
    "allocation": "Please enter a number for each item.",
    "date": "Please enter a date.",
}


def to_markdown(document: Questionnaire) -> str:
    """Render a programmer-ready Markdown instrument.

    Args:
        document: Questionnaire.

    Returns:
        Markdown text.
    """
    lines = [f"# {document.title}", ""]
    if document.estimated_minutes is not None:
        lines.append(
            f"Estimated minutes: {document.estimated_minutes}. {document.estimated_minutes_note}"
        )
        lines.append("")
    if document.objectives:
        lines.append("## Objectives")
        for objective in document.objectives:
            covered = ", ".join(objective.question_ids)
            lines.append(f"- {objective.id}: {objective.description} ({covered})")
        lines.append("")
    if document.sample_notes:
        lines.append("## Sample and quotas")
        for note in document.sample_notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.append("## Programming instructions")
    lines.append(f"[PN] {_RULE}")
    for note in document.programming_notes:
        lines.append(f"[PN] {note}")
    lines.append("")
    if document.modules:
        lines.append("## Outline")
        for module in document.modules:
            lines.append(f"- {module.title}")
        lines.append("")
    for title, questions in _sections(document):
        lines.append(f"## {title}")
        lines.append("")
        for question in questions:
            lines.extend(_markdown_question(question))
    return "\n".join(lines)


def to_docx(document: Questionnaire) -> bytes:
    """Render a DOCX instrument with programming notes in blue.

    Args:
        document: Questionnaire.

    Returns:
        DOCX bytes.
    """
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    doc.add_heading(document.title, level=1)
    doc.add_paragraph(document.estimated_minutes_note)
    if document.objectives:
        doc.add_heading("Objectives", level=2)
        for objective in document.objectives:
            doc.add_paragraph(f"{objective.id}: {objective.description}", style="List Bullet")
    if document.sample_notes:
        doc.add_heading("Sample and quotas", level=2)
        for note in document.sample_notes:
            doc.add_paragraph(note, style="List Bullet")
    doc.add_heading("Programming instructions", level=2)
    _blue(doc, _RULE)
    for note in document.programming_notes:
        _blue(doc, note)
    if document.modules:
        doc.add_heading("Outline", level=2)
        for module in document.modules:
            doc.add_paragraph(module.title, style="List Bullet")
    for title, questions in _sections(document):
        doc.add_heading(title, level=2)
        for question in questions:
            _docx_question(doc, question)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def to_json(document: Questionnaire) -> str:
    """Serialize the canonical questionnaire JSON.

    Args:
        document: Questionnaire.

    Returns:
        Indented JSON.
    """
    return json.dumps(document.model_dump(mode="json"), indent=2)


def _sections(document: Questionnaire) -> list[tuple[str, list[Question]]]:
    """Group questions under their modules, preserving document order.

    Args:
        document: Questionnaire.

    Returns:
        Section title and the questions in that section.
    """
    by_id = {question.id: question for question in document.questions}
    assigned: set[str] = set()
    sections: list[tuple[str, list[Question]]] = []
    for module in document.modules:
        questions = [by_id[item] for item in module.question_ids if item in by_id]
        assigned.update(question.id for question in questions)
        if questions:
            sections.append((module.title, questions))
    rest = [question for question in document.questions if question.id not in assigned]
    if rest:
        sections.append(("Questionnaire", rest))
    return sections


def _markdown_question(question: Question) -> list[str]:
    """Render one question, its codes, and its programming notes.

    Args:
        question: Question.

    Returns:
        Markdown lines, including a trailing blank line.
    """
    lines = [f"### {question.id}. {question.text}", ""]
    instruction = _respondent_instruction(question)
    if instruction:
        lines.append(instruction)
        lines.append("")
    if question.type in {"grid", "matrix"} and question.matrix_items and question.options:
        headers = ["Item"] + [f"{option.code}. {option.label}" for option in question.options]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for item in question.matrix_items:
            lines.append("| " + " | ".join([item] + ["" for _ in question.options]) + " |")
        lines.append("")
    elif question.options:
        lines.append("| Code | Label |")
        lines.append("| --- | --- |")
        for option in question.options:
            lines.append(f"| {option.code} | {_option_label(option)} |")
        lines.append("")
    for note in _programmer_lines(question):
        lines.append(f"[PN] {note}")
    lines.append("")
    return lines


def _docx_question(doc: Document, question: Question) -> None:
    """Add one question card to the document.

    Args:
        doc: Document being built.
        question: Question.
    """
    doc.add_heading(f"{question.id}. {question.text}", level=3)
    instruction = _respondent_instruction(question)
    if instruction:
        doc.add_paragraph(instruction)
    if question.type in {"grid", "matrix"} and question.matrix_items and question.options:
        table = doc.add_table(rows=1 + len(question.matrix_items), cols=1 + len(question.options))
        table.style = "Table Grid"
        table.rows[0].cells[0].text = "Item"
        for index, option in enumerate(question.options, start=1):
            table.rows[0].cells[index].text = f"{option.code}. {option.label}"
        for row_index, item in enumerate(question.matrix_items, start=1):
            table.rows[row_index].cells[0].text = item
    elif question.options:
        table = doc.add_table(rows=1 + len(question.options), cols=2)
        table.style = "Table Grid"
        table.rows[0].cells[0].text = "Code"
        table.rows[0].cells[1].text = "Label"
        for index, option in enumerate(question.options, start=1):
            table.rows[index].cells[0].text = str(option.code)
            table.rows[index].cells[1].text = _option_label(option)
    for note in _programmer_lines(question):
        _blue(doc, note)


def _respondent_instruction(question: Question) -> str:
    """Return the respondent-facing instruction.

    Args:
        question: Question.

    Returns:
        Instruction text, or an empty string for display-only items.
    """
    if question.instruction:
        return question.instruction
    return _RESPONDENT.get(question.type, "")


def _option_label(option: Option) -> str:
    """Append a terminate mark when the option ends the interview.

    Args:
        option: Response option.

    Returns:
        Label shown in the code table.
    """
    label = str(option.label)
    if option.terminate and "TERMINATE" not in label.upper():
        return f"{label}  TERMINATE"
    return label


def _programmer_lines(question: Question) -> list[str]:
    """Build the programming note for one question.

    Args:
        question: Question.

    Returns:
        Note lines. These are not respondent text.
    """
    lines = list(question.programmer_notes)
    if question.display_if is not None:
        lines.append(f"[BASE: {_expr_text(question.display_if)}]")
    else:
        lines.append("[BASE: ALL]")
    lines.append(_answer_rule(question))
    if question.randomize_options:
        lines.append("Randomize the list. Keep anchored codes in the order shown.")
    else:
        lines.append("Do not randomize.")
    exclusive = [str(option.code) for option in question.options if option.exclusive]
    if exclusive:
        lines.append("Mutually exclusive codes: " + ", ".join(exclusive) + ".")
    anchored = [str(option.code) for option in question.options if option.anchor]
    if anchored:
        lines.append("Anchor codes: " + ", ".join(anchored) + ".")
    terminating = [str(option.code) for option in question.options if option.terminate]
    if terminating:
        lines.append("TERMINATE if code " + ", ".join(terminating) + ".")
    for rule in question.routing:
        condition = f" when {_expr_text(rule.when)}" if rule.when is not None else ""
        lines.append(f"Route to {rule.go_to}{condition}.")
    if question.variable_names:
        lines.append("Programmed variables: " + ", ".join(question.variable_names) + ".")
    elif question.type == "multi_select":
        names = [f"{question.id}r{option.code}" for option in question.options]
        if names:
            lines.append("Program each response as " + ", ".join(names) + ".")
    if any(option.open_text for option in question.options):
        specify = f"{question.id}r98oe"
        if specify not in question.variable_names:
            lines.append(f"Program the other-specify as {specify}.")
    lines.append("Do not show this programming note to respondents.")
    return lines


def _answer_rule(question: Question) -> str:
    """Describe how many answers the question accepts.

    Args:
        question: Question.

    Returns:
        One programming sentence.
    """
    if question.type == "multi_select":
        return "Allow multiple responses."
    if question.type == "numeric":
        return "Numeric entry."
    if question.type == "text":
        return "Open-end text."
    if question.type in {"grid", "matrix"}:
        return "Grid. Allow one response per row."
    if question.type in {"display", "terminate"}:
        return "Display text. Do not store a response."
    return "Allow one response."


def _expr_text(expr: object) -> str:
    """Render a routing expression as programmer text.

    Args:
        expr: Comparison or boolean expression.

    Returns:
        Readable condition.
    """
    kind = getattr(expr, "kind", None)
    if kind == "cmp":
        if expr.op in {"answered", "not_answered"}:
            return f"{expr.ref} {expr.op.replace('_', ' ')}"
        return f"{expr.ref} {expr.op} {expr.value}"
    if kind == "bool":
        parts = [_expr_text(arg) for arg in expr.args]
        if expr.op == "not":
            return f"not ({parts[0]})" if parts else "not"
        return f" {expr.op} ".join(parts)
    return str(expr)


def _blue(doc: Document, text: str) -> None:
    """Add one programming note in blue.

    Args:
        doc: Document being built.
        text: Note text.
    """
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.font.color.rgb = _BLUE
    run.font.name = "Calibri"
    run.italic = True
