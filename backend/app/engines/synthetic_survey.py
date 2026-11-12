"""Read a programmed Decipher survey into question specs for synthetic respondents.

Answer codes come from the coverage report the compiler stored with the XML, so
the data uses the questionnaire's codes. Variable names follow the
questionnaire's ``variable_names`` when they line up with the XML rows.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from app.engines.decipher_preview import _flatten
from app.errors import AppError

_ANSWERED = {"radio", "checkbox", "number", "textarea", "text", "select"}
_RANGE = re.compile(r"range\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)")
_NAME = re.compile(r"[^A-Za-z0-9_]")
_TERM_ROWS = re.compile(r"^\s*\w+\.\w+(?:\s+or\s+\w+\.\w+)*\s*$")
_TERM_TOKEN = re.compile(r"(\w+)\.(\w+)")


@dataclass
class Choice:
    """One row, column, or rank position."""

    label: str
    code: str
    text: str
    exclusive: bool = False
    open: bool = False


@dataclass
class Spec:
    """One step in the survey flow."""

    label: str
    tag: str
    kind: str
    title: str = ""
    cond: str | None = None
    rows: list[Choice] = field(default_factory=list)
    cols: list[Choice] = field(default_factory=list)
    positions: int = 0
    required: bool = True
    atleast: int | None = None
    lower: float | None = None
    upper: float | None = None
    target: str = ""
    names: list[str] = field(default_factory=list)
    open_names: dict[str, str] = field(default_factory=dict)
    ending: set[str] = field(default_factory=set)

    @property
    def answered(self) -> bool:
        """Return whether respondents give an answer here."""
        return self.kind in {
            "single",
            "multi",
            "grid",
            "rank",
            "number",
            "allocation",
            "text",
            "date",
        }


def parse_survey(
    xml: str,
    items: list[dict[str, Any]],
    questions: list[dict[str, Any]] | None = None,
) -> list[Spec]:
    """Turn survey XML into ordered specs.

    Args:
        xml: Decipher survey XML.
        items: Coverage items stored with the XML. Their punches carry the codes.
        questions: Questionnaire questions, used for variable names.

    Returns:
        Specs in document order, including terminate, goto, and display steps.

    Raises:
        AppError: The XML cannot be read or has no questions.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise AppError(f"The survey XML is not well-formed ({exc}).", "bad_xml") from exc
    punches = _punches(items)
    by_label = _questions_by_label(items, questions or [])
    specs = [_spec(node, punches.get(node.get("label") or "", {})) for node in _flatten(root)]
    for spec in specs:
        if spec.answered:
            spec.names = _names(spec, by_label.get(spec.label))
            spec.open_names = {
                row.label: _safe(f"{spec.label}r{row.code}oe")
                for row in spec.rows
                if row.open and spec.kind in {"single", "multi"}
            }
    _mark_endings(specs)
    if not any(spec.answered for spec in specs):
        raise AppError("The survey XML has no questions to answer.", "bad_xml")
    _dedupe_names(specs)
    return specs


def _mark_endings(specs: list[Spec]) -> None:
    """Mark the rows whose choice sends a respondent to a terminate.

    Only plain conditions such as ``S1.r2`` or ``S4.r1 or S4.r2`` are read.

    Args:
        specs: Specs in order.
    """
    by_label = {spec.label: spec for spec in specs if spec.answered}
    for spec in specs:
        if spec.kind != "term" or not spec.cond or not _TERM_ROWS.match(spec.cond):
            continue
        for label, row in _TERM_TOKEN.findall(spec.cond):
            target = by_label.get(label)
            if target is not None and any(item.label == row for item in target.rows):
                target.ending.add(row)


def _punches(items: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Map each question label to its row and column codes.

    Args:
        items: Coverage items.

    Returns:
        Label to ``{row_label: code}``.
    """
    found: dict[str, dict[str, str]] = {}
    for item in items:
        label = str(item.get("label") or "")
        codes = {
            str(punch.get("row_label") or ""): str(punch.get("code") or "")
            for punch in list(item.get("punches") or [])
        }
        found[label] = codes
    return found


def _questions_by_label(
    items: list[dict[str, Any]], questions: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Map XML labels to questionnaire questions.

    Args:
        items: Coverage items, which pair question ids with XML labels.
        questions: Questionnaire questions.

    Returns:
        Label to question.
    """
    by_id = {str(question.get("id") or ""): question for question in questions}
    found: dict[str, dict[str, Any]] = {}
    for item in items:
        question = by_id.get(str(item.get("question_id") or ""))
        if question is not None:
            found[str(item.get("label") or "")] = question
    return found


def _spec(node: ET.Element, codes: dict[str, str]) -> Spec:
    """Build one spec.

    Args:
        node: Flattened survey element.
        codes: Row and column codes for this question.

    Returns:
        Spec.
    """
    label = node.get("label") or ""
    title = _text(node.find("title")) or _text(node)
    spec = Spec(label=label, tag=node.tag, kind=_kind(node), title=title, cond=node.get("cond"))
    spec.required = node.get("optional") != "1"
    if node.tag == "goto":
        spec.target = node.get("target") or ""
        return spec
    rows = [child for child in list(node) if child.tag == "row"]
    cols = [child for child in list(node) if child.tag == "col"]
    choices = [child for child in list(node) if child.tag == "choice"]
    spec.rows = [_choice(child, index, codes) for index, child in enumerate(rows, start=1)]
    spec.cols = [_choice(child, index, codes) for index, child in enumerate(cols, start=1)]
    spec.positions = len(choices)
    atleast = node.get("atleast") or ""
    spec.atleast = int(atleast) if atleast.isdigit() else None
    match = _RANGE.search(node.get("verify") or "")
    if match:
        spec.lower, spec.upper = float(match.group(1)), float(match.group(2))
    return spec


def _kind(node: ET.Element) -> str:
    """Name the answer type of an element.

    Args:
        node: Survey element.

    Returns:
        Kind name. ``display`` and ``loop`` are not answered.
    """
    tag = node.tag
    has_rows = node.find("row") is not None
    if tag == "radio":
        return "grid" if node.find("col") is not None else "single"
    if tag == "checkbox":
        return "multi"
    if tag == "select":
        return "rank"
    if tag == "number":
        return "allocation" if has_rows else "number"
    if tag == "textarea":
        return "text"
    if tag == "text":
        validate = node.find("validate")
        script = validate.text if validate is not None and validate.text else ""
        return "date" if "YYYY-MM-DD" in script else "text"
    if tag in {"term", "goto", "loop"}:
        return tag
    return "display"


def _choice(node: ET.Element, index: int, codes: dict[str, str]) -> Choice:
    """Read one row, column, or choice.

    Args:
        node: Child element.
        index: One-based position, used when the coverage report has no code.
        codes: Codes keyed by row or column label.

    Returns:
        Choice.
    """
    label = node.get("label") or f"r{index}"
    return Choice(
        label=label,
        code=codes.get(label) or str(index),
        text=_text(node),
        exclusive=node.get("exclusive") == "1",
        open=node.get("open") == "1",
    )


def _text(node: ET.Element | None) -> str:
    """Return the element's own text.

    Args:
        node: Element, or None.

    Returns:
        Stripped text.
    """
    if node is None or not node.text:
        return ""
    return " ".join(node.text.split())


def _names(spec: Spec, question: dict[str, Any] | None) -> list[str]:
    """Choose one SPSS variable name per stored value.

    Args:
        spec: Answered question.
        question: Matching questionnaire question, when known.

    Returns:
        Names. Single, number, text, and date questions use one name. Rows use one each.
    """
    if spec.kind in {"single", "number", "text", "date"}:
        return [_safe(spec.label)]
    declared = [str(name) for name in list((question or {}).get("variable_names") or [])]
    prefix = f"{spec.label}r"
    lined_up = [name for name in declared if name.startswith(prefix)][: len(spec.rows)]
    if len(lined_up) == len(spec.rows) and spec.rows:
        return [_safe(name) for name in lined_up]
    if spec.kind == "grid":
        return [_safe(f"{spec.label}{row.label}") for row in spec.rows]
    return [_safe(f"{spec.label}r{row.code}") for row in spec.rows]


def _safe(name: str) -> str:
    """Make a valid SPSS variable name.

    Args:
        name: Proposed name.

    Returns:
        Letters, digits, and underscores, starting with a letter, at most 64 characters.
    """
    clean = _NAME.sub("_", name) or "V"
    if not clean[0].isalpha():
        clean = f"V{clean}"
    return clean[:64]


def _dedupe_names(specs: list[Spec]) -> None:
    """Suffix repeated names so every column is unique.

    Args:
        specs: Specs with names filled.
    """
    seen: set[str] = {"record", "syn_persona"}

    def claim(name: str) -> str:
        candidate = name
        index = 2
        while candidate.lower() in seen:
            candidate = f"{name}_{index}"
            index += 1
        seen.add(candidate.lower())
        return candidate

    for spec in specs:
        spec.names = [claim(name) for name in spec.names]
        spec.open_names = {row: claim(name) for row, name in spec.open_names.items()}
