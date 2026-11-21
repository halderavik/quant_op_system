"""Program one questionnaire question as a Decipher element."""

import re
import xml.etree.ElementTree as ET

from app.engines.decipher_expr import col_labels, safe_label
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
    spec_of,
)
from app.schemas.decipher import CoverageItem, Punch
from app.schemas.questionnaire import Question

_CHOICE = {"single_select", "screener", "rating"}
# Reason: Forsta's rank sort style. Pinned so a live survey's style does not change under it.
_RANKSORT = "ranksort.7"
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_TOP_N = re.compile(
    r"\b(?:top|first|best)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b"
    r"|\brank\s+(?:only\s+|up\s+to\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.I,
)


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
    spec = spec_of(question)
    if spec.dropdown and not multi:
        return _dropdown(parent, question, build)
    node = _question_element(parent, "checkbox" if multi else "radio", question, build)
    if multi and question.required:
        node.set("atleast", str(spec.min_choices or 1))
    if multi and spec.max_choices:
        node.set("atmost", str(spec.max_choices))
    punches = _option_rows(node, question, build, values=not multi)
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "checkbox" if multi else "radio", "programmed", [], punches)


def _dropdown(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """A single choice shown as a drop-down list (Decipher select with choices)."""
    node = _question_element(parent, "select", question, build)
    labels = build.rows.get(question.id, {})
    punches: list[Punch] = []
    for index, option in enumerate(question.options, start=1):
        label = labels.get(str(option.code), f"ch{index}")
        code = str(option.code)
        add_element(
            node,
            "choice",
            option.label,
            label=label,
            value=code if code.lstrip("-").isdigit() else None,
        )
        punches.append(Punch(code=code, label=option.label, row_label=label))
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "select", "programmed", [], punches)


def _boxes(node: ET.Element, question: Question, build: SurveyBuild) -> list[Punch]:
    """Separate entry boxes (r1..rN) filled in order; the first one is required."""
    count = spec_of(question).boxes or 0
    if count < 2:
        return []
    name = build.labels[question.id]
    punches = []
    for index in range(1, count + 1):
        add_element(node, "row", "", label=f"r{index}")
        punches.append(Punch(code=str(index), label=f"Box {index}", row_label=f"r{index}"))
    add_element(
        node,
        "validate",
        f"for i in range(1, len({name}.rows)):\n"
        f"    if {name}.rows[i].val not in (None, '') and {name}.rows[i - 1].val in (None, ''):\n"
        '        error("Please fill in the boxes in order.")\n'
        f"if {name}.rows[0].val in (None, ''):\n"
        '    error("Please provide an answer.")\n',
    )
    return punches


def _grid(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a grid. Missing rows or scale points are not invented.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    tag = "checkbox" if spec_of(question).multiple else "radio"
    node = _question_element(parent, tag, question, build)
    if tag == "checkbox" and question.required:
        node.set("atleast", "1")
    punches: list[Punch] = []
    columns = col_labels(question.options)
    codes = [str(option.code) for option in question.options]
    repeated = len(set(codes)) != len(codes)
    if repeated:
        # Reason: "Which is closer to your view?" pairs each numbered 1, 2 read as one
        # scale; Decipher needs unique column labels, so number them by position.
        _warn(
            build,
            f"{question.id} repeats answer codes ({', '.join(codes)}); it may be several "
            "either/or questions. Columns are numbered by position; check the structure.",
        )
    for position, option in enumerate(question.options, start=1):
        code = str(option.code)
        label, value = (f"c{position}", code) if repeated else columns[code]
        add_element(node, "col", option.label, label=label, value=value)
        punches.append(Punch(code=code, label=option.label, row_label=label))
    row_names = build.rows.get(question.id, {})
    for index, item in enumerate(question.matrix_items, start=1):
        label = row_names.get(str(index), f"r{index}")
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
    return _item(question, build, tag, status, warnings, punches)


def _numeric(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a number entry without inventing a range.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    spec = spec_of(question)
    node = _question_element(
        parent,
        "number",
        question,
        build,
        size=_number_size(spec.max_value),
        verify=_verify(spec.min_value, spec.max_value),
        amount=_whole(spec.total),
        **({"ss:listDisplay": "0"} if _rows_of(question) else {}),
    )
    punches = (
        _option_rows(node, question, build) if _rows_of(question) else _boxes(node, question, build)
    )
    if not _rows_of(question):
        for code in spec.noanswer_codes:
            option = next((o for o in question.options if str(o.code) == str(code)), None)
            if option is not None:
                label = build.rows.get(question.id, {}).get(str(code), f"r{code}")
                add_element(node, "noanswer", option.label, label=label)
                punches.append(Punch(code=str(code), label=option.label, row_label=label))
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "number", "programmed", [], punches)


def _rows_of(question: Question) -> bool:
    """Whether a number question asks for one number per option (not only a no-answer box)."""
    noanswer = {str(code) for code in spec_of(question).noanswer_codes}
    return any(str(option.code) not in noanswer for option in question.options)


def _verify(low: float | None, high: float | None) -> str | None:
    """Decipher range check, such as range(0,999)."""
    if low is None and high is None:
        return None
    low_text = _whole(low) if low is not None else "0"
    high_text = _whole(high) if high is not None else "999999999"
    return f"range({low_text},{high_text})"


def _whole(value: float | None) -> str | None:
    """A number without a trailing .0."""
    if value is None:
        return None
    return str(int(value)) if float(value).is_integer() else str(value)


def _number_size(high: float | None) -> str:
    """Box width that fits the largest allowed number."""
    if high is None:
        return "5"
    return str(max(2, len(str(int(abs(high)))) + 1))


def _textarea(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program an open-end text question.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    spec = spec_of(question)
    tag = "text" if spec.single_line or (spec.boxes or 0) > 1 else "textarea"
    node = _question_element(parent, tag, question, build, size="50" if tag == "text" else None)
    punches: list[Punch] = _boxes(node, question, build)
    for code in spec.noanswer_codes:
        option = next((o for o in question.options if str(o.code) == str(code)), None)
        if option is not None:
            label = build.rows.get(question.id, {}).get(str(code), f"r{code}")
            add_element(node, "noanswer", option.label, label=label)
            punches.append(Punch(code=str(code), label=option.label, row_label=label))
    if spec.min_chars:
        name = build.labels[question.id]
        add_element(
            node,
            "validate",
            f"if len({name}.val.strip()) lt {spec.min_chars}:\n"
            f'    error("Please enter at least {spec.min_chars} characters.")\n',
        )
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, tag, "programmed", [], punches)


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
    spec = spec_of(question)
    total = spec.total if spec.total is not None else 100
    node = _question_element(parent, "number", question, build, size=_number_size(total))
    punches = _option_rows(node, question, build)
    warnings: list[str] = []
    status = "programmed"
    if punches:
        node.set("verify", _verify(spec.min_value or 0, spec.max_value or total) or "")
        node.set("amount", _whole(total) or "100")
        node.set("ss:listDisplay", "0")
    else:
        status = "partial"
        warnings.append(
            f"{question.id} has no allocation rows, so a total of 100 was not programmed."
        )
        _warn(build, warnings[-1])
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "number", status, warnings, punches)


def _rank(parent: ET.Element, question: Question, build: SurveyBuild) -> CoverageItem:
    """Program a rank as a drag-and-drop rank sort.

    Each option is a row and each rank position is a choice. ``unique="none,cols"``
    stops two items sharing a rank. A "top N" question gets N rank positions,
    optional rows, and a check that exactly N items were ranked.

    Args:
        parent: Parent element.
        question: Question.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    label = build.labels[question.id]
    count = len(question.options)
    top = rank_limit(question)
    partial = top is not None and top < count
    node = _question_element(parent, "select", question, build, unique="none,cols", uses=_RANKSORT)
    positions = top if partial and top is not None else count
    # Reason: Decipher rejects the ranksort style without minRanks, the items each respondent must rank.
    node.set("minRanks", str(max(positions, 1)))
    if partial:
        node.set("optional", "1")
    punches = _option_rows(node, question, build)
    for index in range(1, positions + 1):
        add_element(node, "choice", str(index), label=f"ch{index}")
    warnings: list[str] = []
    status = "programmed"
    if partial:
        # Reason: optional rows let respondents skip items, so the exact count is checked here.
        script = (
            f"ranked = len([row for row in {label}.rows if row.val is not None])\n"
            f"if ranked != {positions}:\n"
            f'    error("Please rank exactly {positions} items")\n'
        )
        add_element(node, "validate", script)
    if count < 2:
        status = "partial"
        warnings.append(
            f"{question.id} is a rank with fewer than two items, so nothing can be ordered."
        )
        _warn(build, warnings[-1])
    _terms_and_gotos(parent, question, build, punches)
    return _item(question, build, "select", status, warnings, punches)


def rank_limit(question: Question) -> int | None:
    """Return N when the question asks for only the top N items.

    Args:
        question: Rank question.

    Returns:
        N, or None when every item is ranked.
    """
    blob = " ".join([question.text, question.instruction or "", *question.programmer_notes])
    match = _TOP_N.search(blob)
    if match is None:
        return None
    word = (match.group(1) or match.group(2)).lower()
    value = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
    return value if value and value > 0 else None


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
