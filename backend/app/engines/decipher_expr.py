"""Translate questionnaire expressions into Decipher conditions."""

import re
from difflib import SequenceMatcher

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
    by_id = {question.id: question for question in document.questions}
    for question in document.questions:
        if question.type in {"grid", "matrix"}:
            rows[question.id] = grid_row_labels(question, by_id)
            cols[question.id] = {
                code: label for code, (label, _) in col_labels(question.options).items()
            }
        else:
            rows[question.id] = piped_row_labels(question, by_id)
            if question.programming and question.programming.dropdown:
                rows[question.id] = {
                    code: "ch" + label[1:] for code, label in rows[question.id].items()
                }
            cols[question.id] = {}
    for variable in document.derived_variables:
        if variable.values and variable.id not in rows:
            rows[variable.id] = row_labels(variable.values)
            cols[variable.id] = {}
    return rows, cols


def col_labels(options: list) -> dict[str, tuple[str, str | None]]:
    """Scale column labels and values, as Decipher programmers write them.

    Ascending whole-number codes name the columns (c0 ... c10) and need no value;
    other codes keep position labels (c1 ... c5) with the code as the value, as in
    a 5-to-1 agreement scale. A Don't know or Not applicable point coded apart from
    the scale (97, 98, or 9 after a 5-point scale) is named after its code (c97),
    and only the scale points are numbered.

    Args:
        options: Scale points.

    Returns:
        Code to (column label, value or None).
    """
    codes = [str(option.code) for option in options]
    numeric = bool(codes) and all(code.lstrip("-").isdigit() for code in codes)
    if not numeric or len(set(codes)) != len(codes):
        return {
            code: (f"c{index}", code if code.lstrip("-").isdigit() else None)
            for index, code in enumerate(codes, start=1)
        }
    apart = _off_scale_codes(options)
    scale = [code for code in codes if code not in apart]
    values = [int(code) for code in scale]
    labels: dict[str, tuple[str, str | None]] = {}
    if values == sorted(values) and min(values, default=0) >= 0:
        labels.update({code: (f"c{int(code)}", None) for code in scale})
    else:
        labels.update({code: (f"c{index}", code) for index, code in enumerate(scale, start=1)})
    for code in apart:
        labels[code] = (f"c{int(code)}", code)
    return {code: labels[code] for code in codes}


# Reason: kept local to the engines (no services import); matches Don't know style labels.
_APART_LABEL = re.compile(
    r"^\s*(?:(?:i\s+)?don.?t know|do not know|not sure|unsure|not applicable|n/?a\b|none\b"
    r"|prefer not|no opinion|can.?t say|cannot say)",
    re.I,
)


def _off_scale_codes(options: list) -> set[str]:
    """Codes of points outside the scale's run of consecutive numbers (Don't know as 97 or 9)."""
    numbers = sorted({int(option.code) for option in options})
    if len(numbers) < 3:
        return set()
    run_end = numbers[0]
    for number in numbers[1:]:
        if number != run_end + 1:
            break
        run_end = number
    return {
        str(option.code)
        for option in options
        if int(option.code) > run_end + 1
        and (int(option.code) >= 90 or _APART_LABEL.search(str(getattr(option, "label", ""))))
    }


def grid_row_labels(question: Question, questions: dict[str, Question]) -> dict[str, str]:
    """Grid row number to row label.

    Rows piped from an earlier question (``row_condition``) take that question's
    row labels, matched by text, so Decipher's ``rowCond`` lines up.

    Args:
        question: Grid question.
        questions: Questions by id.

    Returns:
        "1", "2", ... to labels such as r1 or r98.
    """
    source = piped_source(question, questions)
    labels: dict[str, str] = {}
    taken: set[str] = set()
    match = row_matcher(source)
    for index, item in enumerate(question.matrix_items, start=1):
        label = match(item) or f"r{index}"
        if label in taken:
            label = f"r{index}_{index}"
        taken.add(label)
        labels[str(index)] = label
    return labels


def piped_row_labels(question: Question, questions: dict[str, Question]) -> dict[str, str]:
    """Row labels of a list question, lined up with the question its rows are piped from.

    Rows are named after their own codes (r1, r98). When the rows are piped from an
    earlier list ("ONLY SHOW PRODUCTS PURCHASED AT Q1") and a row's code differs from
    the source's code for the same wording, the row takes the source's label, so
    ``rowCond="Q1[row]"`` shows the right rows.

    Args:
        question: A list question (not a grid).
        questions: Questions by id.

    Returns:
        Code to row label.
    """
    own = row_labels(question.options)
    source = piped_source(question, questions)
    if source is None or not question.options:
        return own
    match = row_matcher(source)
    wanted = {str(o.code): match(o.label) for o in question.options}
    moved = {code: label for code, label in wanted.items() if label and label != own[code]}
    if not moved:
        return own
    kept = {label for code, label in own.items() if code not in moved}
    labels = dict(own)
    for code, label in moved.items():
        if label not in kept:
            labels[code] = label
            kept.add(label)
    return labels


def piped_source(question: Question, questions: dict[str, Question]) -> Question | None:
    """The earlier question whose answers decide which of this question's rows show."""
    spec = question.programming
    return questions.get(spec.row_condition.source) if spec and spec.row_condition else None


def row_key(text: str) -> str:
    """Row wording reduced for matching: case, punctuation, and "(specify)" ignored."""
    text = re.sub(r"\((?:please\s+)?specify\)|_{2,}|:+\s*$", " ", text.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def row_matcher(source: Question | None):
    """Find the source row label for a piped row's wording.

    Exact wording first, then the same words without punctuation, then a close
    match (a questionnaire often words a piped list slightly differently).

    Args:
        source: Question the rows are piped from, or None.

    Returns:
        A function from row wording to the source's row label, or None.
    """
    if source is None:
        return lambda text: None
    if source.type in {"grid", "matrix"}:
        # Reason: a grid source's rows are its items, labelled by position.
        pairs = [(item, f"r{index}") for index, item in enumerate(source.matrix_items, start=1)]
    else:
        codes = row_labels(source.options) if source.options else {}
        pairs = [(option.label, codes[str(option.code)]) for option in source.options]
    exact = {" ".join(text.lower().split()): label for text, label in pairs}
    loose: dict[str, str] = {}
    for text, label in pairs:
        loose.setdefault(row_key(text), label)

    def match(text: str) -> str | None:
        found = exact.get(" ".join(text.lower().split())) or loose.get(row_key(text))
        if found:
            return found
        key = row_key(text)
        scored = sorted(
            ((SequenceMatcher(None, key, other).ratio(), label) for other, label in loose.items()),
            reverse=True,
        )
        if (
            scored
            and scored[0][0] >= 0.85
            and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.05)
        ):
            return scored[0][1]
        return None

    return match


def row_labels(options: list) -> dict[str, str]:
    """Row labels named after the punch codes (r1, r98, r99), as Decipher programmers write them.

    Args:
        options: Options or derived values with a ``code``.

    Returns:
        Code to row label. Falls back to position labels when codes are not unique whole numbers.
    """
    codes = [str(option.code) for option in options]
    if codes and all(code.isdigit() for code in codes) and len(set(codes)) == len(codes):
        return {code: f"r{int(code)}" for code in codes}
    return {code: f"r{index}" for index, code in enumerate(codes, start=1)}


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
    from app.engines.flow import reference_table

    _, questions, _ = reference_table(document)  # derived variables can be skip conditions too
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
    if expr.value_ref:
        return _ref_comparison(expr, name, question, questions, labels, rows)
    if expr.aggregate == "count":
        op = _COMPARE.get(expr.op) or {"eq": "==", "ne": "!="}.get(expr.op, ">=")
        return f"{name}.count {op} {_literal(expr.value)}"
    if expr.row is not None and question is not None:
        return _row_comparison(expr, name, question, rows.get(expr.ref, {}), cols.get(expr.ref, {}))
    if expr.op == "answered":
        return _presence(name, question)
    if expr.op == "not_answered":
        return f"not {_presence(name, question)}"
    if expr.op in _COMPARE:
        return f"{name}.ival {_COMPARE[expr.op]} {_literal(expr.value)}"
    if expr.op in {"in", "not_in"}:
        clause = _membership(name, question, _as_list(expr.value), rows, cols)
        return clause if expr.op == "in" else _answered_but_not(name, question, f"not ({clause})")
    selected = _selected(name, question, expr.value, rows.get(expr.ref, {}), cols.get(expr.ref, {}))
    if expr.op == "ne":
        negated = f"not ({selected})" if selected.startswith("(") else f"not {selected}"
        return _answered_but_not(name, question, negated)
    return selected


def _answered_but_not(name: str, question: Question | None, negated: str) -> str:
    """An "ask if Q5 is not 99" base on a select-all question also needs Q5 to have been answered.

    Without the guard, a respondent who never saw Q5 also passes ``not Q5.r99``.
    Programmers write ``(Q5.any and not Q5.r99)``.
    """
    if question is not None and question.type == "multi_select":
        return f"({name}.any and {negated})"
    return negated


def _ref_comparison(
    expr: Comparison,
    name: str,
    question: Question | None,
    questions: dict[str, Question],
    labels: dict[str, str],
    rows: dict[str, dict[str, str]],
) -> str:
    """Compare two numeric answers, such as C2 > C1."""

    def side(label: str, ref: str, row: object) -> str:
        if row is None:
            return f"{label}.ival"
        return f"{label}.{rows.get(ref, {}).get(str(row), f'r{row}')}.ival"

    op = _COMPARE.get(expr.op) or {"eq": "==", "ne": "!="}.get(expr.op, "==")
    other = labels.get(expr.value_ref or "", expr.value_ref or "")
    return (
        f"{side(name, expr.ref, expr.row)} {op} {side(other, expr.value_ref or '', expr.value_row)}"
    )


def _row_comparison(
    expr: Comparison,
    name: str,
    question: Question,
    rows: dict[str, str],
    cols: dict[str, str],
) -> str:
    """One row of a grid, a numeric list, or a multi-select.

    Args:
        expr: Comparison with ``row`` set.
        name: Decipher label.
        question: Referenced question.
        rows: Code to row label.
        cols: Scale code to column label.

    Returns:
        Decipher condition text.
    """
    if question.type in {"grid", "matrix"}:
        row = rows.get(str(expr.row), f"r{expr.row}")
        if expr.op == "answered":
            return f"{name}.{row}.any"
        if expr.op == "not_answered":
            return f"not {name}.{row}.any"
        wanted = _as_list(expr.value)
        if expr.op in _COMPARE:
            limit = (
                float(wanted[0])
                if wanted and str(wanted[0]).lstrip("-").replace(".", "", 1).isdigit()
                else 0
            )
            ops = {"gt": float.__gt__, "gte": float.__ge__, "lt": float.__lt__, "lte": float.__le__}
            wanted = [
                code
                for code in cols
                if code.lstrip("-").replace(".", "", 1).isdigit()
                and ops[expr.op](float(code), limit)
            ]
        cells = [f"{name}.{row}.{cols[str(code)]}" for code in wanted if str(code) in cols]
        clause = "(" + " or ".join(cells) + ")" if len(cells) > 1 else (cells[0] if cells else "0")
        return f"not {clause}" if expr.op in {"ne", "not_in"} else clause
    row = rows.get(str(expr.row), f"r{expr.row}")
    if question.type in {"numeric", "allocation"}:
        if expr.op == "answered":
            return f"{name}.{row}.val is not None"
        if expr.op == "not_answered":
            return f"{name}.{row}.val is None"
        if expr.op in {"in", "not_in"}:
            values = ", ".join(_literal(value) for value in _as_list(expr.value))
            clause = f"{name}.{row}.ival in [{values}]"
            return clause if expr.op == "in" else f"not ({clause})"
        op = _COMPARE.get(expr.op) or {"eq": "==", "ne": "!="}[expr.op]
        return f"{name}.{row}.ival {op} {_literal(expr.value)}"
    selected = f"{name}.{row}"
    negative = expr.op in {"ne", "not_in", "not_answered"} or expr.value in {0, False, "0"}
    return f"not {selected}" if negative else selected


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
        item_rows = list(rows.values()) or [
            f"r{index}" for index in range(1, len(question.matrix_items) + 1)
        ]
        parts = [f"{name}.{row}.{column}" for row in item_rows] or [f"{name}.{column}"]
        return parts[0] if len(parts) == 1 else "(" + " or ".join(parts) + ")"
    if key in rows:
        if rows[key].startswith("ch"):
            return f"({name}.val == {name}.{rows[key]}.index)"  # a dropdown choice
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
