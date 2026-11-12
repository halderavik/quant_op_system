"""Fill a contract for an intent the router already chose."""

import re
from typing import Any

from app.schemas.project import TaskContract

_COLUMN = re.compile(r"\b(?:column|variable)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_RESPONDENT = re.compile(r"\brespondent(?:\s+id|_id)?\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)

_META: dict[str, tuple[str, list[str]]] = {
    "program_decipher": ("decipher", ["decipher_survey"]),
    "buy_sample": ("sample", ["sample_purchase"]),
    "generate_synthetic": ("synthetic", ["synthetic_data", "dataset"]),
    "create_questionnaire": ("questionnaire", ["questionnaire"]),
    "revise_questionnaire": ("questionnaire", ["questionnaire"]),
    "run_analysis": ("analysis", ["analysis", "report"]),
    "propose_codeframe": ("coding", ["codeframe"]),
    "import_codeframe": ("coding", ["codeframe"]),
    "code_open_ends": ("coding", ["coding"]),
    "clean_data": ("cleaning", ["cleaning", "xlsx"]),
    "apply_cleaning": ("cleaning", ["dataset"]),
    "run_saved_tabspec": ("crosstab", ["crosstab", "xlsx"]),
    "build_tabspec": ("tabspec", ["tabspec", "xlsx"]),
    "run_crosstab": ("crosstab", ["crosstab", "xlsx"]),
    "run_sandbox_task": ("general", ["chart", "report"]),
    "general_task": ("general", ["note"]),
}


def apply_chosen_intent(
    *,
    task_id: str,
    project_id: str,
    conversation_id: str,
    text: str,
    intent: str,
    fields: dict[str, Any],
    missing: list[str],
    variable_names: list[str],
    has_dataset: bool,
    route_reason: str,
    has_cleaning: bool = False,
) -> TaskContract:
    """Parse fields for one chosen intent and skip the keyword cascade.

    Args:
        task_id: Task id.
        project_id: Project id.
        conversation_id: Conversation id.
        text: User text, including a prepended analysis request when that applies.
        intent: Intent the router chose.
        fields: Fields already parsed, such as a weight variable.
        missing: Missing-role accumulator.
        variable_names: Names on the active dataset.
        has_dataset: Whether a dataset is loaded.
        route_reason: Why this intent was chosen.
        has_cleaning: Whether a fraud recommendation is already saved.

    Returns:
        Task contract for that intent.
    """
    # Reason: importing here keeps the keyword module and this filler from a cycle.
    from app.agents.intent import _BLOCKED, _BY, _check_names, _method
    from app.agents.intent_roles import fill_roles

    specialist, outputs = _META.get(intent, ("general", ["note"]))
    if intent not in _META:
        intent = "general_task"
    if intent == "run_analysis" and _BLOCKED.search(text):
        lowered = text.lower()
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
            route_reason,
        )
    if intent in {"propose_codeframe", "import_codeframe", "code_open_ends"}:
        _coding_fields(text, fields)
        if intent != "import_codeframe":
            if not has_dataset:
                missing.append("dataset")
            if intent == "propose_codeframe":
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
            intent,
            specialist,
            fields,
            missing,
            outputs,
            route_reason,
        )
    if intent in {"clean_data", "apply_cleaning"}:
        if not has_dataset:
            missing.append("dataset")
        if intent == "apply_cleaning" and not has_cleaning:
            missing.append("cleaning_recommendation")
        return _contract(
            task_id,
            project_id,
            conversation_id,
            text,
            intent,
            specialist,
            fields,
            missing,
            outputs,
            route_reason,
        )
    if intent == "run_analysis":
        method = _method(text.lower())
        if method:
            fields["method"] = method
            fill_roles(text, fields, missing, method)
        if not has_dataset:
            missing.append("dataset")
    elif intent == "run_crosstab":
        match = _BY.search(text)
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
        intent,
        specialist,
        fields,
        missing,
        outputs,
        route_reason,
    )


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
    route_reason: str = "",
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
        route_reason: Why the router chose this intent. Empty for the keyword path.

    Returns:
        Task contract.
    """
    defaults: dict[str, Any] = {"percent_type": "column"} if intent == "run_crosstab" else {}
    if route_reason:
        defaults["route_reason"] = route_reason
    return TaskContract(
        task_id=task_id,
        project_id=project_id,
        conversation_id=conversation_id,
        intent=intent,
        specialist=specialist,
        user_request=text,
        provided_fields=fields,
        missing_required=missing,
        defaults_used=defaults,
        expected_outputs=outputs,
        acceptance_checks=["schema", "export_exists"] if "xlsx" in outputs else ["schema"],
        status="clarification_needed" if missing else "running",
    )


def _coding_fields(text: str, fields: dict[str, Any]) -> None:
    """Record a response column and respondent id when the message names them.

    Args:
        text: User text.
        fields: Contract fields to update.
    """
    column = _COLUMN.search(text)
    respondent = _RESPONDENT.search(text)
    if column:
        fields["response_variable"] = column.group(1)
    if respondent:
        fields["respondent_id_variable"] = respondent.group(1)
