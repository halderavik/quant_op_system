"""Program one questionnaire question as a Decipher element."""

import xml.etree.ElementTree as ET

from app.engines.decipher_expr import safe_label
from app.engines.decipher_markup import (
    SurveyBuild,
    _comment_body,
    _condition,
    _item,
    _notes,
    _option_rows,
    _question_element,
    _terms_and_gotos,
    _titles,
    _warn,
    add_element,
)
from app.schemas.decipher import CoverageItem, Punch
from app.schemas.questionnaire import Question

_CHOICE = {"single_select", "screener", "rating"}


def emit_question(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Append one question and the terminate or goto elements that follow it.

    Args:
        parent: Survey or block element.
        question: Question to program.
        build: Shared labels and warnings.

    Returns:
        Coverage for this question.
    """
    if question.unsupported:
        return _unsupported(parent, question, build)
    if question.type == "display":
        return _display(parent, question, build)
    if question.type == "terminate":
        return _terminate(parent, question, build)
    if question.type in _CHOICE or question.type == "multi_select":
        return _choice(parent, question, build)
    if question.type in {"grid", "matrix"}:
        return _grid(parent, question, build)
    if question.type == "numeric":
        return _numeric(parent, question, build)
    if question.type == "text":
        return _textarea(parent, question, build)
    if question.type == "date":
        return _date(parent, question, build)
    if question.type == "allocation":
        return _allocation(parent, question, build)
    if question.type == "rank":
        return _rank(parent, question, build)
    if question.type == "loop":
        return _loop(parent, question, build)
    return _unsupported(parent, question, build)


def _choice(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a single-select, screener, rating, or multi-select.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    multi = question.type == "multi_select"
    node = _question_element(parent, "checkbox" if multi else "radio", question, build)
    if multi and question.required:
        node.set("atleast", "1")
    punches = _option_rows(node, question)
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "checkbox" if multi else "radio", "programmed", [], punches)


def _grid(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a grid. Missing rows or scale points are not invented.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    node = _question_element(parent, "radio", question, build)
    punches: list[Punch] = []
    for index, option in enumerate(question.options, start=1):
        label = f"c{index}"
        add_element(node, "col", option.label, label=label)
        punches.append(Punch(code=str(option.code), label=option.label, row_label=label))
    for index, item in enumerate(question.matrix_items, start=1):
        label = f"r{index}"
        add_element(node, "row", item, label=label)
        punches.append(Punch(code=str(index), label=item, row_label=label))
    warnings: list[str] = []
    status = "programmed"
    if not question.matrix_items or not question.options:
        status = "partial"
        warnings.append(
            f"{question.id} has no rows or scale points, so no grid cells were invented."
        )
        _warn(build, warnings[-1])
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "radio", status, warnings, punches)


def _numeric(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a number entry without inventing a range.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    _question_element(parent, "number", question, build, size="5")
    _terms_and_gotos(parent, question, build, [])
    return _item(question, build, "number", "programmed", [], [])


def _textarea(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program an open-end text question.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    _question_element(parent, "textarea", question, build)
    _terms_and_gotos(parent, question, build, [])
    return _item(question, build, "textarea", "programmed", [], [])


def _date(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a date as text entry. No calendar style is attached.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    label = build.labels[question.id]
    node = _question_element(parent, "text", question, build, size="10")
    script = (
        f"value = {label}.val\n"
        "parts = value.split('-') if value else []\n"
        "ok = len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit() "
        "and len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2\n"
        "if value and not ok:\n"
        '    error("Please enter a date as YYYY-MM-DD")\n'
    )
    add_element(node, "validate", script)
    warning = (
        f"{question.id} is a date. No calendar style is attached. Respondents enter YYYY-MM-DD."
    )
    _warn(build, warning)
    _terms_and_gotos(parent, question, build, [])
    return _item(question, build, "text", "partial", [warning], [])


def _allocation(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a 100-point allocation when the question has rows.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    label = build.labels[question.id]
    node = _question_element(parent, "number", question, build, size="3")
    punches = _option_rows(node, question)
    warnings: list[str] = []
    status = "programmed"
    if punches:
        node.set("verify", "range(0,100)")
        total = " + ".join(f"{label}.{punch.row_label}.ival" for punch in punches)
        script = (
            f"total = {total}\n"
            "if total != 100:\n"
            '    error("Please make sure the numbers total 100")\n'
        )
        add_element(node, "validate", script)
    else:
        status = "partial"
        warnings.append(
            f"{question.id} has no allocation rows, so a total of 100 was not programmed."
        )
        _warn(build, warnings[-1])
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "number", status, warnings, punches)


def _rank(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a rank as unique choices. No visual rank-sort style is attached.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    node = _question_element(parent, "select", question, build)
    node.set("unique", "none,cols")
    punches = _option_rows(node, question)
    for index, _option in enumerate(question.options, start=1):
        add_element(node, "choice", str(index), label=f"ch{index}")
    warning = f"{question.id} is a rank. A visual rank-sort style is not attached, so this is a unique choice list."
    _warn(build, warning)
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "select", "partial", [warning], punches)


def _loop(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a loop shell. Nested questions are not invented.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    label = build.labels[question.id]
    _notes(parent, question)
    node = add_element(parent, "loop", label=label, vars="item", cond=_condition(question, build))
    _titles(node, question)
    block_label = safe_label(f"Block_{label}_body", build.used)
    block = add_element(node, "block", label=block_label)
    block.append(ET.Comment(" Nested questions are not in the questionnaire schema. "))
    punches: list[Punch] = []
    for index, option in enumerate(question.options, start=1):
        row_label = f"r{index}"
        row = add_element(node, "looprow", label=row_label)
        add_element(row, "loopvar", option.label, name="item")
        punches.append(Punch(code=str(option.code), label=option.label, row_label=row_label))
    warning = f"{question.id} is a loop. Nested questions are not in the questionnaire, so the loop body is empty."
    _warn(build, warning)
    return _item(question, build, "loop", "partial", [warning], punches)


def _display(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program respondent-facing display text.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    _notes(parent, question)
    add_element(
        parent,
        "html",
        question.text,
        label=build.labels[question.id],
        where="survey",
        cond=_condition(question, build),
    )
    return _item(question, build, "html", "programmed", [], [])


def _terminate(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a question whose only job is to end the interview.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    add_element(
        parent,
        "term",
        question.text or "Thank you for your time.",
        label=build.labels[question.id],
        cond=_condition(question, build) or "1",
    )
    return _item(question, build, "term", "programmed", [], [])


def _unsupported(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Keep an unsupported question in the file as a programmer note.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Partial coverage item.
    """
    warning = (
        f"{question.id} is marked unsupported and was exported as a note, not a live question."
    )
    _notes(parent, question)
    add_element(
        parent,
        "html",
        question.text,
        label=build.labels[question.id],
        where="survey",
    )
    parent.append(ET.Comment(f" {_comment_body(warning)} "))
    _warn(build, warning)
    return _item(question, build, "html", "partial", [warning], [])
