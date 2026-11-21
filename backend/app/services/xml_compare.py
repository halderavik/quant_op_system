"""Side-by-side comparison of the generated survey XML with an edited or reference XML.

The matching and the checks come from ``decipher_similarity.compare_questionnaire``,
the engine the benchmark scores with. This module groups its checks by question
and adds each question's XML from both files, as written, for a side-by-side view.
The reference XML is used for this answer only and is not stored.
"""

import re
import xml.etree.ElementTree as ET
from typing import Any

from sqlalchemy.orm import Session

from app.engines.decipher_similarity import (
    QUESTION_TAGS,
    QUESTIONNAIRE_AREAS,
    _key,
    _parse,
    _questions,
    compare_questionnaire,
)
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.questionnaire import Questionnaire

MAX_REFERENCE_CHARS = 5_000_000
_SNIPPET_CHARS = 20_000


def compare_with_reference(db: Session, project_id: str, reference: str) -> dict[str, Any]:
    """Compare the project's latest generated XML with a reference XML.

    Args:
        db: Session.
        project_id: Project id.
        reference: Survey XML taken as correct (hand-edited, or programmed elsewhere).

    Returns:
        The comparison; see ``compare_xml``.

    Raises:
        AppError: No generated XML yet, or the reference is not survey XML.
    """
    survey = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    generated = str((survey.content or {}).get("xml") or "") if survey else ""
    if not generated:
        raise AppError(
            "Program the survey first; there is no generated XML to compare.", "not_found", 404
        )
    current = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    ids: set[str] = set()
    if current is not None:
        document = Questionnaire.model_validate(current.content)
        ids = {q.id for q in document.questions} | {v.id for v in document.derived_variables}
    result = compare_xml(generated, reference, ids)
    result["generated_version"] = survey.version if survey else None
    return result


def compare_xml(generated: str, reference: str, questionnaire_ids: set[str]) -> dict[str, Any]:
    """Group the comparison checks by question, with both XML snippets.

    Args:
        generated: Survey XML built from the questionnaire.
        reference: Survey XML taken as correct.
        questionnaire_ids: Question and derived-variable ids; only these are scored.
            Empty means every question in either file is scored.

    Returns:
        Overall and per-area match, one row per question (reference order, then
        questions only the generated XML has), other checks such as terminates,
        and what was left out of the score.
    """
    if len(reference) > MAX_REFERENCE_CHARS:
        raise AppError("That reference XML is too large to compare.", "bad_request", 400)
    try:
        reference_root = _parse(reference)
    except ET.ParseError as exc:
        raise AppError(f"The reference is not valid XML: {exc}.", "bad_request", 400) from None
    generated_root = _parse(generated)
    ours = _questions(generated_root)
    theirs = _questions(reference_root)
    if not theirs:
        raise AppError("The reference XML has no survey questions to compare.", "bad_request", 400)
    scope = questionnaire_ids or {q.label for q in [*ours.values(), *theirs.values()]}
    similarity = compare_questionnaire(generated, reference, scope)

    by_question: dict[str, list[dict[str, Any]]] = {}
    other: list[dict[str, Any]] = []
    for check in similarity.checks:
        row = {
            "area": check.area,
            "check": check.check,
            "passed": check.passed,
            "detail": check.detail,
            "item": check.item,
        }
        key = _key(check.item)
        if check.area != "Terminates" and (key in theirs or key in ours):
            by_question.setdefault(key, []).append(row)
        else:
            other.append(row)

    scoped = {_key(item) for item in scope}
    rows: list[dict[str, Any]] = []
    order = [*theirs, *[key for key in ours if key not in theirs]]
    for key in order:
        if key not in scoped:
            continue
        mine, ref = ours.get(key), theirs.get(key)
        checks = by_question.get(key, [])
        passed = sum(check["passed"] for check in checks)
        if mine is None:
            status = "missing"
        elif ref is None:
            status = "extra"
        else:
            status = "match" if passed == len(checks) else "differs"
        rows.append(
            {
                "key": key,
                "label": (ref or mine).label,  # type: ignore[union-attr]
                "status": status,
                "passed": passed,
                "total": len(checks),
                "generated_xml": raw_element(generated, mine.label, mine.tag) if mine else "",
                "reference_xml": raw_element(reference, ref.label, ref.tag) if ref else "",
                "checks": checks,
            }
        )
    hit, total = similarity.score()
    return {
        "match": round(100 * hit / total, 1) if total else None,
        "areas": {
            area: {"passed": a, "total": b}
            for area in QUESTIONNAIRE_AREAS
            for a, b in [similarity.score(area)]
            if b
        },
        "questions": rows,
        "other_checks": other,
        "not_scored": {**similarity.only_reference, **similarity.only_generated},
    }


def raw_element(xml: str, label: str, tag: str) -> str:
    """One question's XML exactly as written in the file, comments and all.

    Args:
        xml: Survey XML text.
        label: Question label.
        tag: Element name (radio, checkbox, ...).

    Returns:
        The element's source text, trimmed to a readable length; empty when not found.
    """
    if tag not in QUESTION_TAGS:
        return ""
    opening = re.search(
        rf"<(?:\w+:)?{tag}\b[^>]*?\blabel\s*=\s*[\"']{re.escape(label)}[\"'][^>]*?(/?)>", xml
    )
    if opening is None:
        return ""
    if opening.group(1) == "/":
        return opening.group(0)
    closing = re.compile(rf"</(?:\w+:)?{tag}\s*>")
    end = closing.search(xml, opening.end())
    text = xml[opening.start() : end.end()] if end else opening.group(0)
    start_of_line = xml.rfind("\n", 0, opening.start()) + 1
    indent = xml[start_of_line : opening.start()]
    if indent.strip() == "" and indent:
        text = "\n".join(
            line[len(indent) :] if line.startswith(indent) else line
            for line in (indent + text).splitlines()
        )
    if len(text) > _SNIPPET_CHARS:
        text = text[:_SNIPPET_CHARS] + "\n<!-- trimmed -->"
    return text


__all__ = ["compare_with_reference", "compare_xml", "raw_element"]
