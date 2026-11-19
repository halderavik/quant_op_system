"""Shared Decipher element helpers."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from app.engines.decipher_expr import combined_condition, safe_label, translate
from app.schemas.decipher import CoverageItem, Punch
from app.schemas.questionnaire import Option, ProgrammingSpec, Question

# Reason: Decipher's ss:, html:, and builder: attributes must be declared for the file
# to be well-formed; registering keeps the same prefixes whenever the tree is written.
DECIPHER_NAMESPACES = {
    "ss": "http://decipherinc.com/ss",
    "html": "http://decipherinc.com/html",
    "builder": "http://decipherinc.com/builder",
}
for _prefix, _uri in DECIPHER_NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)


def qualified(name: str) -> str:
    """Turn ``ss:listDisplay`` into ElementTree's ``{uri}listDisplay``."""
    prefix, _, local = name.partition(":")
    if local and prefix in DECIPHER_NAMESPACES:
        return f"{{{DECIPHER_NAMESPACES[prefix]}}}{local}"
    return name


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
    # Screen-out flags wait until this question, then end the interview together.
    terminate_after: str | None = None
    order: dict[str, int] = field(default_factory=dict)
    deferred_terms: list[tuple[str, str, str]] = field(default_factory=list)
    needs_group_rows: bool = False


def spec_of(question: Question) -> ProgrammingSpec:
    """The question's programming spec, or the defaults."""
    return question.programming or ProgrammingSpec()


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
    clean = {
        qualified(key): str(value)
        for key, value in attrs.items()
        if value is not None and value != ""
    }
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
    spec = spec_of(question)
    shuffle = []
    shuffles_rows, shuffle_by, problem = row_order(question, build)
    if problem:
        _warn(build, problem)
    if shuffles_rows:
        shuffle.append("rows")
    if spec.randomize_columns:
        shuffle.append("cols")
    row_cond = None
    if spec.row_condition and spec.row_condition.source in build.labels:
        source = build.labels[spec.row_condition.source]
        column = spec.row_condition.column
        column_label = build.cols.get(spec.row_condition.source, {}).get(str(column))
        if column is not None and column_label:
            source = f"{source}[row].{column_label}"
            row_cond = source if spec.row_condition.mode != "not_selected" else f"not {source}"
        row_cond = (
            row_cond
            or {
                "selected": f"{source}[row]",
                "not_selected": f"not {source}[row]",
                "positive": f"{source}[row].ival gt 0",
            }[spec.row_condition.mode]
        )
    _autofill(parent, tag, question, build)
    node = add_element(
        parent,
        tag,
        label=build.labels[question.id],
        optional="0" if question.required else "1",
        cond="0" if spec.hidden else _condition(question, build),
        shuffle=",".join(shuffle) or None,
        shuffleBy=shuffle_by,
        sortRows="asc,survey" if spec.sort_alphabetically else None,
        rowCond=row_cond,
        **attrs,
    )
    _titles(node, question, build)
    _validations(node, question, build)
    for note in spec.unresolved:
        node.append(ET.Comment(f" PROGRAMMER TODO: {_comment_body(note)} "))
        _warn(build, f"{question.id}: {note}")
    if spec.keep_together:
        lines = []
        for group in spec.keep_together:
            labels = [build.rows.get(question.id, {}).get(str(code)) for code in group]
            labels = [label for label in labels if label]
            if len(labels) > 1:
                lines.append(f"group_rows({build.labels[question.id]}, {labels!r})")
        if lines:
            build.needs_group_rows = True
            add_element(node, "exec", "\n".join(lines))
    return node


def _titles(node: ET.Element, question: Question, build: "SurveyBuild | None" = None) -> None:
    """Add the respondent title and instruction, with piped answers filled in.

    Args:
        node: Question element.
        question: Question.
        build: Shared build state, for piping.
    """
    title = add_element(node, "title", _piped(question.text, question, build))
    for image in spec_of(question).images:
        name = image_file(image)
        ET.SubElement(title, "br")
        ET.SubElement(title, "img", {"src": f"[rel {name}]", "width": "auto"})
        if build is not None:
            _warn(build, f"{question.id}: upload {name} to the survey's static files ({image})")
    if question.instruction:
        add_element(node, "comment", _piped(question.instruction, question, build))


_IMAGE_FILE = re.compile(r"[\w.-]+\.(?:png|jpe?g|gif|webp|svg|mp4)$", re.I)


def image_file(image: str) -> str:
    """The file name to reference: the name the questionnaire gives, or one made from its description."""
    image = image.strip()
    if _IMAGE_FILE.fullmatch(image):
        return image
    stem = re.sub(r"[^A-Za-z0-9]+", "_", image).strip("_")[:40] or "image"
    return f"{stem}.png"


def _piped(text: str, question: Question, build: "SurveyBuild | None") -> str:
    """Replace each pipe placeholder with the Decipher expression for that answer."""
    if build is None:
        return text
    for pipe in spec_of(question).pipes:
        if pipe.placeholder and pipe.placeholder in text and pipe.source in build.labels:
            text = text.replace(pipe.placeholder, _pipe_expression(pipe.source, build))
    return text


def _pipe_expression(source: str, build: "SurveyBuild") -> str:
    """${...} that prints an earlier answer: the selected text, the number, or the typed text."""
    name = build.labels[source]
    question = build.questions.get(source)
    kind = question.type if question else "single_select"
    if kind == "multi_select":
        return '${", ".join(row.text for row in ' + name + ".rows if row)}"
    if kind in {"numeric", "allocation"}:
        return "${" + name + ".ival}"
    if kind in {"text", "date"}:
        return "${" + name + ".val}"
    return "${" + name + ".selected.text if " + name + '.selected else ""}'


def _autofill(parent: ET.Element, tag: str, question: Question, build: "SurveyBuild") -> None:
    """Answer the question in code before it is reached ("autopunch 0 and do not show")."""
    fill = spec_of(question).autofill
    if fill is None:
        return
    name = build.labels[question.id]
    row = build.rows.get(question.id, {}).get(str(fill.code))
    if tag == "checkbox" and row:
        action = f"{name}.{row}.val = 1"
    elif tag in {"radio", "select"} and row:
        action = f"{name}.val = {name}.{row}.index"
    else:
        action = (
            f"{name}.val = {fill.code!r}"
            if not str(fill.code).lstrip("-").isdigit()
            else f"{name}.val = {fill.code}"
        )
    if fill.when is not None:
        condition = translate(
            fill.when, build.questions, build.labels, build.rows, build.cols, build.issues
        )
        action = f"if {condition}:\n    {action}"
    add_element(parent, "exec", action)


def _validations(node: ET.Element, question: Question, build: "SurveyBuild") -> None:
    """Checks that stop the page with a message, and one-time prompts before an answer is accepted."""
    spec = spec_of(question)
    name = build.labels[question.id]
    lines: list[str] = []
    for check in spec.validations:
        condition = translate(
            check.error_when, build.questions, build.labels, build.rows, build.cols, build.issues
        )
        lines.append(f"if {condition}:\n    error({check.message!r})")
    rows = build.rows.get(question.id, {})
    chosen = [f"{name}.{rows[str(code)]}" for code in spec.confirm_codes if str(code) in rows]
    if chosen and spec.confirm_message:
        flag = f"{name}_confirm_asked"
        lines.append(
            f"if ({' or '.join(chosen)}) and not p.get({flag!r}):\n"
            f"    p.{flag} = 1\n"
            f"    error({spec.confirm_message!r})"
        )
    if lines:
        add_element(node, "validate", "\n".join(lines) + "\n")


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


def _option_rows(
    node: ET.Element,
    question: Question,
    build: "SurveyBuild | None" = None,
    values: bool = False,
) -> list[Punch]:
    """Add one row per option, labelled by its punch code.

    Args:
        node: Question element.
        question: Question.
        build: Shared build state, for row labels and option conditions.
        values: Write ``value`` with the punch code (single-choice questions).

    Returns:
        Punches in option order. No-answer codes become ``noanswer`` elements.
    """
    punches: list[Punch] = []
    spec = spec_of(question)
    labels = build.rows.get(question.id, {}) if build else {}
    conditions = {str(item.code): item.when for item in spec.option_conditions}
    noanswer = {str(code) for code in spec.noanswer_codes}
    taken: set[str] = set()
    for index, option in enumerate(question.options, start=1):
        row_label = labels.get(str(option.code), f"r{index}")
        if row_label in taken:
            # Reason: a questionnaire can repeat a code by mistake; Decipher needs unique rows.
            if build:
                _warn(
                    build,
                    f"{question.id} uses code {option.code} more than once; check the questionnaire.",
                )
            suffix = 2
            while f"{row_label}_{suffix}" in taken:
                suffix += 1
            row_label = f"{row_label}_{suffix}"
        taken.add(row_label)
        if str(option.code) in noanswer:
            add_element(node, "noanswer", option.label, label=row_label)
            punches.append(Punch(code=str(option.code), label=option.label, row_label=row_label))
            continue
        attrs: dict[str, str] = {}
        if values and str(option.code).lstrip("-").isdigit():
            attrs["value"] = str(option.code)
        if build and str(option.code) in conditions:
            attrs["cond"] = translate(
                conditions[str(option.code)],
                build.questions,
                build.labels,
                build.rows,
                build.cols,
                build.issues,
            )
        # Reason: exclusive only means something where several answers are allowed.
        if _exclusive(option, question) and question.type == "multi_select":
            attrs["exclusive"] = "1"
        if option.open_text:
            attrs["open"] = "1"
            attrs["openSize"] = "25"
        # Reason: a question can shuffle because it follows another's order, so the
        # element's own shuffle decides whether anchored rows must stay put.
        if "rows" in (node.get("shuffle") or "") and (
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
    spec = spec_of(question)
    name = build.labels[question.id]
    for option in question.options:
        if not option.terminate:
            continue
        row_label = by_code.get(str(option.code))
        if row_label is None:
            continue
        _term(
            parent,
            build,
            question,
            f"Term_{name}_{row_label}",
            f"{name}.{row_label}",
            f"{question.id}: TERMINATE - {option.label}",
        )
    if spec.terminate_when is not None:
        condition = translate(
            spec.terminate_when, build.questions, build.labels, build.rows, build.cols, build.issues
        )
        _term(parent, build, question, f"Term_{name}", condition, f"{question.id}: TERMINATE")
    for number, rule in enumerate(spec.terminate_rules, start=1):
        condition = translate(
            rule.when, build.questions, build.labels, build.rows, build.cols, build.issues
        )
        description = f"{question.id}: TERMINATE" + (f" - {rule.label}" if rule.label else "")
        _term(
            parent,
            build,
            question,
            f"Term_{name}_{number}",
            condition,
            description,
            rule.immediately,
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


def _term(
    parent: ET.Element,
    build: SurveyBuild,
    question: Question,
    label: str,
    condition: str,
    description: str,
    immediately: bool | None = None,
) -> None:
    """Add a terminate now, or hold it until the end of the screener when terminates are flags.

    Args:
        parent: Parent element.
        build: Shared build state.
        question: Question that screens out.
        label: Proposed term label.
        condition: Decipher condition.
        description: Term text, shown in Decipher's reports.
    """
    label = safe_label(label, build.used)
    after = build.terminate_after
    deferred = (
        after is not None
        and not (spec_of(question).terminate_immediately if immediately is None else immediately)
        and build.order.get(question.id, 0) < build.order.get(after, -1)
    )
    if deferred:
        build.deferred_terms.append((label, condition, description))
        return
    add_element(parent, "term", description, label=label, cond=condition)


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


def _shufflable(question: Question) -> bool:
    """Whether the question has at least two rows to put in random order.

    A number or text entry whose only "row" is a no-answer box has nothing to shuffle.
    """
    noanswer = {str(code) for code in spec_of(question).noanswer_codes}
    rows = question.matrix_items or [o for o in question.options if str(o.code) not in noanswer]
    return len(rows) > 1


def _row_set(question: Question, build: SurveyBuild) -> list[str]:
    """The row labels Decipher compares for shuffleBy, without no-answer boxes."""
    noanswer = {str(code) for code in spec_of(question).noanswer_codes}
    return sorted(
        label for code, label in build.rows.get(question.id, {}).items() if code not in noanswer
    )


def row_order(
    question: Question, build: SurveyBuild, seen: frozenset[str] = frozenset()
) -> tuple[bool, str | None, str | None]:
    """How a question's rows are ordered: shuffled, following another question, or fixed.

    Decipher accepts ``shuffleBy`` only on a question whose rows shuffle, following a
    question that shuffles with the same rows. "Same order as" a question in a fixed
    order needs nothing, and one whose answer list differs cannot share its order.

    Args:
        question: Question being built.
        build: Shared build state.
        seen: Questions already on this "same order as" chain, to stop a loop.

    Returns:
        Whether the rows shuffle, the ``shuffleBy`` label or None, and a warning or None.
    """
    if not _shufflable(question):
        return False, None, None
    own = question.randomize_options
    leader_id = spec_of(question).same_order_as or ""
    leader = build.questions.get(leader_id)
    label = build.labels.get(leader_id)
    if leader is None or label is None or leader_id == question.id or leader_id in seen:
        return own, None, None
    leader_shuffles, _, _ = row_order(leader, build, seen | {question.id})
    if not leader_shuffles:
        return own, None, None
    if _row_set(question, build) != _row_set(leader, build):
        return (
            True,
            None,
            f"{question.id} should keep the same order as {leader_id}, but their answer lists "
            "differ, so Decipher cannot share the order. It is shuffled on its own; check "
            "whether the order should match.",
        )
    return True, label, None


def _warn(build: SurveyBuild, message: str) -> None:
    """Record a programming warning once.

    Args:
        build: Shared build state.
        message: Warning text.
    """
    if message not in build.warnings:
        build.warnings.append(message)
