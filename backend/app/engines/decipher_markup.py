"""Shared Decipher element helpers."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from app.engines.decipher_expr import combined_condition, safe_label, translate
from app.schemas.decipher import CoverageItem, Punch
from app.schemas.questionnaire import Option, Question


@dataclass
class SurveyBuild:
    """Labels and maps shared while the survey XML is built."""

    questions: dict[str, Question]
    labels: dict[str, str]
    rows: dict[str, dict[str, str]]
    cols: dict[str, dict[str, str]]
    hides: dict[str, list[str]]
    used: set[str]
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def add_element(
    parent: ET.Element, tag: str, text: str | None = None, **attrs: object
) -> ET.Element:
    """Append an element, omitting empty attributes.

    Args:
        parent: Parent element.
        tag: Decipher tag.
        text: Text content.
        attrs: Attributes. None and empty strings are omitted.

    Returns:
        New element.
    """
    clean = {key: str(value) for key, value in attrs.items() if value is not None and value != ""}
    node = ET.SubElement(parent, tag, clean)
    if text is not None:
        node.text = text
    return node


def _question_element(
    parent: ET.Element,
    tag: str,
    question: Question,
    build: SurveyBuild,
    **attrs: object,
) -> ET.Element:
    """Create a question element with its condition, title, and notes.

    Args:
        parent: Parent element.
        tag: Decipher tag.
        question: Question.
        build: Shared build state.
        attrs: Extra attributes such as size.

    Returns:
        Question element.
    """
    _notes(parent, question)
    node = add_element(
        parent,
        tag,
        label=build.labels[question.id],
        optional="0" if question.required else "1",
        cond=_condition(question, build),
        shuffle="rows" if question.randomize_options and question.options else None,
        **attrs,
    )
    _titles(node, question)
    return node


def _titles(node: ET.Element, question: Question) -> None:
    """Add the respondent title and instruction.

    Args:
        node: Question element.
        question: Question.
    """
    add_element(node, "title", question.text)
    if question.instruction:
        add_element(node, "comment", question.instruction)


def _notes(parent: ET.Element, question: Question) -> None:
    """Copy programmer notes into comments placed before the question.

    Decipher rejects a ``note`` element inside ``radio``, ``checkbox``, and
    ``textarea``. Comments stay in the file and are not shown to respondents.

    Args:
        parent: Survey or block that will contain the question.
        question: Question.
    """
    for note in question.programmer_notes:
        parent.append(ET.Comment(f" {question.id}: {_comment_body(note)} "))


def _comment_body(note: str) -> str:
    """Return note text that can sit inside an XML comment.

    Args:
        note: Programmer note.

    Returns:
        One line, with a double hyphen removed so the comment stays well formed.
    """
    return " ".join(note.split()).replace("--", "-")


def _option_rows(node: ET.Element, question: Question) -> list[Punch]:
    """Add one row per option.

    Args:
        node: Question element.
        question: Question.

    Returns:
        Punches in option order.
    """
    punches: list[Punch] = []
    for index, option in enumerate(question.options, start=1):
        row_label = f"r{index}"
        attrs: dict[str, str] = {}
        if _exclusive(option, question):
            attrs["exclusive"] = "1"
        if option.open_text:
            attrs["open"] = "1"
            attrs["openSize"] = "25"
        if question.randomize_options and (
            option.anchor or option.open_text or _exclusive(option, question)
        ):
            attrs["randomize"] = "0"
        add_element(node, "row", option.label, label=row_label, **attrs)
        punches.append(Punch(code=str(option.code), label=option.label, row_label=row_label))
    return punches


def _exclusive(option: Option, question: Question) -> bool:
    """Return whether an option is mutually exclusive.

    Args:
        option: Response option.
        question: Question that owns the option.

    Returns:
        True when the flag or the exclusive code list says so.
    """
    return option.exclusive or str(option.code) in {str(code) for code in question.exclusive_codes}


def _terms_and_gotos(
    parent: ET.Element,
    question: Question,
    build: SurveyBuild,
    punches: list[Punch],
) -> None:
    """Append terminate elements and backward jumps after a question.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.
        punches: Rows just programmed, used for option terminates.
    """
    by_code = {punch.code: punch.row_label for punch in punches}
    for option in question.options:
        if not option.terminate:
            continue
        row_label = by_code.get(str(option.code))
        if row_label is None:
            continue
        label = safe_label(f"Term_{build.labels[question.id]}_{row_label}", build.used)
        add_element(
            parent,
            "term",
            "Thank you for your time.",
            label=label,
            cond=f"{build.labels[question.id]}.{row_label}",
        )
    ids = list(build.questions)
    start = ids.index(question.id) if question.id in ids else -1
    for rule in question.routing:
        if rule.go_to == "TERMINATE":
            condition = (
                translate(
                    rule.when, build.questions, build.labels, build.rows, build.cols, build.issues
                )
                if rule.when is not None
                else "1"
            )
            label = safe_label(f"Term_{build.labels[question.id]}", build.used)
            add_element(parent, "term", "Thank you for your time.", label=label, cond=condition)
        elif rule.go_to in build.labels and start >= 0 and ids.index(rule.go_to) < start:
            condition = (
                translate(
                    rule.when, build.questions, build.labels, build.rows, build.cols, build.issues
                )
                if rule.when is not None
                else "1"
            )
            add_element(parent, "goto", target=build.labels[rule.go_to], cond=condition)


def _condition(question: Question, build: SurveyBuild) -> str | None:
    """Return the show-if condition for a question.

    Args:
        question: Question.
        build: Shared build state.

    Returns:
        Decipher condition, or None when the question is always shown.
    """
    return combined_condition(
        question,
        build.hides.get(question.id, []),
        build.questions,
        build.labels,
        build.rows,
        build.cols,
        build.issues,
    )


def _item(
    question: Question,
    build: SurveyBuild,
    element: str,
    status: str,
    warnings: list[str],
    punches: list[Punch],
) -> CoverageItem:
    """Build a coverage row.

    Args:
        question: Question.
        build: Shared build state.
        element: Decipher tag.
        status: ``programmed`` or ``partial``.
        warnings: Warnings for this question.
        punches: Code map.

    Returns:
        Coverage item.
    """
    return CoverageItem(
        question_id=question.id,
        label=build.labels[question.id],
        element=element,
        status="partial" if status == "partial" else "programmed",
        warnings=warnings,
        punches=punches,
    )


def _warn(build: SurveyBuild, message: str) -> None:
    """Record a programming warning once.

    Args:
        build: Shared build state.
        message: Warning text.
    """
    if message not in build.warnings:
        build.warnings.append(message)
