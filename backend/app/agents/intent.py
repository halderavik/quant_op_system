"""Rule-based task contracts. Computation never waits on a model to invent variables."""

import re
from typing import Any

from app.agents.questionnaire_route import is_project_note, is_question_edit
from app.schemas.project import TaskContract

_METHODS = [
    ("binary_logistic_regression", r"logistic"),
    ("ordinal_regression", r"ordinal"),
    ("linear_regression", r"linear regression|\bols\b"),
    ("key_driver", r"key[- ]driver"),
    ("chi_square", r"chi[- ]?square"),
    ("anova", r"\banova\b"),
    ("t_test", r"t-test|ttest"),
    ("correlation", r"correlation"),
    ("correspondence", r"correspondence"),
    ("clustering", r"cluster|segmentation"),
    ("reliability", r"cronbach|reliability"),
    ("discriminant", r"discriminant"),
    ("pca", r"\bpca\b|principal component"),
    ("efa", r"\befa\b|factor analysis"),
    ("descriptive", r"descriptive summary|describe the variables"),
]

_BLOCKED = re.compile(r"\b(maxdiff|max-diff|conjoint)\b", re.I)
_QUESTIONNAIRE = (
    "questionnaire",
    "instrument",
    "write a survey",
    "draft a survey",
    "design a survey",
    "create a survey",
    "study brief",
    "statement of work",
)
# Reason: these labels are how a pasted brief is structured. Analysis words such as
# "segmentation", "open-ended", and "conjoint" often appear inside that brief.
_BRIEF_MARKERS = (
    "audience:",
    "objectives:",
    "objective:",
    "eligibility:",
    "quotas:",
    "quota:",
    "sample:",
    "methodology:",
    "brands:",
    "brands,",
)
_DECIPHER_REQUEST = re.compile(
    r"\bdecipher\b|\bsurvey xml\b|\bprogram(?:me)? (?:this |the )?survey\b",
    re.I,
)
_BY = re.compile(
    r"\b(?P<row>[A-Za-z_][A-Za-z0-9_]*)\s+by\s+(?P<banner>[A-Za-z_][A-Za-z0-9_]*)\b",
    re.I,
)
_WEIGHT = re.compile(
    r"\bweight(?:ed)?\s+(?:by|using|with)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.I,
)


def build_contract(
    *,
    task_id: str,
    project_id: str,
    conversation_id: str,
    text: str,
    variable_names: list[str],
    has_dataset: bool,
    has_questionnaire: bool = False,
    continuing: bool = False,
) -> TaskContract:
    """Turn a user message into a task contract.

    Args:
        task_id: Task id.
        project_id: Project id.
        conversation_id: Conversation id.
        text: User message.
        variable_names: Names present on the active dataset.
        has_dataset: Whether a dataset is loaded.
        has_questionnaire: Whether the project already has a questionnaire.
        continuing: Whether the previous assistant turn published a questionnaire.

    Returns:
        Task contract. Missing roles are listed and not invented.
    """
    lowered = text.lower()
    fields: dict[str, Any] = {}
    missing: list[str] = []
    if _DECIPHER_REQUEST.search(lowered):
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "program_decipher",
            "decipher",
            fields,
            missing,
            ["decipher_survey"],
        )
    weight = _WEIGHT.search(text)
    if weight:
        fields["weight_variable"] = weight.group("name")
    questionnaire_intent = _questionnaire_intent(lowered)
    if questionnaire_intent:
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            questionnaire_intent,
            "questionnaire",
            fields,
            missing,
            ["questionnaire"],
        )
    if _BLOCKED.search(text):
        fields["method"] = (
            "maxdiff" if "maxdiff" in lowered or "max-diff" in lowered else "conjoint"
        )
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "run_analysis",
            "analysis",
            fields,
            missing,
            ["report"],
        )
    if any(
        phrase in lowered
        for phrase in (
            "propose a codeframe",
            "draft a codeframe",
            "inductive codeframe",
            "build a codeframe",
            "import this codeframe",
            "import a codeframe",
            "import the codeframe",
        )
    ):
        column = re.search(r"\b(?:column|variable)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
        respondent = re.search(r"\brespondent(?:\s+id|_id)?\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
        if column:
            fields["response_variable"] = column.group(1)
        if respondent:
            fields["respondent_id_variable"] = respondent.group(1)
        intent_name = "import_codeframe" if "import" in lowered else "propose_codeframe"
        if intent_name == "propose_codeframe":
            if not has_dataset:
                missing.append("dataset")
            if "response_variable" not in fields:
                missing.append("response_variable")
            if "respondent_id_variable" not in fields:
                missing.append("respondent_id_variable")
            _check_names(fields, variable_names, missing)
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            intent_name,
            "coding",
            fields,
            missing,
            ["codeframe"],
        )
    if any(
        token in lowered
        for token in ("codeframe", "open-end", "open end", "oe coding", "sentiment code")
    ):
        column = re.search(r"\b(?:column|variable)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
        respondent = re.search(r"\brespondent(?:\s+id|_id)?\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
        if column:
            fields["response_variable"] = column.group(1)
        if respondent:
            fields["respondent_id_variable"] = respondent.group(1)
        if not has_dataset:
            missing.append("dataset")
        _check_names(fields, variable_names, missing)
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "code_open_ends",
            "coding",
            fields,
            missing,
            ["coding"],
        )
    if any(token in lowered for token in ("tab spec", "tabspec", "tab plan", "banner book")):
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "build_tabspec",
            "tabspec",
            fields,
            missing,
            ["tabspec", "xlsx"],
        )
    method = _method(lowered)
    if method:
        fields["method"] = method
        _fill_roles(text, fields, missing, method)
        if not has_dataset:
            missing.append("dataset")
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "run_analysis",
            "analysis",
            fields,
            missing,
            ["analysis", "report"],
        )
    match = _BY.search(text)
    if match or "crosstab" in lowered or "cross-tab" in lowered:
        if match:
            fields["row_variable"] = match.group("row")
            fields["banner_variable"] = match.group("banner")
            _check_names(fields, variable_names, missing)
        else:
            missing.extend(["row_variable", "banner_variable"])
        if not has_dataset:
            missing.append("dataset")
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "run_crosstab",
            "crosstab",
            fields,
            missing,
            ["crosstab", "xlsx"],
        )
    if "chart" in lowered and "table" in lowered:
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "run_sandbox_task",
            "general",
            fields,
            missing,
            ["chart", "report"],
        )
    if has_questionnaire and continuing and not is_project_note(lowered):
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "revise_questionnaire",
            "questionnaire",
            fields,
            missing,
            ["questionnaire"],
        )
    return _contract(
        task_id,
        project_id,
        conversation_id,
        text,
        "general_task",
        "general",
        fields,
        missing,
        ["note"],
    )


def _questionnaire_intent(text: str) -> str | None:
    """Return a questionnaire intent when the message is a survey-design request.

    Args:
        text: Lower-cased user text.

    Returns:
        ``create_questionnaire``, ``revise_questionnaire``, or None. A pasted study
        brief is a draft request even when it mentions segmentation, open ends, or
        methods the instrument should not include.
    """
    if _is_study_brief(text):
        return "create_questionnaire"
    if is_question_edit(text) or text.startswith("change q"):
        return "revise_questionnaire"
    is_request = any(token in text for token in _QUESTIONNAIRE)
    if not is_request:
        return None
    if text.startswith("change "):
        return "revise_questionnaire"
    return "create_questionnaire"


def _is_study_brief(text: str) -> bool:
    """Return whether the message has the labeled sections of a study brief.

    Args:
        text: Lower-cased user text.

    Returns:
        True when at least two brief labels are present.
    """
    return sum(marker in text for marker in _BRIEF_MARKERS) >= 2


def _method(text: str) -> str | None:
    """Return the first registered method mentioned in the text.

    Args:
        text: Lower-cased user text.

    Returns:
        Method name or None.
    """
    for name, pattern in _METHODS:
        if re.search(pattern, text):
            return name
    return None


def _fill_roles(text: str, fields: dict[str, Any], missing: list[str], method: str) -> None:
    """Pull variable roles out of phrases like 'of purchase on trust and age'.

    Args:
        text: User text.
        fields: Contract fields to update.
        missing: Missing-role accumulator.
        method: Registered method name.
    """
    of_on = re.search(r"\bof\s+([A-Za-z_][A-Za-z0-9_]*)\s+on\s+([A-Za-z0-9_,\s]+)", text, re.I)
    if of_on:
        fields["dependent"] = of_on.group(1)
        fields["predictors"] = _names(of_on.group(2))
    dependent = re.search(r"\bdependent\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
    if dependent:
        fields["dependent"] = dependent.group(1)
    predictors = re.search(r"\bpredictors?\s+([A-Za-z0-9_,\s]+)", text, re.I)
    if predictors:
        fields["predictors"] = _names(predictors.group(1))
    grouped = re.search(r"\bby\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.I)
    if grouped and method in {"t_test", "anova"}:
        fields["group"] = grouped.group(1)
    pair = re.search(
        r"\bbetween\s+([A-Za-z_][A-Za-z0-9_]*)\s+and\s+([A-Za-z_][A-Za-z0-9_]*)",
        text,
        re.I,
    )
    if pair:
        fields["var_a"] = pair.group(1)
        fields["var_b"] = pair.group(2)
    variables = re.search(r"\bvariables?\s+([A-Za-z0-9_,\s]+)", text, re.I)
    if variables:
        fields["variables"] = _names(variables.group(1))
    needs_dependent = method in {
        "linear_regression",
        "binary_logistic_regression",
        "ordinal_regression",
        "key_driver",
        "t_test",
        "anova",
        "discriminant",
    }
    if needs_dependent and "dependent" not in fields:
        missing.append("dependent")
    if method in {
        "linear_regression",
        "binary_logistic_regression",
        "ordinal_regression",
        "key_driver",
        "discriminant",
    }:
        if not fields.get("predictors"):
            missing.append("predictors")
    if method in {"t_test", "anova"} and "group" not in fields:
        missing.append("group")
    if method in {"chi_square", "correspondence"} and "var_a" not in fields:
        missing.extend(["var_a", "var_b"])
    if method in {
        "correlation",
        "pca",
        "efa",
        "clustering",
        "reliability",
        "descriptive",
    } and not fields.get("variables"):
        missing.append("variables")


def _names(text: str) -> list[str]:
    """Split a list of variable names.

    Args:
        text: Comma or 'and' separated names.

    Returns:
        Names.
    """
    parts = re.split(r",|\band\b", text)
    return [part.strip() for part in parts if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part.strip())]


def _check_names(fields: dict[str, Any], variable_names: list[str], missing: list[str]) -> None:
    """Mark variables that are not in the dataset.

    Args:
        fields: Parsed fields.
        variable_names: Dataset names.
        missing: Missing accumulator.
    """
    if not variable_names:
        return
    lookup = {name.lower(): name for name in variable_names}
    for key in (
        "row_variable",
        "banner_variable",
        "weight_variable",
        "response_variable",
        "respondent_id_variable",
    ):
        if key not in fields:
            continue
        actual = lookup.get(str(fields[key]).lower())
        if actual is None:
            missing.append(key)
        else:
            fields[key] = actual


def _contract(
    task_id: str,
    project_id: str,
    conversation_id: str,
    text: str,
    intent: str,
    specialist: str,
    fields: dict[str, Any],
    missing: list[str],
    outputs: list[str],
) -> TaskContract:
    """Assemble a contract.

    Args:
        task_id: Task id.
        project_id: Project id.
        conversation_id: Conversation id.
        text: User text.
        intent: Intent name.
        specialist: Specialist name.
        fields: Provided fields.
        missing: Missing fields.
        outputs: Expected outputs.

    Returns:
        Task contract.
    """
    return TaskContract(
        task_id=task_id,
        project_id=project_id,
        conversation_id=conversation_id,
        intent=intent,
        specialist=specialist,
        user_request=text,
        provided_fields=fields,
        missing_required=missing,
        defaults_used={"percent_type": "column"} if intent == "run_crosstab" else {},
        expected_outputs=outputs,
        acceptance_checks=["schema", "export_exists"] if "xlsx" in outputs else ["schema"],
        status="clarification_needed" if missing else "running",
    )
