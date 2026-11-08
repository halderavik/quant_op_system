"""Questionnaire structure and routing-graph checks."""

import re
from typing import Any

from app.engines.expression import evaluate
from app.schemas.expression import BoolExpr, Comparison, Expr
from app.schemas.questionnaire import FlowIssue, FlowReport, Questionnaire, RespondentPreview

_OP_WORDS = {
    "eq": "equals",
    "ne": "does not equal",
    "gt": "is greater than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "in": "is one of",
    "not_in": "is not one of",
}
_PUNCH = re.compile(r"[rc]\d+")
_CODE_OPS = {"eq", "ne", "in", "not_in"}
_RANGE_OPS = {"gt", "gte", "lt", "lte"}
_RANGE_TYPES = {"numeric", "rating", "allocation", "date"}


def validate_questionnaire(document: Questionnaire) -> FlowReport:
    """Check ids, references, reachability, and cycles.

    Args:
        document: Questionnaire document.

    Returns:
        Flow report. Errors fail the report.
    """
    issues: list[FlowIssue] = []
    ids = [question.id for question in document.questions]
    if not ids:
        issues.append(
            FlowIssue(
                severity="error",
                code="empty_instrument",
                message="A questionnaire needs at least one question.",
            )
        )
    if len(ids) != len(set(ids)):
        issues.append(
            FlowIssue(severity="error", code="duplicate_id", message="Question ids must be unique")
        )
    known = set(ids)
    questions = {question.id: question for question in document.questions}
    index = {question_id: position for position, question_id in enumerate(ids)}
    graph: dict[str, list[str]] = {question_id: [] for question_id in ids}
    for question in document.questions:
        for option in question.options:
            if (
                question.exclusive_codes
                and option.code in question.exclusive_codes
                and not option.exclusive
            ):
                issues.append(
                    FlowIssue(
                        severity="warning",
                        code="exclusive_flag",
                        message=f"{question.id} lists exclusive code {option.code} without the exclusive flag",
                        question_id=question.id,
                    )
                )
        _check_expr(
            question.display_if,
            known,
            index,
            question.id,
            issues,
            allow_forward=False,
            clause="is shown only when",
            questions=questions,
        )
        for rule in question.routing:
            _check_expr(
                rule.when,
                known,
                index,
                question.id,
                issues,
                allow_forward=False,
                clause=f"skips to {rule.go_to} when",
                questions=questions,
            )
            if rule.go_to in {"END", "TERMINATE"}:
                continue
            if rule.go_to not in known:
                issues.append(
                    FlowIssue(
                        severity="error",
                        code="bad_route",
                        message=f"{question.id} routes to unknown question {rule.go_to}",
                        question_id=question.id,
                    )
                )
            else:
                graph[question.id].append(rule.go_to)
        position = index[question.id]
        terminates = any(
            rule.go_to == "TERMINATE" and rule.when is None for rule in question.routing
        )
        if not terminates and position + 1 < len(ids):
            graph[question.id].append(ids[position + 1])
    cycles = _cycles(graph)
    for question_id in cycles:
        issues.append(
            FlowIssue(
                severity="error",
                code="cycle",
                message=f"{question_id} is part of a routing loop",
                question_id=question_id,
            )
        )
    reachable = _reachable(ids[0], graph) if ids else []
    unreachable = [question_id for question_id in ids if question_id not in reachable]
    for question_id in unreachable:
        issues.append(
            FlowIssue(
                severity="warning",
                code="unreachable",
                message=f"{question_id} is not reachable from the first question",
                question_id=question_id,
            )
        )
    covered = {qid for objective in document.objectives for qid in objective.question_ids}
    for question_id in covered - known:
        issues.append(
            FlowIssue(
                severity="error",
                code="objective_ref",
                message=f"Objective references unknown question {question_id}",
            )
        )
    for module in document.modules:
        for question_id in module.question_ids:
            if question_id not in known:
                issues.append(
                    FlowIssue(
                        severity="error",
                        code="module_ref",
                        message=f"Module {module.id} references unknown question {question_id}",
                    )
                )
    status = (
        "failed"
        if any(issue.severity == "error" for issue in issues)
        else ("passed_with_warnings" if issues else "passed")
    )
    return FlowReport(status=status, issues=issues, reachable=reachable, unreachable=unreachable)


def preview_path(document: Questionnaire, answers: dict[str, Any]) -> RespondentPreview:
    """Walk one respondent path using the supplied answers.

    Args:
        document: Questionnaire document.
        answers: Map of question id to answer code.

    Returns:
        Ordered question ids and whether the path terminated.
    """
    questions = {question.id: question for question in document.questions}
    order = [question.id for question in document.questions]
    if not order:
        return RespondentPreview(path=[], answers=answers)
    path: list[str] = []
    seen: set[str] = set()
    current: str | None = order[0]
    terminated = False
    while current and current not in seen and current in questions:
        seen.add(current)
        question = questions[current]
        shown = evaluate(question.display_if, answers, set(questions))
        if shown:
            path.append(current)
        nxt = order[order.index(current) + 1] if order.index(current) + 1 < len(order) else None
        for rule in question.routing:
            if evaluate(rule.when, answers, set(questions)):
                if rule.go_to == "TERMINATE":
                    terminated = True
                    nxt = None
                elif rule.go_to == "END":
                    nxt = None
                else:
                    nxt = rule.go_to
                break
        current = nxt
    return RespondentPreview(path=path, terminated=terminated, answers=answers)


def describe_comparison(expr: Comparison) -> str:
    """Describe one comparison in plain language.

    Args:
        expr: Comparison node.

    Returns:
        Text such as ``Q3 equals 1`` or ``Q3 is answered``.
    """
    if expr.op == "answered":
        return f"{expr.ref} is answered"
    if expr.op == "not_answered":
        return f"{expr.ref} is not answered"
    word = _OP_WORDS.get(expr.op, expr.op)
    value = expr.value
    if isinstance(value, list):
        shown = ", ".join(str(item) for item in value)
    else:
        shown = str(value)
    return f"{expr.ref} {word} {shown}"


def unknown_ref_message(owner: str, clause: str, expr: Comparison, known: set[str]) -> str:
    """Explain a condition that names a question the survey does not have.

    Args:
        owner: Question that owns the condition.
        clause: How the condition is used, such as ``is shown only when``.
        expr: Comparison that names the missing question.
        known: Question ids on the survey.

    Returns:
        One sentence naming the owner, the comparison, and why the reference is unusable.
    """
    message = (
        f"{owner} {clause} {describe_comparison(expr)}, "
        f"but {expr.ref} is not a question on this survey."
    )
    hint = _ref_hint(expr.ref, known)
    return f"{message} {hint}" if hint else message


def _ref_hint(ref: str, known: set[str]) -> str:
    """Explain a punch label or hidden variable used where a question id belongs.

    Args:
        ref: Reference that is not a question id.
        known: Question ids on the survey.

    Returns:
        Extra guidance, or an empty string when the reference has no recognizable shape.
    """
    for question_id in sorted(known, key=len, reverse=True):
        if not ref.startswith(question_id):
            continue
        suffix = ref[len(question_id) :]
        if _PUNCH.fullmatch(suffix):
            kind = "row" if suffix.startswith("r") else "column"
            return (
                f"{ref} looks like a {kind} punch on {question_id}, not a question id. "
                f"Name {question_id} in the condition and put the code in the value."
            )
    if ref.startswith("HV_"):
        return (
            f"{ref} looks like a hidden variable. "
            "Hidden variables belong in programmer notes, not in a show-if or a skip."
        )
    return ""


def _check_expr(
    expr: Expr | None,
    known: set[str],
    index: dict[str, int],
    owner: str,
    issues: list[FlowIssue],
    *,
    allow_forward: bool,
    clause: str,
    questions: dict[str, Any],
) -> None:
    """Validate references inside a routing expression.

    Args:
        expr: Expression or None.
        known: Known question ids.
        index: Question position by id.
        owner: Question that owns the expression.
        issues: Accumulator.
        allow_forward: When false, references must be earlier questions.
        clause: How the condition is used, such as ``is shown only when``.
        questions: Questions by id, used to check option codes.
    """
    if expr is None:
        return
    if isinstance(expr, Comparison):
        if expr.ref not in known:
            issues.append(
                FlowIssue(
                    severity="error",
                    code="bad_ref",
                    message=unknown_ref_message(owner, clause, expr, known),
                    question_id=owner,
                )
            )
        elif not allow_forward and index[expr.ref] >= index[owner]:
            issues.append(
                FlowIssue(
                    severity="error",
                    code="forward_ref",
                    message=f"{owner} references {expr.ref}, which is not an earlier question",
                    question_id=owner,
                )
            )
        else:
            _check_codes(expr, questions[expr.ref], owner, clause, issues)
        return
    if isinstance(expr, BoolExpr):
        for child in expr.args:
            _check_expr(
                child,
                known,
                index,
                owner,
                issues,
                allow_forward=allow_forward,
                clause=clause,
                questions=questions,
            )


def _check_codes(
    expr: Comparison,
    question: Any,
    owner: str,
    clause: str,
    issues: list[FlowIssue],
) -> None:
    """Reject a comparison that the referenced question cannot answer.

    Args:
        expr: Comparison whose question id is already known.
        question: Referenced question.
        owner: Question that owns the condition.
        clause: How the condition is used.
        issues: Accumulator.
    """
    if expr.op in {"answered", "not_answered"}:
        return
    if expr.op in _RANGE_OPS and question.type not in _RANGE_TYPES:
        issues.append(
            FlowIssue(
                severity="error",
                code="bad_compare",
                message=(
                    f"{owner} {clause} {describe_comparison(expr)}, "
                    f"but {question.id} is a {question.type}. "
                    "Use a selected code or answered, not a numeric comparison."
                ),
                question_id=owner,
            )
        )
        return
    if not question.options or expr.op not in _CODE_OPS | _RANGE_OPS:
        return
    codes = {str(option.code) for option in question.options}
    values = expr.value if isinstance(expr.value, list) else [expr.value]
    missing = [value for value in values if str(value) not in codes]
    if not missing:
        return
    listed = ", ".join(str(option.code) for option in question.options)
    absent = ", ".join(str(value) for value in missing)
    noun = "code" if len(missing) == 1 else "codes"
    issues.append(
        FlowIssue(
            severity="error",
            code="bad_code",
            message=(
                f"{owner} {clause} {describe_comparison(expr)}, "
                f"but {question.id} has no {noun} {absent}. Use one of: {listed}."
            ),
            question_id=owner,
        )
    )


def _cycles(graph: dict[str, list[str]]) -> list[str]:
    """Return nodes that participate in a directed cycle.

    Args:
        graph: Adjacency list.

    Returns:
        Question ids on a cycle.
    """
    color = {node: 0 for node in graph}
    found: list[str] = []

    def visit(node: str) -> None:
        color[node] = 1
        for nxt in graph.get(node, []):
            if color.get(nxt) == 1:
                found.append(node)
            elif color.get(nxt) == 0:
                visit(nxt)
        color[node] = 2

    for node in graph:
        if color[node] == 0:
            visit(node)
    return sorted(set(found))


def _reachable(start: str, graph: dict[str, list[str]]) -> list[str]:
    """Return nodes reachable from ``start``.

    Args:
        start: First question id.
        graph: Adjacency list.

    Returns:
        Reachable ids in visit order.
    """
    seen: list[str] = []
    stack = [start]
    while stack:
        node = stack.pop(0)
        if node in seen:
            continue
        seen.append(node)
        stack.extend(graph.get(node, []))
    return seen
