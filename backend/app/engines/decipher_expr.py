"""Translate questionnaire expressions into Decipher conditions."""

import re

from app.schemas.expression import Comparison, Expr
from app.schemas.questionnaire import Question, Questionnaire

_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_COMPARE = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def safe_label(raw: str, used: set[str]) -> str:
    """Return a unique Decipher label.

    Args:
        raw: Question id, module id, or generated name.
        used: Labels already assigned in this survey.

    Returns:
        A label that starts with a letter and is not in ``used``.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not _LABEL.match(cleaned):
        cleaned = f"Q_{cleaned}".strip("_") or "Q_item"
    candidate = cleaned
    number = 2
    while candidate in used:
        candidate = f"{cleaned}_{number}"
        number += 1
    used.add(candidate)
    return candidate


def punch_maps(
    document: Questionnaire,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Map option codes to row labels, and grid scale codes to column labels.

    Args:
        document: Questionnaire.

    Returns:
        Row maps and column maps, keyed by question id then code.
    """
    rows: dict[str, dict[str, str]] = {}
    cols: dict[str, dict[str, str]] = {}
    for question in document.questions:
        if question.type in {"grid", "matrix"}:
            rows[question.id] = {}
            cols[question.id] = {
                str(option.code): f"c{index}"
                for index, option in enumerate(question.options, start=1)
            }
        else:
            rows[question.id] = {
                str(option.code): f"r{index}"
                for index, option in enumerate(question.options, start=1)
            }
            cols[question.id] = {}
    return rows, cols


def skip_hides(
    document: Questionnaire,
    labels: dict[str, str],
    rows: dict[str, dict[str, str]],
    cols: dict[str, dict[str, str]],
    issues: list[str],
) -> dict[str, list[str]]:
    """Build the extra conditions that hide questions a skip jumps over.

    Args:
        document: Questionnaire.
        labels: Question id to Decipher label.
        rows: Option code to row label.
        cols: Scale code to column label.
        issues: Unknown-reference messages to append.

    Returns:
        Question id to condition fragments that must all be true.
    """
    ids = [question.id for question in document.questions]
    index = {question_id: position for position, question_id in enumerate(ids)}
    questions = {question.id: question for question in document.questions}
    extra = {question_id: [] for question_id in ids}
    for question in document.questions:
        start = index[question.id]
        for rule in question.routing:
            if rule.go_to == "TERMINATE":
                continue
            target = len(ids) if rule.go_to == "END" else index.get(rule.go_to)
            if target is None or target <= start + 1:
                continue
            condition = translate(rule.when, questions, labels, rows, cols, issues)
            for question_id in ids[start + 1 : target]:
                extra[question_id].append(f"not ({condition})")
    return extra


def translate(
    expr: Expr | None,
    questions: dict[str, Question],
    labels: dict[str, str],
    rows: dict[str, dict[str, str]],
    cols: dict[str, dict[str, str]],
    issues: list[str],
) -> str:
    """Render one expression as a Decipher condition.

    Args:
        expr: Comparison or boolean expression. None means always true.
        questions: Questions by id.
        labels: Question id to Decipher label.
        rows: Option code to row label.
        cols: Scale code to column label.
        issues: Unknown-reference messages to append.

    Returns:
        Decipher condition text.
    """
    if expr is None:
        return "1"
    if isinstance(expr, Comparison):
        return _comparison(expr, questions, labels, rows, cols, issues)
    parts = [translate(arg, questions, labels, rows, cols, issues) for arg in expr.args]
    if expr.op == "not":
        return f"not ({parts[0]})" if parts else "not (1)"
    joiner = " and " if expr.op == "and" else " or "
    return "(" + joiner.join(parts) + ")"


def _comparison(
    expr: Comparison,
    questions: dict[str, Question],
    labels: dict[str, str],
    rows: dict[str, dict[str, str]],
    cols: dict[str, dict[str, str]],
    issues: list[str],
) -> str:
    """Render one comparison.

    Args:
        expr: Comparison node.
        questions: Questions by id.
        labels: Question id to Decipher label.
        rows: Option code to row label.
        cols: Scale code to column label.
        issues: Unknown-reference messages to append.

    Returns:
        Decipher condition text.
    """
    if expr.ref not in questions:
        issues.append(f"Condition refers to unknown question {expr.ref}.")
    name = labels.get(expr.ref, expr.ref)
    question = questions.get(expr.ref)
    if expr.op == "answered":
        return _presence(name, question)
    if expr.op == "not_answered":
        return f"not {_presence(name, question)}"
    if expr.op in _COMPARE:
        return f"{name}.ival {_COMPARE[expr.op]} {_literal(expr.value)}"
    if expr.op in {"in", "not_in"}:
        clause = _membership(name, question, _as_list(expr.value), rows, cols)
        return clause if expr.op == "in" else f"not ({clause})"
    selected = _selected(name, question, expr.value, rows.get(expr.ref, {}), cols.get(expr.ref, {}))
    if expr.op == "ne":
        return f"not ({selected})" if selected.startswith("(") else f"not {selected}"
    return selected


def _presence(name: str, question: Question | None) -> str:
    """Return the Decipher test for any answer.

    Args:
        name: Decipher label.
        question: Question, when the reference is known.

    Returns:
        ``.any`` for multi-select and grids, otherwise ``.val``.
    """
    if question is not None and question.type in {"multi_select", "grid", "matrix"}:
        return f"{name}.any"
    return f"{name}.val"


def _selected(
    name: str,
    question: Question | None,
    value: object,
    rows: dict[str, str],
    cols: dict[str, str],
) -> str:
    """Return the condition for one selected code or numeric value.

    Args:
        name: Decipher label.
        question: Question, when the reference is known.
        value: Compared value.
        rows: Option code to row label for this question.
        cols: Scale code to column label for this question.

    Returns:
        Decipher condition text.
    """
    key = str(value)
    if question is not None and question.type in {"grid", "matrix"} and key in cols:
        column = cols[key]
        item_rows = [f"r{index}" for index in range(1, len(question.matrix_items) + 1)]
        parts = [f"{name}.{row}.{column}" for row in item_rows] or [f"{name}.{column}"]
        return parts[0] if len(parts) == 1 else "(" + " or ".join(parts) + ")"
    if key in rows:
        return f"{name}.{rows[key]}"
    if question is not None and question.type in {"numeric", "allocation", "date"}:
        return f"{name}.ival == {_literal(value)}"
    return f"{name}.val == {_literal(value)}"


def _membership(
    name: str,
    question: Question | None,
    values: list[object],
    rows: dict[str, dict[str, str]],
    cols: dict[str, dict[str, str]],
) -> str:
    """Return a condition that is true when any listed code is selected.

    Args:
        name: Decipher label.
        question: Question, when the reference is known.
        values: Accepted codes.
        rows: All row maps. This question's map is not required when values are numeric.
        cols: All column maps.

    Returns:
        Parenthesized or of selections.
    """
    question_rows = {}
    question_cols = {}
    if question is not None:
        question_rows = rows.get(question.id, {})
        question_cols = cols.get(question.id, {})
    parts = [_selected(name, question, value, question_rows, question_cols) for value in values]
    return "(" + " or ".join(parts) + ")" if parts else "0"


def _as_list(value: object) -> list[object]:
    """Return a comparison value as a list.

    Args:
        value: Scalar or list from the expression.

    Returns:
        One or more values.
    """
    if isinstance(value, list):
        return list(value)
    return [value]


def _literal(value: object) -> str:
    """Render a Python literal safe to place in a Decipher condition.

    Args:
        value: Compared value.

    Returns:
        Number or quoted string.
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    text = "" if value is None else str(value)
    if text.isdigit():
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def combined_condition(
    question: Question,
    hides: list[str],
    questions: dict[str, Question],
    labels: dict[str, str],
    rows: dict[str, dict[str, str]],
    cols: dict[str, dict[str, str]],
    issues: list[str],
) -> str | None:
    """Join a question's display logic with skip logic that jumps over it.

    Args:
        question: Question being programmed.
        hides: Skip fragments that hide this question.
        questions: Questions by id.
        labels: Question id to Decipher label.
        rows: Option code to row label.
        cols: Scale code to column label.
        issues: Unknown-reference messages to append.

    Returns:
        Condition text, or None when the question is always shown.
    """
    parts: list[str] = []
    if question.display_if is not None:
        parts.append(translate(question.display_if, questions, labels, rows, cols, issues))
    parts.extend(hides)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return " and ".join(f"({part})" for part in parts)
