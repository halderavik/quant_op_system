"""Test the survey XML's logic with simulated respondents, checked against the questionnaire.

Each simulated respondent takes the survey XML the way Decipher would run it: its
``cond`` attributes decide what is shown and its ``term`` elements screen people
out. The same answers are then read against the questionnaire's own logic (bases,
option and rule terminates, derived variables), evaluated here independently of
the XML compiler. Where the two disagree for a respondent, the first disagreement
is reported with the answers that caused it, so one wrong base does not show up as
dozens of follow-on differences.

Derived variables are worked out from their definitions and given to both sides;
the XML's own exec code is not run. Answers are drawn at random, so rare paths may
not be reached by every run.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.engines.decipher import range_midpoint
from app.engines.decipher_preview import _apply
from app.engines.decipher_similarity import _parse, _questions
from app.engines.flow import describe_comparison
from app.engines.synthetic_draw import draw
from app.engines.synthetic_sim import _shown
from app.engines.synthetic_survey import Spec, parse_survey
from app.schemas.expression import BoolExpr, Comparison, Expr
from app.schemas.questionnaire import DerivedVariable, Question, Questionnaire

RESPONDENTS = 400
_EXAMPLES = 3
_BASE_NOTE = re.compile(
    r"\b(?:ask|show|display)\s+(?:only\s+)?(?:if|to|when)\b|^\s*base\s*:|\[\s*ask if|\bonly show\b",
    re.I,
)
_ASK_ALL = re.compile(r"\bask all\b|total respondents|all respondents", re.I)
_ANSWERED = {
    "single_select",
    "multi_select",
    "rating",
    "numeric",
    "text",
    "matrix",
    "rank",
    "allocation",
    "date",
    "grid",
    "screener",
}


@dataclass
class _Run:
    """One simulated respondent."""

    answers: dict[str, Any] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)  # question ids, in the order asked
    term: str | None = None  # XML terminate label that ended the interview


def run_logic_qa(
    document: Questionnaire,
    xml: str,
    items: list[dict[str, Any]],
    respondents: int = RESPONDENTS,
    seed: int = 11,
) -> dict[str, Any]:
    """Run simulated respondents through the XML and check them against the questionnaire.

    Args:
        document: Planned questionnaire the XML was built from.
        xml: Survey XML (as stored, including any corrections Decipher asked for).
        items: Coverage items stored with the XML; they map question ids to labels and codes.
        respondents: How many respondents to simulate.
        seed: Random seed, so a run can be repeated.

    Returns:
        Agreement, per-question counts, issues with example answers, and warnings.
    """
    specs = parse_survey(xml, items, [q.model_dump(mode="json") for q in document.questions])
    for spec in specs:
        # Reason: synthetic data makes screen-out answers rare; a logic test wants
        # every path, so they are drawn as often as any other answer.
        spec.ending = set()
    label_of = {str(item.get("question_id")): str(item.get("label")) for item in items}
    id_of = {label: qid for qid, label in label_of.items()}
    punches = {
        str(item.get("label")): {
            str(p.get("row_label") or p.get("label")): str(p.get("code"))
            for p in item.get("punches") or []
        }
        for item in items
    }
    hidden_labels = {q.label for q in _questions(_parse(xml)).values() if q.hidden}
    questions = {question.id: question for question in document.questions}
    order = {question.id: index for index, question in enumerate(document.questions)}
    index_of = {spec.label: index for index, spec in enumerate(specs) if spec.label}
    rng = random.Random(seed)
    warned: set[str] = set()
    skipped = {
        id_of.get(spec.label, spec.label) for spec in specs if spec.kind == "multi" and spec.cols
    }
    for qid in sorted(skipped):
        warned.add(
            f"{qid} is a select-all grid; its answers are not simulated, so logic that uses it "
            "is not checked."
        )

    issues: dict[tuple[str, str], dict[str, Any]] = {}
    expected_shown: Counter[str] = Counter()
    xml_shown: Counter[str] = Counter()
    expected_terms = xml_terms = agreed = 0
    for _ in range(respondents):
        run = _walk_xml(
            document, specs, index_of, id_of, label_of, punches, hidden_labels, rng, warned
        )
        for qid in run.asked:
            xml_shown[qid] += 1
        found, seen, ends = _check(document, questions, order, label_of, run, skipped)
        for qid in seen:
            expected_shown[qid] += 1
        expected_terms += ends
        xml_terms += run.term is not None
        if found is None:
            agreed += 1
            continue
        key = (found["question_id"], found["kind"])
        entry = issues.setdefault(key, {**found, "count": 0, "examples": []})
        entry["count"] += 1
        if len(entry["examples"]) < _EXAMPLES:
            entry["examples"].append(found["example"])
        entry.pop("example", None)

    rows = []
    for question in document.questions:
        if question.id not in label_of or question.type not in _ANSWERED:
            continue
        rows.append(
            {
                "question_id": question.id,
                "label": label_of[question.id],
                "expected": expected_shown[question.id],
                "xml": xml_shown[question.id],
            }
        )
    never = [row["question_id"] for row in rows if row["xml"] == 0]
    unprogrammed = [
        question.id
        for question in document.questions
        if question.display_if is None
        and not (question.programming and question.programming.row_condition)
        and any(
            _BASE_NOTE.search(note) and not _ASK_ALL.search(note)
            for note in question.programmer_notes
        )
    ]
    listed = sorted(
        issues.values(), key=lambda item: (-item["count"], order.get(item["question_id"], 0))
    )
    for item in listed:
        item["message"] = _message(item, respondents, questions)
    return {
        "respondents": respondents,
        "agreement": round(100 * agreed / respondents, 1) if respondents else None,
        "terminated": {"expected": expected_terms, "xml": xml_terms},
        "issues": listed,
        "questions": rows,
        "never_shown": never,
        "written_base_without_logic": unprogrammed,
        "warnings": sorted(warned),
    }


# ------------------------------------------------------------------ the XML side


def _walk_xml(
    document: Questionnaire,
    specs: list[Spec],
    index_of: dict[str, int],
    id_of: dict[str, str],
    label_of: dict[str, str],
    punches: dict[str, dict[str, str]],
    hidden_labels: set[str],
    rng: random.Random,
    warned: set[str],
) -> _Run:
    """Take the survey as Decipher would: conditions, gotos, and terminates from the XML."""
    run = _Run()
    facts: dict[str, Any] = {}
    jumps: set[int] = set()
    index = 0
    while index < len(specs):
        spec = specs[index]
        _inject_derived(document, run.answers, facts, label_of, punches, rng)
        shown = _shown(spec, facts, warned)
        if spec.kind == "goto" and shown and index not in jumps and spec.target in index_of:
            jumps.add(index)
            index = index_of[spec.target]
            continue
        if spec.kind == "term" and shown:
            run.term = spec.label or "a terminate"
            return run
        if spec.answered and shown and spec.label not in hidden_labels:
            drawn = draw(spec, None, None, rng)
            _apply(facts, spec.label, drawn.answer)
            qid = id_of.get(spec.label, spec.label)
            run.asked.append(qid)
            run.answers[qid] = _value(spec, drawn.answer)
        index += 1
    return run


def _value(spec: Spec, answer: Any) -> Any:
    """The answer in questionnaire terms: codes, numbers, or grid cells by row position."""
    rows = {choice.label: choice.code for choice in spec.rows}
    if spec.kind == "single":
        return _code(rows.get(answer.rows[0])) if answer.rows else None
    if spec.kind == "multi":
        return [_code(rows.get(row)) for row in answer.rows if row in rows]
    if spec.kind == "number":
        return _number(answer.value)
    if spec.kind == "allocation":
        return {rows.get(row, row): _number(raw) for row, raw in answer.row_values.items() if raw}
    if spec.kind == "grid":
        position = {choice.label: str(index) for index, choice in enumerate(spec.rows, start=1)}
        cols = {choice.label: choice.code for choice in spec.cols}
        return {
            position.get(row, row): _code(cols.get(col)) for row, col in answer.cells.items() if col
        }
    return (
        "answered" if (answer.value or answer.rows or answer.cells or answer.row_values) else None
    )


def _inject_derived(
    document: Questionnaire,
    answers: dict[str, Any],
    facts: dict[str, Any],
    label_of: dict[str, str],
    punches: dict[str, dict[str, str]],
    rng: random.Random,
) -> None:
    """Work out derived variables from the answers so far and give them to both sides."""
    labels = {
        variable.id: label_of.get(variable.id, variable.id)
        for variable in document.derived_variables
    }
    for variable in document.derived_variables:
        value = derived_value(variable, answers, document, rng)
        if value is None:
            continue
        answers[variable.id] = value
        label = labels[variable.id]
        row_of = {code: row for row, code in punches.get(label, {}).items()}
        if variable.compute is not None:
            facts[f"{label}.val"] = value
            facts[f"{label}.ival"] = value
            continue
        codes = value if isinstance(value, list) else [value]
        for code in codes:
            facts[f"{label}.{row_of.get(str(code), f'r{code}')}"] = True
        if codes:
            facts[f"{label}.any"] = True
            facts[f"{label}.count"] = len(codes)


def derived_value(
    variable: DerivedVariable,
    answers: dict[str, Any],
    document: Questionnaire,
    rng: random.Random | None = None,
) -> Any:
    """A derived variable's value for one respondent, from its programmed definition.

    Args:
        variable: Derived variable.
        answers: Answers so far, by question id.
        document: Questionnaire, for option labels (midpoints) and question types.
        rng: Picks a value for a variable that is assigned rather than computed.

    Returns:
        A code, a list of codes, a number, or None when it cannot be worked out yet.
    """
    if variable.id in answers and variable.values and all(v.when is None for v in variable.values):
        return answers[variable.id]  # an assigned value stays the same for the respondent
    questions = {question.id: question for question in document.questions}
    if variable.compute is not None:
        compute = variable.compute
        wanted = {str(row) for row in compute.rows}
        total = 0.0
        for source in compute.sources:
            current = answers.get(source)
            if compute.kind == "midpoint":
                question = questions.get(source)
                option = (
                    next((o for o in question.options if str(o.code) == str(current)), None)
                    if question
                    else None
                )
                return range_midpoint(option.label) if option else None
            if isinstance(current, list):
                picked = [c for c in current if not wanted or str(c) in wanted]
                total += len(picked) if compute.kind == "count" else 0
            elif isinstance(current, dict):
                cells = [v for k, v in current.items() if not wanted or str(k) in wanted]
                if compute.kind == "count":
                    total += sum(1 for v in cells if (_number(v) or 0) > 0)
                else:
                    total += sum(_number(v) or 0 for v in cells)
            elif current is not None:
                if compute.kind == "count":
                    total += 1 if not wanted or str(current) in wanted else 0
                else:
                    total += _number(current) or 0
        return total
    if not variable.values:
        return None
    if all(value.when is None for value in variable.values):
        if rng is None:
            return None
        return rng.choice(variable.values).code
    chosen = [
        value.code
        for value in variable.values
        if value.when is not None and holds(value.when, answers, questions)
    ]
    if variable.multiple:
        return chosen
    return chosen[0] if chosen else None


# ------------------------------------------------------------ the questionnaire side


def _check(
    document: Questionnaire,
    questions: dict[str, Question],
    order: dict[str, int],
    label_of: dict[str, str],
    run: _Run,
    skipped: set[str],
) -> tuple[dict[str, Any] | None, list[str], bool]:
    """Walk the questionnaire with the respondent's answers and find the first disagreement.

    Args:
        document: Questionnaire.
        questions: Questions by id.
        order: Position of each question.
        label_of: Decipher label of each question id.
        run: The respondent's walk through the XML.
        skipped: Question ids whose answers are not simulated; logic using them is not checked.

    Returns:
        The first disagreement or None, the questions the questionnaire shows, and
        whether the questionnaire screens this respondent out.
    """
    asked = set(run.asked)
    known: dict[str, Any] = {}
    seen: list[str] = []
    pending: str | None = None
    after = document.terminate_after
    for question in document.questions:
        if question.id not in label_of or question.type not in _ANSWERED:
            continue
        for variable in document.derived_variables:
            if variable.id in run.answers:
                known[variable.id] = run.answers[variable.id]
        spec = question.programming
        actual = question.id in asked
        if _refs(question.display_if) & skipped:
            expected = actual  # its base uses an answer that is not simulated
        else:
            expected = not (spec and spec.hidden) and holds(question.display_if, known, questions)
        if expected != actual:
            later = [qid for qid in run.asked if order.get(qid, -1) > order[question.id]]
            if expected and run.term is not None and not later:
                # Reason: the XML screened this respondent out before this question.
                return _terminated_early(questions, run, known), seen, False
            kind = "xml_hides" if expected else "xml_shows"
            return _found(question, kind, run, known), seen, False
        if not expected:
            continue
        seen.append(question.id)
        known[question.id] = run.answers.get(question.id)
        if question.id not in skipped:
            fires, immediately = _screens_out(question, known, questions)
            fires = fires or _derived_terminate(document, question.id, run.answers)
            deferred = (
                fires
                and after is not None
                and not immediately
                and order[question.id] < order.get(after, -1)
            )
            if fires and not deferred:
                return _ending(question, order, run, known), seen, True
            if deferred:
                pending = pending or question.id
        if pending and question.id == after:
            return _ending(questions[pending], order, run, known, at=question), seen, True
    if run.term is not None:
        return _terminated_early(questions, run, known), seen, False
    return None, seen, False


def _terminated_early(
    questions: dict[str, Question], run: _Run, known: dict[str, Any]
) -> dict[str, Any] | None:
    """The XML screened out a respondent the questionnaire keeps; name where."""
    last = run.asked[-1] if run.asked else ""
    where = questions.get(last)
    return _found(where, "xml_terminates", run, known) if where is not None else None


def _derived_terminate(document: Questionnaire, after: str, answers: dict[str, Any]) -> bool:
    """A derived group computed after this question is one the file marks TERMINATE."""
    for variable in document.derived_variables:
        if variable.after != after or variable.id not in answers:
            continue
        value = answers[variable.id]
        codes = {str(code) for code in (value if isinstance(value, list) else [value])}
        if any(item.terminate and str(item.code) in codes for item in variable.values):
            return True
    return False


def _screens_out(
    question: Question, known: dict[str, Any], questions: dict[str, Question]
) -> tuple[bool, bool]:
    """Whether this answer screens the respondent out, and whether immediately."""
    spec = question.programming
    answer = known.get(question.id)
    chosen = {
        str(code) for code in (answer if isinstance(answer, list) else [answer]) if code is not None
    }
    if any(option.terminate and str(option.code) in chosen for option in question.options):
        return True, bool(spec and spec.terminate_immediately)
    if spec is None:
        return False, False
    rules = [(spec.terminate_when, spec.terminate_immediately)] if spec.terminate_when else []
    rules += [(rule.when, rule.immediately) for rule in spec.terminate_rules]
    fired = [immediately for when, immediately in rules if holds(when, known, questions)]
    return bool(fired), any(fired)


def _ending(
    question: Question,
    order: dict[str, int],
    run: _Run,
    known: dict[str, Any],
    at: Question | None = None,
) -> dict[str, Any] | None:
    """The questionnaire screens this respondent out; check the XML did too, in time."""
    stop = order[(at or question).id]
    later = [qid for qid in run.asked if order.get(qid, -1) > stop]
    if run.term is None or later:
        return _found(question, "xml_continues", run, known)
    return None


def _found(question: Question, kind: str, run: _Run, known: dict[str, Any]) -> dict[str, Any]:
    refs = (
        sorted(_refs(question.display_if)) if kind in {"xml_hides", "xml_shows"} else [question.id]
    )
    example = {ref: _show(run.answers.get(ref)) for ref in refs if ref in run.answers}
    if kind == "xml_terminates":
        example["XML terminate"] = run.term or ""
    return {"question_id": question.id, "kind": kind, "example": example}


def _message(item: dict[str, Any], total: int, questions: dict[str, Question]) -> str:
    question = questions.get(item["question_id"])
    count = item["count"]
    people = f"{count} of {total} respondents"
    base = (
        _describe(question.display_if)
        if question is not None and question.display_if
        else "ask all"
    )
    if item["kind"] == "xml_hides":
        return f"The XML skips {item['question_id']} for {people} the questionnaire shows it to (base: {base})."
    if item["kind"] == "xml_shows":
        return (
            f"The XML shows {item['question_id']} to {people} the base leaves out (base: {base})."
        )
    if item["kind"] == "xml_continues":
        return f"{people} should be screened out at {item['question_id']}, but the XML lets them continue."
    return f"The XML screens out {people} right after {item['question_id']}, but the questionnaire keeps them."


# ------------------------------------------------------------------ evaluation


def holds(expr: Expr | None, answers: dict[str, Any], questions: dict[str, Question]) -> bool:
    """Evaluate questionnaire logic against answers, the way the questionnaire means it.

    Single answers are codes, select-all answers are lists of codes, numeric lists and
    grids are dicts (grids keyed by row position). An unanswered question fails every
    test except "not answered", so "S3 is not 2" needs S3 to have been answered.

    Args:
        expr: Base, terminate, or derived-value condition. None is always true.
        answers: Answers by question or derived variable id.
        questions: Questions by id.

    Returns:
        Whether the condition holds.
    """
    if expr is None:
        return True
    if isinstance(expr, BoolExpr):
        results = [holds(arg, answers, questions) for arg in expr.args]
        if expr.op == "and":
            return all(results)
        if expr.op == "or":
            return any(results)
        return not results[0] if results else True
    return _compare(expr, answers, questions)


def _compare(expr: Comparison, answers: dict[str, Any], questions: dict[str, Question]) -> bool:
    current = answers.get(expr.ref)
    present = _present(current)
    if expr.op == "answered":
        return present
    if expr.op == "not_answered":
        return not present
    if expr.aggregate == "count":
        count = len(current) if isinstance(current, list | dict) else (1 if present else 0)
        return present and _numeric(count, expr.op, expr.value)
    if expr.value_ref:
        left = _cell_number(current, expr.row)
        right = _cell_number(answers.get(expr.value_ref), expr.value_row)
        return left is not None and right is not None and _numeric(left, expr.op, right)
    if expr.row is not None:
        key = str(expr.row)
        if isinstance(current, dict):
            if key not in current or not _present(current[key]):
                return False
            return _scalar(current[key], expr.op, expr.value)
        if isinstance(current, list):
            selected = key in {str(code) for code in current}
            truthy = expr.value in (None, 1, True, "1", key) or str(expr.value) == key
            wanted = selected if truthy else not selected
            return (
                wanted
                if expr.op in {"eq", "in"}
                else (not wanted if expr.op in {"ne", "not_in"} else selected)
            )
        return False
    if not present:
        return False
    if isinstance(current, list):
        codes = {str(code) for code in current}
        values = {str(item) for item in _as_list(expr.value)}
        if expr.op in {"eq", "in"}:
            return bool(codes & values)
        if expr.op in {"ne", "not_in"}:
            return not codes & values
        return _numeric(len(codes), expr.op, expr.value)
    if isinstance(current, dict):
        cells = [value for value in current.values() if _present(value)]
        return (
            any(_scalar(value, expr.op, expr.value) for value in cells)
            if expr.op in {"eq", "in"}
            else all(_scalar(value, expr.op, expr.value) for value in cells)
        )
    return _scalar(current, expr.op, expr.value)


def _scalar(current: Any, op: str, value: Any) -> bool:
    if op in {"eq", "ne", "in", "not_in"}:
        values = {str(item) for item in _as_list(value)}
        same = str(current) in values or (
            _number(current) is not None and any(_number(v) == _number(current) for v in values)
        )
        return same if op in {"eq", "in"} else not same
    number = _number(current)
    return number is not None and _numeric(number, op, value)


def _numeric(left: float, op: str, value: Any) -> bool:
    right = _number(value)
    if right is None:
        return False
    return {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
        "eq": left == right,
        "ne": left != right,
    }.get(op, False)


def _cell_number(current: Any, row: Any) -> float | None:
    if isinstance(current, dict):
        return _number(current.get(str(row))) if row is not None else None
    return _number(current)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list | dict):
        return bool(value)
    return str(value) != ""


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _code(raw: str | None) -> Any:
    if raw is None:
        return None
    return int(raw) if raw.lstrip("-").isdigit() else raw


def _refs(expr: Expr | None) -> set[str]:
    if expr is None:
        return set()
    if isinstance(expr, Comparison):
        return {expr.ref} | ({expr.value_ref} if expr.value_ref else set())
    return set().union(*(_refs(arg) for arg in expr.args)) if expr.args else set()


def _describe(expr: Expr | None) -> str:
    if expr is None:
        return "ask all"
    if isinstance(expr, Comparison):
        return describe_comparison(expr)
    parts = [_describe(arg) for arg in expr.args]
    if expr.op == "not":
        return f"not ({parts[0]})" if parts else "not"
    return f" {expr.op} ".join(
        f"({part})" if " and " in part or " or " in part else part for part in parts
    )


def _show(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "(none)"
    if isinstance(value, dict):
        return "; ".join(f"{key}={item}" for key, item in value.items()) or "(none)"
    return "(not answered)" if value is None else str(value)


__all__ = ["RESPONDENTS", "derived_value", "holds", "run_logic_qa"]
