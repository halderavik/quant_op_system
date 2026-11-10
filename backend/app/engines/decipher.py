"""Compile a questionnaire into importable Forsta Decipher survey XML."""

import re
import xml.etree.ElementTree as ET

from app.engines.decipher_expr import punch_maps, safe_label, skip_hides
from app.engines.decipher_markup import SurveyBuild, add_element
from app.engines.decipher_questions import emit_question
from app.engines.flow import validate_questionnaire
from app.schemas.decipher import CoverageItem, DecipherProgram
from app.schemas.questionnaire import Module, Questionnaire

_COND_REF = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*(?:r\d+|c\d+|ival|val|any|count)\b")
_ROW_NAME = re.compile(r"^(?:r|c|ch)\d+$")
# Reason: row, column, and choice labels are unique inside one question, not across the survey.
_SCOPED_TAGS = {"row", "col", "choice", "looprow", "loopvar"}


def compile_decipher(document: Questionnaire) -> DecipherProgram:
    """Program every structured question into Decipher XML.

    Args:
        document: Canonical questionnaire. Programmer notes are copied, not executed.

    Returns:
        Survey XML and a coverage report. A failed report is not ready to import.
    """
    issues = _structure_issues(document)
    if issues:
        return DecipherProgram(
            title=document.title,
            xml="",
            validation_status="failed",
            issues=issues,
        )
    xml, items, warnings, issues = _build(document)
    issues.extend(_xml_issues(xml, items))
    if issues:
        status = "failed"
    elif warnings or any(item.status == "partial" for item in items):
        status = "passed_with_warnings"
    else:
        status = "passed"
    return DecipherProgram(
        title=document.title,
        xml=xml,
        items=items,
        warnings=warnings,
        validation_status=status,
        issues=issues,
    )


def _structure_issues(document: Questionnaire) -> list[str]:
    """Reject instruments that cannot be programmed unambiguously.

    Args:
        document: Questionnaire.

    Returns:
        Fatal issues. An empty list means programming can start.
    """
    issues: list[str] = []
    if not document.questions:
        issues.append("A questionnaire needs at least one question before it can be programmed.")
    ids = [question.id for question in document.questions]
    if len(ids) != len(set(ids)):
        issues.append("Question ids must be unique before they can be programmed.")
    known = set(ids)
    for question in document.questions:
        for rule in question.routing:
            if rule.go_to not in known and rule.go_to not in {"END", "TERMINATE"}:
                issues.append(f"{question.id} routes to unknown question {rule.go_to}.")
    # Reason: a punch label or hidden variable is not a question, so programming stops
    # before that name is written into a Decipher condition.
    for issue in validate_questionnaire(document).issues:
        if issue.code == "bad_ref":
            issues.append(issue.message)
    return issues


def _build(document: Questionnaire) -> tuple[str, list[CoverageItem], list[str], list[str]]:
    """Build the survey element tree.

    Args:
        document: Questionnaire with unique ids and known routes.

    Returns:
        XML text, coverage items, warnings, and expression issues.
    """
    used: set[str] = set()
    labels = {question.id: safe_label(question.id, used) for question in document.questions}
    rows, cols = punch_maps(document)
    questions = {question.id: question for question in document.questions}
    issues: list[str] = []
    hides = skip_hides(document, labels, rows, cols, issues)
    build = SurveyBuild(
        questions=questions,
        labels=labels,
        rows=rows,
        cols=cols,
        hides=hides,
        used=used,
        issues=issues,
    )
    survey = ET.Element(
        "survey",
        {
            "name": _survey_name(document.title),
            "alt": document.title,
            "compat": "153",
            # Reason: Decipher rejects compat 151 and higher unless delphi is set.
            "delphi": "1",
            "builderCompatible": "1",
            "state": "testing",
            "secure": "1",
            "setup": "term,decLang,quota,time",
        },
    )
    _samples(survey)
    for note in document.sample_notes:
        survey.append(ET.Comment(f" Sample: {note} "))
    for note in document.programming_notes:
        survey.append(ET.Comment(f" Programming: {note} "))
    items: list[CoverageItem] = []
    parent = survey
    current: str | None = None
    opened = False
    for question in document.questions:
        module = _module_for(document, question.id)
        key = module.id if module else None
        if not opened or key != current:
            parent = _block(survey, module, build) if module else survey
            current = key
            opened = True
        items.append(emit_question(parent, question, build))
        add_element(parent, "suspend")
    ET.indent(survey, space="  ")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(survey, encoding="unicode")
    return xml, items, build.warnings, build.issues


def _block(survey: ET.Element, module: Module, build: SurveyBuild) -> ET.Element:
    """Open a Decipher block for one module stretch.

    Args:
        survey: Survey root.
        module: Module being entered.
        build: Shared build state.

    Returns:
        Block element.
    """
    block = add_element(survey, "block", label=safe_label(f"Block_{module.id}", build.used))
    block.append(ET.Comment(f" {module.title} "))
    return block


def _module_for(document: Questionnaire, question_id: str) -> Module | None:
    """Return the first module that lists a question.

    Args:
        document: Questionnaire.
        question_id: Question id.

    Returns:
        Module, or None when the question is unassigned.
    """
    for module in document.modules:
        if question_id in module.question_ids:
            return module
    return None


def _samples(survey: ET.Element) -> None:
    """Add the open-link sample source required to test an imported survey.

    Args:
        survey: Survey root.
    """
    sources = add_element(survey, "samplesources", default="0")
    source = add_element(sources, "samplesource", list="0")
    add_element(source, "title", "Open Survey")
    add_element(
        source,
        "invalid",
        "You are missing information in the URL. Please verify the URL with the original invite.",
    )
    add_element(source, "completed", "It seems you have already completed this survey.")
    add_element(source, "exit", "Thank you for taking our survey.", cond="terminated")
    add_element(
        source,
        "exit",
        "Thank you for taking our survey. Your efforts are greatly appreciated!",
        cond="qualified",
    )
    add_element(source, "exit", "Thank you for taking our survey.", cond="overquota")


def _survey_name(title: str) -> str:
    """Return a Decipher survey name derived from the title.

    Args:
        title: Questionnaire title.

    Returns:
        A letter-leading name of at most 40 characters.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", title)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"Survey{cleaned}"
    return cleaned[:40] or "Survey"


def _xml_issues(xml: str, items: list[CoverageItem]) -> list[str]:
    """Check that the programmed XML is well-formed and complete.

    Args:
        xml: Survey document.
        items: Coverage rows that must appear as labels.

    Returns:
        Fatal issues.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return [f"The survey XML is not well-formed ({exc})."]
    labels = [
        element.get("label")
        for element in root.iter()
        if element.get("label") and element.tag not in _SCOPED_TAGS
    ]
    issues: list[str] = []
    if len(labels) != len(set(labels)):
        issues.append("Decipher labels must be unique.")
    for element in root.iter():
        scoped = [
            child.get("label")
            for child in list(element)
            if child.tag in _SCOPED_TAGS and child.get("label")
        ]
        if len(scoped) != len(set(scoped)):
            parent = element.get("label") or element.tag
            issues.append(f"Labels inside {parent} must be unique.")
    known = set(labels)
    for item in items:
        if item.label not in known:
            issues.append(f"{item.question_id} is missing from the survey XML.")
    for element in root.iter("goto"):
        target = element.get("target")
        if target not in known:
            issues.append(f"Goto target {target} does not exist.")
    seen: set[str] = set()
    for element in root.iter():
        condition = element.get("cond")
        if not condition:
            continue
        for match in _COND_REF.finditer(condition):
            name = match.group(1)
            if _ROW_NAME.match(name) or name in known or name in seen:
                continue
            seen.add(name)
            issues.append(f"Condition refers to unknown question {name}.")
    return issues
