"""Score a generated Decipher survey against a reference survey, such as one programmed by hand.

Questions are matched by label. For each question the reference asks, the
comparison checks that the generated survey has it, with the same element type,
the same answer rows and scale columns (by label and value), a show-if when the
reference has one, and the same row piping, number range, total, and shuffle.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_QUESTION_TAGS = {"radio", "checkbox", "number", "float", "text", "textarea", "select"}
_CHECKS = (
    "present",
    "type",
    "rows",
    "columns",
    "show-if",
    "row piping",
    "range",
    "total",
    "shuffle",
)


@dataclass
class QuestionScore:
    """How one reference question compares."""

    label: str
    passed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


@dataclass
class SurveyScore:
    """Comparison of one generated survey with its reference."""

    questions: list[QuestionScore] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    reference_hidden: int = 0
    generated_hidden: int = 0
    reference_terms: int = 0
    generated_terms: int = 0

    @property
    def score(self) -> float:
        """Share of checks passed, 0 to 1."""
        passed = sum(len(q.passed) for q in self.questions)
        total = passed + sum(len(q.failed) for q in self.questions)
        return passed / total if total else 0.0

    def by_check(self) -> dict[str, tuple[int, int]]:
        """Passed and applicable counts for each kind of check."""
        counts: dict[str, list[int]] = {name: [0, 0] for name in _CHECKS}
        for question in self.questions:
            for name in question.passed:
                counts[name][0] += 1
                counts[name][1] += 1
            for name in question.failed:
                counts[name][1] += 1
        return {name: (hit, seen) for name, (hit, seen) in counts.items() if seen}


def compare_surveys(generated: str, reference: str) -> SurveyScore:
    """Compare two survey XML documents.

    Args:
        generated: Survey XML to score.
        reference: Survey XML taken as correct. Undeclared ss:/html: prefixes are tolerated.

    Returns:
        Per-question results and totals.
    """
    ours = _questions(_parse(generated))
    theirs_root = _parse(reference)
    theirs = _questions(theirs_root)
    result = SurveyScore()
    ours_by_key = {_key(label): node for label, node in ours.items()}
    for label, node in theirs.items():
        if _hidden(node):
            result.reference_hidden += 1
            continue
        result.questions.append(_score(label, node, ours_by_key.get(_key(label))))
    reference_keys = {_key(label) for label, node in theirs.items()}
    for label, node in ours.items():
        if _hidden(node):
            result.generated_hidden += 1
        elif _key(label) not in reference_keys:
            result.extra.append(label)
    result.reference_terms = sum(1 for _ in theirs_root.iter("term"))
    result.generated_terms = sum(1 for _ in _parse(generated).iter("term"))
    return result


def _parse(xml: str) -> ET.Element:
    """Parse survey XML, removing undeclared prefixes and builder-only markup."""
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml.strip())
    text = re.sub(r"\s+xmlns(:\w+)?=\"[^\"]*\"", "", text)
    text = re.sub(r"(\s)[a-zA-Z]+:([A-Za-z][\w.-]*\s*=)", r"\1\2", text)
    text = re.sub(r"<(/?)(?:ss|html|builder):", r"<\1", text)
    return ET.fromstring(text)


_PARENTS: dict[int, dict[ET.Element, ET.Element]] = {}


def _questions(root: ET.Element) -> dict[str, ET.Element]:
    parents = {child: parent for parent in root.iter() for child in parent}
    found: dict[str, ET.Element] = {}
    for node in root.iter():
        if node.tag in _QUESTION_TAGS and node.get("label") and node.get("label") not in found:
            found[node.get("label")] = node
            _PARENTS[id(node)] = parents
    return found


def _hidden(node: ET.Element) -> bool:
    """A question respondents never see: computed, or switched off."""
    where = node.get("where") or ""
    return (
        "execute" in where
        and "survey" not in where.replace("execute,survey,report", "")
        or (node.get("cond") or "").strip() == "0"
        or where == "execute"
    )


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", label.lower())


def _rows(node: ET.Element, tag: str) -> set[str]:
    rows = set()
    for child in node:
        if child.tag in {tag, "noanswer"} and (child.get("cond") or "").strip() != "0":
            rows.add(_cell(child) if tag == "col" else child.get("label") or "")
    return rows


def _cell(child: ET.Element) -> str:
    """A column as label=value, where a missing value is the number in the label (c3 -> 3)."""
    label = child.get("label") or ""
    value = child.get("value")
    if value is None:
        digits = re.sub(r"\D", "", label)
        value = digits
    return f"{label}={value}"


def _condition(node: ET.Element, parents: dict[ET.Element, ET.Element]) -> bool:
    """Whether the question, or a block or loop around it, has a show-if."""
    current: ET.Element | None = node
    while current is not None:
        if (current.get("cond") or "").strip() not in {"", "1"}:
            return True
        current = parents.get(current)
        if current is not None and current.tag not in {"block", "loop"}:
            break
    return False


def _score(label: str, reference: ET.Element, generated: ET.Element | None) -> QuestionScore:
    score = QuestionScore(label=label)
    if generated is None:
        score.failed["present"] = "missing"
        return score
    score.passed.append("present")

    def check(name: str, ok: bool, detail: str) -> None:
        if ok:
            score.passed.append(name)
        else:
            score.failed[name] = detail

    same_tag = (
        reference.tag == generated.tag
        or {reference.tag, generated.tag} <= {"text", "textarea"}
        or {
            reference.tag,
            generated.tag,
        }
        <= {"number", "float"}
    )
    check("type", same_tag, f"{generated.tag} instead of {reference.tag}")
    ref_rows, gen_rows = _rows(reference, "row"), _rows(generated, "row")
    if ref_rows:
        check(
            "rows",
            ref_rows == gen_rows,
            f"rows {sorted(gen_rows)[:8]} instead of {sorted(ref_rows)[:8]}",
        )
    ref_cols, gen_cols = _rows(reference, "col"), _rows(generated, "col")
    if ref_cols:
        check(
            "columns",
            ref_cols == gen_cols,
            f"columns {sorted(gen_cols)[:6]} instead of {sorted(ref_cols)[:6]}",
        )
    ref_cond = _condition(reference, _PARENTS.get(id(reference), {}))
    gen_cond = _condition(generated, _PARENTS.get(id(generated), {}))
    if ref_cond or gen_cond:
        check(
            "show-if",
            ref_cond == gen_cond,
            "has a show-if the reference lacks" if gen_cond else "show-if missing",
        )
    if reference.get("rowCond") or generated.get("rowCond"):
        check(
            "row piping",
            bool(reference.get("rowCond")) == bool(generated.get("rowCond")),
            "rowCond differs",
        )
    if reference.get("verify") and "range" in (reference.get("verify") or ""):
        check(
            "range",
            _range(reference) == _range(generated),
            f"{generated.get('verify')} instead of {reference.get('verify')}",
        )
    if reference.get("amount") or generated.get("amount"):
        check(
            "total",
            reference.get("amount") == generated.get("amount"),
            f"amount {generated.get('amount')} instead of {reference.get('amount')}",
        )
    ref_shuffle = "rows" in (reference.get("shuffle") or "")
    gen_shuffle = "rows" in (generated.get("shuffle") or "")
    if ref_rows and (ref_shuffle or gen_shuffle):
        check("shuffle", ref_shuffle == gen_shuffle, "shuffled" if gen_shuffle else "not shuffled")
    return score


def _range(node: ET.Element) -> str:
    match = re.search(r"range\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", node.get("verify") or "")
    return f"{match.group(1)},{match.group(2)}" if match else ""
