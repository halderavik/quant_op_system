"""Walk a Decipher survey XML file the way a respondent would."""

import re
import xml.etree.ElementTree as ET
from typing import Any

from app.engines.decipher_cond import ConditionError, condition_holds
from app.schemas.preview import PreviewAnswer, PreviewColumn, PreviewRow, PreviewScreen

_STEPS = {
    "radio",
    "checkbox",
    "number",
    "textarea",
    "text",
    "select",
    "html",
    "loop",
    "term",
    "goto",
}
_LOOP_NOTE = "Nested questions are not in the questionnaire schema."
_DATE = "Please enter a date as YYYY-MM-DD"
_TOTAL = "Please make sure the numbers total 100"
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def step_preview(
    xml: str, answers: dict[str, PreviewAnswer], current_label: str | None
) -> PreviewScreen:
    """Return the next screen after the question the respondent just answered.

    Args:
        xml: Decipher survey document.
        answers: Answers keyed by question label.
        current_label: Label just answered. None starts at the first screen.

    Returns:
        The next question, a terminate or thank-you screen, or an error screen.
    """
    if not xml.strip():
        return PreviewScreen(status="error", message="The survey XML is empty.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return PreviewScreen(status="error", message=f"The survey XML is not well-formed ({exc}).")
    nodes = _flatten(root)
    start = 0
    if current_label is not None:
        found = _index_of(nodes, current_label)
        if found is None:
            return PreviewScreen(
                status="error",
                message=f"This preview could not find question {current_label}.",
            )
        start = found + 1
    return _walk(nodes, _facts(answers), start, _exits(root), xml)


def _flatten(element: ET.Element) -> list[ET.Element]:
    """List question, term, and goto elements in document order.

    Args:
        element: Survey element or one of its descendants.

    Returns:
        Elements the respondent can land on. Sample sources are omitted.
    """
    if element.tag == "samplesources":
        return []
    if element.tag in _STEPS:
        return [element]
    found: list[ET.Element] = []
    for child in list(element):
        found.extend(_flatten(child))
    return found


def _exits(root: ET.Element) -> dict[str, str]:
    """Read the qualified and terminated exit lines.

    Args:
        root: Survey root.

    Returns:
        Exit condition to respondent text.
    """
    found: dict[str, str] = {}
    for node in root.iter("exit"):
        kind = node.get("cond")
        if kind and node.text:
            found[kind] = node.text.strip()
    return found


def _walk(
    nodes: list[ET.Element],
    facts: dict[str, Any],
    start: int,
    exits: dict[str, str],
    xml: str,
) -> PreviewScreen:
    """Move forward until a visible screen or the end of the survey.

    Args:
        nodes: Flattened survey elements.
        facts: Answer values for conditions.
        start: Index to resume from.
        exits: Sample-source exit text.
        xml: Original XML, used to detect the empty-loop comment.

    Returns:
        The screen to show.
    """
    index = start
    jumps: set[int] = set()
    while index < len(nodes):
        element = nodes[index]
        visible, error = _visible(element.get("cond"), facts)
        if error is not None:
            return error
        if element.tag == "goto":
            if visible:
                if index in jumps:
                    return PreviewScreen(
                        status="error",
                        message="This preview stopped because the survey jumps in a loop.",
                    )
                jumps.add(index)
                target = element.get("target") or ""
                jump = _index_of(nodes, target)
                if jump is None:
                    return PreviewScreen(
                        status="error",
                        message=f"Goto target {target} does not exist.",
                    )
                index = jump
                continue
            index += 1
            continue
        if element.tag == "term" and visible:
            return _term(element, exits)
        if visible and element.tag != "term":
            return _question(element, xml)
        index += 1
    return PreviewScreen(
        status="complete",
        message=exits.get("qualified", "Thank you for taking our survey."),
    )


def _visible(condition: str | None, facts: dict[str, Any]) -> tuple[bool, PreviewScreen | None]:
    """Evaluate a condition attribute.

    Args:
        condition: Decipher condition, or None when the element is always shown.
        facts: Answer values.

    Returns:
        Whether the element is shown, and an error screen when the condition cannot be read.
    """
    if not condition:
        return True, None
    try:
        return condition_holds(condition, facts), None
    except ConditionError as exc:
        return False, PreviewScreen(
            status="error",
            message=f"This preview cannot read the condition: {exc.condition}",
        )


def _term(element: ET.Element, exits: dict[str, str]) -> PreviewScreen:
    """Build the screen for a terminate element.

    Args:
        element: Term element.
        exits: Sample-source exit text.

    Returns:
        Terminated screen.
    """
    return PreviewScreen(
        status="terminated",
        label=element.get("label"),
        element="term",
        title=_title(element),
        message=exits.get("terminated", ""),
    )


def _question(element: ET.Element, xml: str) -> PreviewScreen:
    """Build a respondent screen from one question element.

    Args:
        element: Question or loop element.
        xml: Original XML.

    Returns:
        Question screen. Programmer notes are not copied.
    """
    return PreviewScreen(
        status="question",
        label=element.get("label"),
        element=element.tag,
        title=_title(element),
        comment=_child_text(element, "comment"),
        required=_required(element),
        atleast=_atleast(element),
        rows=_rows(element),
        cols=_named(element, "col"),
        choices=_named(element, "choice"),
        shuffle=element.get("shuffle") == "rows",
        verify=element.get("verify"),
        check=_check(element),
        warning=_LOOP_NOTE if element.tag == "loop" and _LOOP_NOTE in xml else None,
    )


def _title(element: ET.Element) -> str:
    """Return the respondent-facing title.

    Args:
        element: Survey element.

    Returns:
        Title text, or the element's own text for html and term.
    """
    title = _child_text(element, "title")
    if title:
        return title
    return (element.text or "").strip()


def _child_text(element: ET.Element, tag: str) -> str | None:
    """Return stripped text for a direct child.

    Args:
        element: Parent element.
        tag: Child tag.

    Returns:
        Text, or None when the child is missing or blank.
    """
    child = element.find(tag)
    if child is None or not child.text:
        return None
    text = child.text.strip()
    return text or None


def _rows(element: ET.Element) -> list[PreviewRow]:
    """Collect rows and loop rows.

    Args:
        element: Question or loop.

    Returns:
        Rows in XML order.
    """
    rows: list[PreviewRow] = []
    for child in list(element):
        if child.tag == "row":
            rows.append(
                PreviewRow(
                    label=child.get("label") or "",
                    text=(child.text or "").strip(),
                    exclusive=child.get("exclusive") == "1",
                    open=child.get("open") == "1",
                    randomize=child.get("randomize") != "0",
                )
            )
        elif child.tag == "looprow":
            variable = child.find("loopvar")
            text = ""
            if variable is not None and variable.text:
                text = variable.text.strip()
            rows.append(PreviewRow(label=child.get("label") or "", text=text, randomize=False))
    return rows


def _named(element: ET.Element, tag: str) -> list[PreviewColumn]:
    """Collect columns or rank choices.

    Args:
        element: Question element.
        tag: ``col`` or ``choice``.

    Returns:
        Children of that tag.
    """
    return [
        PreviewColumn(label=child.get("label") or "", text=(child.text or "").strip())
        for child in list(element)
        if child.tag == tag
    ]


def _required(element: ET.Element) -> bool:
    """Return whether the respondent must answer.

    Args:
        element: Survey element.

    Returns:
        False for display, loop, and optional questions.
    """
    if element.tag in {"html", "loop", "term", "goto"}:
        return False
    return element.get("optional") != "1"


def _atleast(element: ET.Element) -> int | None:
    """Return the checkbox minimum, when the XML sets one.

    Args:
        element: Survey element.

    Returns:
        Minimum selections, or None.
    """
    raw = element.get("atleast")
    if raw and raw.isdigit():
        return int(raw)
    return None


def _check(element: ET.Element) -> str:
    """Recognize the date and allocation checks this compiler writes.

    Args:
        element: Question element.

    Returns:
        ``date``, ``total100``, or ``none``. Other validate scripts are ignored.
    """
    node = element.find("validate")
    script = node.text if node is not None and node.text else ""
    if _DATE in script:
        return "date"
    if _TOTAL in script:
        return "total100"
    return "none"


def _index_of(nodes: list[ET.Element], label: str) -> int | None:
    """Find the first element with a label.

    Args:
        nodes: Flattened elements.
        label: Decipher label.

    Returns:
        Index, or None.
    """
    for index, element in enumerate(nodes):
        if element.get("label") == label:
            return index
    return None


def _facts(answers: dict[str, PreviewAnswer]) -> dict[str, Any]:
    """Turn answers into the dotted names conditions use.

    Args:
        answers: Answers keyed by question label.

    Returns:
        Facts such as ``S1.r1`` and ``Q3.ival``.
    """
    facts: dict[str, Any] = {}
    for label, answer in answers.items():
        _apply(facts, label, answer)
    return facts


def _apply(facts: dict[str, Any], label: str, answer: PreviewAnswer) -> None:
    """Record one answer.

    Args:
        facts: Fact map to update.
        label: Question label.
        answer: Respondent answer.
    """
    chosen = [row for row in answer.rows if row]
    for row in chosen:
        facts[f"{label}.{row}"] = True
    if chosen:
        facts[f"{label}.any"] = True
        facts[f"{label}.count"] = len(chosen)
    if len(chosen) == 1 and not answer.value:
        facts[f"{label}.val"] = chosen[0]
    for row, column in answer.cells.items():
        if not row or not column:
            continue
        facts[f"{label}.{row}.{column}"] = True
        facts[f"{label}.{row}"] = True
        facts[f"{label}.{row}.val"] = column
        facts[f"{label}.any"] = True
    for row, raw in answer.row_values.items():
        if not raw:
            continue
        facts[f"{label}.{row}"] = True
        facts[f"{label}.{row}.val"] = raw
        number = _number(raw)
        if number is not None:
            facts[f"{label}.{row}.ival"] = number
        facts[f"{label}.any"] = True
    if answer.value:
        facts[f"{label}.val"] = answer.value
        number = _number(answer.value)
        if number is not None:
            facts[f"{label}.ival"] = number
        facts[f"{label}.any"] = True


def _number(raw: str) -> int | float | None:
    """Parse a numeric answer.

    Args:
        raw: Entered text.

    Returns:
        Int or float, or None when the text is not a number.
    """
    if not _NUMBER.fullmatch(raw):
        return None
    if "." in raw:
        return float(raw)
    return int(raw)
