"""Rule-based task contracts. Computation never waits on a model to invent variables."""

import re
from typing import Any

from app.agents.intent_roles import fill_roles
from app.agents.questionnaire_route import is_project_note, is_question_edit
from app.agents.spec_run_intent import mentions_crosstab, tab_spec_intent
from app.schemas.project import TaskContract

# Reason: "satisfaction by gender" is a crosstab, but the same shape with a named
# procedure is an analysis the registry may not implement.
_ADHOC_ANALYSIS = re.compile(
    r"mann.{0,3}whitney|kruskal|wilcoxon|friedman|kolmogorov|shapiro|"
    r"non-?parametric|\bturf\b|van westendorp|price sensitivity|"
    r"penalty analysis|gap analysis|mixed model|multilevel|"
    r"\bsurvival\b|\bhazard\b|proportion test|\bz[- ]test\b|"
    r"compare (?:the )?means|mean difference|"
    r"(?:build|create) an index|composite (?:score|index)|"
    r"run an analysis|statistical analysis|significance test",
    re.I,
)
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
    ("clustering", r"cluster|segmentation|\bpam\b|gower|medoid|hierarchical|\bdbscan\b"),
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
    has_tabspec: bool = False,
    offered_tabspec: bool = False,
    analysis_followup: bool = False,
    prior_analysis_request: str = "",
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
        has_tabspec: Whether the project already has a saved tab spec.
        offered_tabspec: Whether the previous reply asked the user to build a spec.
        analysis_followup: Whether the previous analysis turn asked a question.
        prior_analysis_request: The analysis request that question belongs to.

    Returns:
        Task contract. Missing roles are listed and not invented.
    """
    if analysis_followup and prior_analysis_request.strip() and not _leaves_analysis(text):
        text = prior_analysis_request.strip() + "\n\nFollow-up instruction: " + text.strip()
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
    spec_intent = tab_spec_intent(
        text,
        has_tabspec=has_tabspec,
        names_row_and_banner=_BY.search(text) is not None,
        offered_tabspec=offered_tabspec,
    )
    if spec_intent:
        running_book = spec_intent == "run_saved_tabspec"
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            spec_intent,
            "crosstab" if running_book else "tabspec",
            fields,
            missing,
            ["crosstab", "xlsx"] if running_book else ["tabspec", "xlsx"],
        )
    method = _method(lowered)
    if method:
        fields["method"] = method
        fill_roles(text, fields, missing, method)
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
    if _ADHOC_ANALYSIS.search(text):
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
    if match or mentions_crosstab(text):
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


def _leaves_analysis(text: str) -> bool:
    """Return whether a follow-up starts a different specialist task.

    Args:
        text: The new user message, before it is joined to the prior analysis.

    Returns:
        True for a questionnaire, table, coding, or Decipher request.
    """
    lowered = text.lower()
    if _DECIPHER_REQUEST.search(lowered) or _questionnaire_intent(lowered):
        return True
    if any(
        token in lowered for token in ("codeframe", "open-end", "open end", "tab spec", "tabspec")
    ):
        return True
    return mentions_crosstab(lowered) or _BY.search(text) is not None


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
