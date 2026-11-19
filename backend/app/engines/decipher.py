"""Compile a questionnaire into importable Forsta Decipher survey XML."""

import re
import xml.etree.ElementTree as ET

from app.engines.decipher_expr import punch_maps, safe_label, skip_hides, translate
from app.engines.decipher_markup import SurveyBuild, _term, add_element, qualified
from app.engines.decipher_questions import emit_question
from app.engines.flow import reference_table, validate_questionnaire
from app.schemas.decipher import CoverageItem, DecipherProgram, Punch
from app.schemas.questionnaire import DerivedVariable, Module, Questionnaire

_COND_REF = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*(?:r\d+|c\d+|ival|val|any|count)\b")
_ROW_NAME = re.compile(r"^(?:r|c|ch)\d+$")
# Reason: row, column, and choice labels are unique inside one question, not across the survey.
_SCOPED_TAGS = {"row", "col", "choice", "looprow", "loopvar", "noanswer"}


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
    for variable in document.derived_variables:
        if variable.values or variable.compute:
            labels[variable.id] = safe_label(variable.id, used)
    rows, cols = punch_maps(document)
    _, questions, _ = reference_table(document)
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
        terminate_after=document.terminate_after,
        order={question.id: position for position, question in enumerate(document.questions)},
    )
    survey = _survey_element(
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
            # Reason: the settings B3's Decipher programmers put on every survey.
            "autosaveKey": "RID,ID,UUID,ppid,uid,uniqueid,uig,SEID,UID,transaction_id,rid",
            "browserDupes": "safe",
            "extraVariables": "ipAddress,source,record,decLang,list,userAgent,w,settings",
            "fir": "on",
            "geoip": "all",
            "html:showNumber": "0",
            "mobile": "compat",
            "mobileDevices": "smartphone,tablet,desktop",
            "ss:disableBackButton": "1",
            "ss:enableNavigation": "0",
            "ss:hideProgressBar": "0",
        }
    )
    _samples(survey)
    library = add_element(survey, "exec", GROUP_ROWS, when="init")
    for note in document.sample_notes:
        survey.append(ET.Comment(f" Sample: {note} "))
    for note in document.programming_notes:
        survey.append(ET.Comment(f" Programming: {note} "))
    items: list[CoverageItem] = []
    parent = survey
    current: str | None = None
    opened = False
    derived_after: dict[str | None, list] = {}
    for variable in document.derived_variables:
        if variable.values or variable.compute:
            derived_after.setdefault(
                variable.after if variable.after in labels else None, []
            ).append(variable)
    for variable in derived_after.pop(None, []):
        items.append(emit_derived(survey, variable, build))
    rotation_of = _rotation_places(document, build)
    rotation: tuple[int, ET.Element] | None = None
    section: tuple[int, ET.Element] | None = None
    for question in document.questions:
        module = _module_for(document, question.id)
        key = module.id if module else None
        if not opened or key != current:
            parent = _block(survey, module, build) if module else survey
            current = key
            opened = True
            rotation = section = None
        target = parent
        place = rotation_of.get(question.id)
        if place is None:
            rotation = section = None
        else:
            which, group = place
            if rotation is None or rotation[0] != which:
                outer = add_element(
                    parent,
                    "block",
                    label=safe_label(f"BLK_Rotate{which + 1}", build.used),
                    randomizeChildren="1",
                )
                note = document.rotations[which].note
                if note:
                    outer.append(ET.Comment(f" {_comment(note)} "))
                rotation, section = (which, outer), None
            if section is None or section[0] != group:
                inner = add_element(
                    rotation[1],
                    "block",
                    label=safe_label(f"BLK_Rotate{which + 1}_{group + 1}", build.used),
                    randomize="1",
                )
                section = (group, inner)
            target = section[1]
        items.append(emit_question(target, question, build))
        add_element(target, "suspend")
        for variable in derived_after.pop(question.id, []):
            items.append(emit_derived(target, variable, build))
        if question.id == document.terminate_after and build.deferred_terms:
            parent.append(
                ET.Comment(" Screen-outs flagged during the screener end the interview here. ")
            )
            for label, condition, description in build.deferred_terms:
                add_element(parent, "term", description, label=label, cond=condition)
            build.deferred_terms.clear()
    for variable in document.derived_variables:
        if not variable.values and not variable.compute:
            survey.append(
                ET.Comment(
                    f" PROGRAMMER TODO: derived variable {variable.id}: "
                    f"{_comment(variable.definition)} "
                )
            )
            _note_warning(
                build,
                f"Derived variable {variable.id} is not programmed: {variable.definition[:120]}",
            )
    if not build.needs_group_rows:
        survey.remove(library)
    ET.indent(survey, space="  ")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(survey, encoding="unicode")
    return xml, items, build.warnings, build.issues


def _survey_element(attributes: dict[str, str]) -> ET.Element:
    """The survey root with Decipher's prefixed attributes declared."""
    return ET.Element("survey", {qualified(key): value for key, value in attributes.items()})


GROUP_ROWS = """
def group_rows(question, grouped_rows):
    first_item_index = None
    shuffle_order = [row.index for row in question.rows.order]
    for index, row in enumerate(shuffle_order):
        if question.rows[row].label in grouped_rows:
            if first_item_index == None:
                first_item_index = index
            else:
                first_item_index += 1
                shuffle_order.insert(first_item_index, shuffle_order.pop(index))
    question.rows.order = shuffle_order
"""


def emit_derived(parent: ET.Element, variable: DerivedVariable, build: SurveyBuild) -> CoverageItem:
    """Program a derived variable as a hidden question set by an exec.

    Args:
        parent: Survey or block.
        variable: Derived variable with programmed values.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    if variable.compute:
        return _emit_computed(parent, variable, build)
    name = build.labels[variable.id]
    rows = build.rows.get(variable.id, {})
    lines: list[str] = []
    for value in variable.values:
        if value.when is None:
            continue
        condition = translate(
            value.when, build.questions, build.labels, build.rows, build.cols, build.issues
        )
        row = rows[str(value.code)]
        if variable.multiple:
            lines.append(f"{name}.{row}.val = 1 if ({condition}) else 0")
        else:
            keyword = "if" if not lines else "elif"
            lines.append(f"{keyword} {condition}:\n    {name}.val = {name}.{row}.index")
    parent.append(ET.Comment(f" {variable.id}: {_comment(variable.definition)} "))
    if lines:
        add_element(parent, "exec", "\n".join(lines))
    else:
        parent.append(
            ET.Comment(f" PROGRAMMER TODO: assign {variable.id} ({_comment(variable.definition)}) ")
        )
    node = add_element(
        parent,
        "checkbox" if variable.multiple else "radio",
        label=name,
        optional="1",
        where="execute,survey,report",
        **({"atleast": "0"} if variable.multiple else {}),
    )
    add_element(node, "title", variable.label or variable.id)
    for value in variable.values:
        add_element(
            node,
            "row",
            value.label,
            label=rows[str(value.code)],
            value=None if variable.multiple else str(value.code),
        )
    for note in variable.unresolved:
        node.append(ET.Comment(f" PROGRAMMER TODO: {_comment(note)} "))
    for value in variable.values:
        if value.terminate:
            row = rows[str(value.code)]
            _term(
                parent,
                build,
                build.questions[variable.id],
                f"Term_{name}_{row}",
                f"{name}.{row}",
                f"{variable.id}: TERMINATE - {value.label}",
            )
    punches = [
        Punch(code=str(v.code), label=v.label, row_label=rows[str(v.code)]) for v in variable.values
    ]
    return CoverageItem(
        question_id=variable.id,
        label=name,
        element="checkbox" if variable.multiple else "radio",
        status="partial" if variable.unresolved else "programmed",
        warnings=list(variable.unresolved),
        punches=punches,
    )


def _emit_computed(
    parent: ET.Element, variable: DerivedVariable, build: SurveyBuild
) -> CoverageItem:
    """Program a computed number (a total or a range midpoint) as a hidden question.

    Args:
        parent: Survey or block.
        variable: Derived variable with ``compute`` set.
        build: Shared build state.

    Returns:
        Coverage item.
    """
    compute = variable.compute
    assert compute is not None
    name = build.labels[variable.id]
    todos = list(variable.unresolved)
    code = ""
    if compute.kind == "sum":
        terms = []
        for source in compute.sources:
            question = build.questions.get(source)
            label = build.labels.get(source)
            if question is None or label is None:
                todos.append(f"{source} is not a question in this survey")
                continue
            rows = build.rows.get(source, {})
            wanted = [rows[str(row)] for row in compute.rows if str(row) in rows] or (
                list(rows.values()) if question.options or question.matrix_items else []
            )
            if wanted and question.type in {"numeric", "allocation"}:
                terms.extend(f"({label}.{row}.val or 0)" for row in wanted)
            else:
                terms.append(f"({label}.val or 0)")
        if terms:
            code = f"{name}.val = " + " + ".join(terms)
    else:
        source = compute.sources[0] if compute.sources else ""
        question = build.questions.get(source)
        label = build.labels.get(source)
        rows = build.rows.get(source, {})
        pairs = []
        for option in question.options if question else []:
            middle = range_midpoint(option.label)
            row = rows.get(str(option.code))
            if middle is not None and row:
                pairs.append(f"({label}.{row}, {middle:g})")
        if pairs:
            code = (
                f"for answer, middle in [{', '.join(pairs)}]:\n"
                f"    if answer:\n"
                f"        {name}.val = middle"
            )
            _note_warning(
                build,
                f"{variable.id}: check the midpoints worked out from the {source} answer ranges",
            )
        else:
            todos.append(f"no numeric ranges found in the answers of {source}")
    parent.append(ET.Comment(f" {variable.id}: {_comment(variable.definition)} "))
    if code:
        add_element(parent, "exec", code)
    else:
        parent.append(ET.Comment(f" PROGRAMMER TODO: compute {variable.id} "))
    node = add_element(
        parent,
        "float",
        label=name,
        optional="1",
        size="12",
        where="execute,survey,report",
    )
    add_element(node, "title", variable.label or variable.id)
    for note in todos:
        node.append(ET.Comment(f" PROGRAMMER TODO: {_comment(note)} "))
        _note_warning(build, f"{variable.id}: {note}")
    return CoverageItem(
        question_id=variable.id,
        label=name,
        element="float",
        status="partial" if todos or not code else "programmed",
        warnings=todos,
        punches=[],
    )


_AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*[kKmM]?")


def range_midpoint(label: str) -> float | None:
    """The middle of an answer range: "25-34" is 29.5, "$50,000 to $74,999" is 62499.5.

    "Under 25" is half of 25 and "65 or older" is 65; a label without a number has none.

    Args:
        label: Answer wording.

    Returns:
        The midpoint, or None.
    """
    numbers = []
    for found in _AMOUNT.findall(label):
        text = found.replace(",", "").strip()
        scale = {"k": 1_000, "m": 1_000_000}.get(text[-1].lower(), 1)
        numbers.append(float(text.rstrip("kKmM").strip()) * scale)
    if len(numbers) >= 2:
        return (numbers[0] + numbers[1]) / 2
    if len(numbers) == 1:
        if re.search(r"\b(?:under|less than|below|fewer than|up to)\b|<", label, re.I):
            return numbers[0] / 2
        return numbers[0]
    return None


def _rotation_places(document: Questionnaire, build: SurveyBuild) -> dict[str, tuple[int, int]]:
    """Map each rotated question to (rotation, section); rotations that cannot be built are dropped.

    A rotation is kept only when its sections are runs of consecutive questions that
    follow each other and sit in one module, so the blocks can wrap them.

    Args:
        document: Questionnaire.
        build: Shared build state, for warnings.

    Returns:
        Question id to (rotation index, section index).
    """
    order = {question.id: position for position, question in enumerate(document.questions)}
    places: dict[str, tuple[int, int]] = {}
    for which, rotation in enumerate(document.rotations):
        groups = [[q for q in group if q in order] for group in rotation.groups]
        groups = [sorted(group, key=order.__getitem__) for group in groups if group]
        flat = sorted((q for group in groups for q in group), key=order.__getitem__)
        positions = [order[q] for q in flat]
        modules = {(_module_for(document, q) or Module(id="", title="")).id for q in flat}
        contiguous = (
            positions == list(range(positions[0], positions[0] + len(positions)))
            if positions
            else False
        )
        sections_whole = all(
            [order[q] for q in group] == list(range(order[group[0]], order[group[0]] + len(group)))
            for group in groups
        )
        if (
            len(groups) < 2
            or not contiguous
            or not sections_whole
            or len(modules) > 1
            or any(q in places for q in flat)
        ):
            _note_warning(
                build,
                f"Section rotation not programmed (sections must be runs of consecutive questions): "
                f"{_comment(rotation.note or str(rotation.groups))[:160]}",
            )
            continue
        for group_index, group in enumerate(sorted(groups, key=lambda g: order[g[0]])):
            for question_id in group:
                places[question_id] = (which, group_index)
    return places


def _comment(text: str) -> str:
    """Text safe inside an XML comment."""
    return " ".join(text.split()).replace("--", "-")


def _note_warning(build: SurveyBuild, message: str) -> None:
    if message not in build.warnings:
        build.warnings.append(message)


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
