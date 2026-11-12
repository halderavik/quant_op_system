"""Rule-based task contracts. Computation never waits on a model to invent variables."""

import re
from typing import Any

from app.agents.intent_fields import _contract, apply_chosen_intent
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
_SYNTHETIC_REQUEST = re.compile(
    r"\b(?:synthetic|simulated|dummy|fake)\s+(?:survey\s+)?"
    r"(?:data|dataset|respondents?|responses?|sample|completes?|interviews?)\b|"
    r"\bsimulate\s+(?:the\s+)?(?:survey|respondents?|responses?|data)\b",
    re.I,
)
_DECIPHER_REQUEST = re.compile(
    r"\bdecipher\b|\bsurvey xml\b|\bprogram(?:me)? (?:this |the )?survey\b",
    re.I,
)
_SAMPLE_REQUEST = re.compile(
    r"\bprolific\b|"
    r"\b(?:buy|recruit|purchase)\b.{0,40}\b(?:respondents?|participants?|sample)\b|"
    r"\bfield(?:ing)? (?:the |this )?survey\b|"
    r"\bsample (?:cost|price)\b|"
    r"\bpanel sample\b|"
    r"\brecruitment quota\b|"
    r"\baudience cost\b",
    re.I,
)
_CLEANING_REQUEST = re.compile(
    r"\bfraud|\bfraudulent\b|"
    r"data clean|clean the data|clean this data|cleaning the data|"
    r"\bdata quality\b|\bquality check\b|\bquality control\b|"
    r"\bqc the\b|\bqc this\b|"
    r"\bspeeder|\bstraight-?lin|\bflat-?lin|"
    r"\bgibberish\b|"
    r"\bbad respondents?\b|\bduplicate respondents?\b|"
    r"\battention check\b|\bred herring\b|"
    r"\binattentive\b|\bsatisfic|"
    r"who should we remove|respondents to remove|identify fraud",
    re.I,
)
_APPLY_CLEANING = re.compile(
    r"\bapply (?:the |those |these )?(?:cleaning|removals?|flags|recommendation)\b|"
    r"\bdrop the (?:flagged|fraud|speeders|recommended)\b|"
    r"\bremove the (?:flagged|fraud)(?: respondents| cases| rows)?\b|"
    r"\bdrop (?:those|these) (?:rows|respondents|cases)\b",
    re.I,
)
_APPLY_WORD = re.compile(r"\b(?:apply|drop|remove)\b", re.I)
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
    chosen_intent: str | None = None,
    route_reason: str = "",
    has_cleaning: bool = False,
    cleaning_followup: bool = False,
    sample_followup: bool = False,
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
        chosen_intent: Intent already chosen by the router. The keyword order does not override it.
        route_reason: Why that intent was chosen.
        has_cleaning: Whether a fraud recommendation is already saved.
        cleaning_followup: Whether the previous turn was a fraud recommendation.
        sample_followup: Whether the previous turn priced or launched a sample.

    Returns:
        Task contract. Missing roles are listed and not invented.
    """
    if chosen_intent == "run_analysis" and analysis_followup and prior_analysis_request.strip():
        text = prior_analysis_request.strip() + "\n\nFollow-up instruction: " + text.strip()
    elif (
        chosen_intent is None
        and analysis_followup
        and prior_analysis_request.strip()
        and not _leaves_analysis(text)
    ):
        text = prior_analysis_request.strip() + "\n\nFollow-up instruction: " + text.strip()
    lowered = text.lower()
    fields: dict[str, Any] = {}
    missing: list[str] = []
    if chosen_intent:
        weight = _WEIGHT.search(text)
        if weight:
            fields["weight_variable"] = weight.group("name")
        return apply_chosen_intent(
            task_id=task_id,
            project_id=project_id,
            conversation_id=conversation_id,
            text=text,
            intent=chosen_intent,
            fields=fields,
            missing=missing,
            variable_names=variable_names,
            has_dataset=has_dataset,
            route_reason=route_reason,
            has_cleaning=has_cleaning,
        )
    if _SYNTHETIC_REQUEST.search(text) and not _is_study_brief(lowered):
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "generate_synthetic",
            "synthetic",
            fields,
            missing,
            ["synthetic_data", "dataset"],
        )
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
    if _SAMPLE_REQUEST.search(text) and not _is_study_brief(lowered):
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "buy_sample",
            "sample",
            fields,
            missing,
            ["sample_purchase"],
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
    if sample_followup and not _leaves_sample(text):
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            "buy_sample",
            "sample",
            fields,
            missing,
            ["sample_purchase"],
        )
    # Reason: "check the open ends for fraud" must not fall through into open-end coding.
    if cleaning_followup and not _leaves_cleaning(text):
        follow_intent = (
            "apply_cleaning"
            if _APPLY_CLEANING.search(text) or _APPLY_WORD.search(text)
            else "clean_data"
        )
        return _finish_cleaning(
            task_id,
            project_id,
            conversation_id,
            text,
            follow_intent,
            fields,
            has_dataset,
            has_cleaning,
        )
    cleaning_intent = None if _leaves_cleaning(text) else _cleaning_route(text)
    if cleaning_intent:
        return _finish_cleaning(
            task_id,
            project_id,
            conversation_id,
            text,
            cleaning_intent,
            fields,
            has_dataset,
            has_cleaning,
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


def product_lock(text: str) -> str | None:
    """Return an intent that must not wait on the route model.

    Args:
        text: User message.

    Returns:
        ``program_decipher``, ``create_questionnaire`` for a pasted study brief,
        ``run_analysis`` for MaxDiff or conjoint, or None. A brief that mentions
        MaxDiff still drafts a questionnaire.
    """
    lowered = text.lower()
    # Reason: "synthetic data from the Decipher survey" must not lock to programming.
    if _SYNTHETIC_REQUEST.search(text) and not _is_study_brief(lowered):
        return "generate_synthetic"
    if _DECIPHER_REQUEST.search(lowered):
        return "program_decipher"
    if _is_study_brief(lowered):
        return "create_questionnaire"
    if _BLOCKED.search(text):
        return "run_analysis"
    return None


def _sample_request(text: str) -> bool:
    """Return whether the message is asking to price or field a panel sample.

    Args:
        text: User message.

    Returns:
        True for a Prolific or panel-sample request that is not a study brief.
    """
    return _SAMPLE_REQUEST.search(text) is not None and not _is_study_brief(text.lower())


def _leaves_sample(text: str) -> bool:
    """Return whether a sample follow-up starts another specialist.

    Args:
        text: User message.

    Returns:
        True for a questionnaire, Decipher, analysis, table, coding, or cleaning request.
    """
    lowered = text.lower()
    if _DECIPHER_REQUEST.search(lowered) or _questionnaire_intent(lowered) or _cleaning_route(text):
        return True
    if _method(lowered) or _ADHOC_ANALYSIS.search(text) or _BLOCKED.search(text):
        return True
    if any(
        token in lowered
        for token in ("codeframe", "open-end", "open end", "tab spec", "tabspec", "tab plan")
    ):
        return True
    return mentions_crosstab(lowered) or _BY.search(text) is not None


def _leaves_analysis(text: str) -> bool:
    """Return whether a follow-up starts a different specialist task.

    Args:
        text: The new user message, before it is joined to the prior analysis.

    Returns:
        True for a questionnaire, table, coding, or Decipher request.
    """
    lowered = text.lower()
    if _DECIPHER_REQUEST.search(lowered) or _questionnaire_intent(lowered) or _sample_request(text):
        return True
    if _cleaning_route(text):
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


def _cleaning_route(text: str) -> str | None:
    """Return a cleaning intent when the message asks for fraud review or an apply.

    Args:
        text: User message.

    Returns:
        ``apply_cleaning``, ``clean_data``, or None. Coding and statistics are not matched here.
    """
    if _APPLY_CLEANING.search(text):
        return "apply_cleaning"
    if _CLEANING_REQUEST.search(text):
        return "clean_data"
    return None


def _leaves_cleaning(text: str) -> bool:
    """Return whether the message starts a specialist other than data cleaning.

    Args:
        text: User message.

    Returns:
        True for a questionnaire, Decipher program, codeframe, statistic, or table.
    """
    lowered = text.lower()
    if _DECIPHER_REQUEST.search(lowered) or _questionnaire_intent(lowered) or _sample_request(text):
        return True
    if any(
        token in lowered for token in ("codeframe", "code the open", "oe coding", "sentiment code")
    ):
        return True
    if _method(lowered) or _ADHOC_ANALYSIS.search(text):
        return True
    if mentions_crosstab(lowered) or _BY.search(text) is not None:
        return True
    return "tab spec" in lowered or "tabspec" in lowered or "tab plan" in lowered


def _finish_cleaning(
    task_id: str,
    project_id: str,
    conversation_id: str,
    text: str,
    intent_name: str,
    fields: dict[str, Any],
    has_dataset: bool,
    has_cleaning: bool,
) -> TaskContract:
    """Build a cleaning contract and list a missing dataset or recommendation.

    Args:
        task_id: Task id.
        project_id: Project id.
        conversation_id: Conversation id.
        text: User message.
        intent_name: ``clean_data`` or ``apply_cleaning``.
        fields: Parsed fields.
        has_dataset: Whether a dataset is loaded.
        has_cleaning: Whether a fraud recommendation is already saved.

    Returns:
        Task contract.
    """
    missing: list[str] = []
    if not has_dataset:
        missing.append("dataset")
    if intent_name == "apply_cleaning" and not has_cleaning:
        missing.append("cleaning_recommendation")
    outputs = ["dataset"] if intent_name == "apply_cleaning" else ["cleaning", "xlsx"]
    return _contract(
        task_id,
        project_id,
        conversation_id,
        text,
        intent_name,
        "cleaning",
        fields,
        missing,
        outputs,
    )


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
