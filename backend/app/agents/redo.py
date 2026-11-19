"""Redo a chat request with a different action when the router chose the wrong one."""

# action -> (intent, text appended to the original request, label shown in chat)
REDO_ACTIONS: dict[str, tuple[str, str, str]] = {
    "import_exact": (
        "create_questionnaire",
        "Use this questionnaire exactly as written.",
        "Import the questionnaire as written",
    ),
    "draft_reference": (
        "create_questionnaire",
        "Use it as a reference and draft a new questionnaire.",
        "Draft a new questionnaire from it",
    ),
    "revise_questionnaire": ("revise_questionnaire", "", "Edit the current questionnaire"),
    "program_decipher": ("program_decipher", "", "Program it in Decipher"),
    "run_analysis": ("run_analysis", "", "Run an analysis"),
    "run_crosstab": ("run_crosstab", "", "Run tables"),
    "general_task": ("general_task", "", "Just answer"),
}


def redo_request(original: str, action: str) -> tuple[str, str, str]:
    """The intent, the request text, and the chat label for a redo.

    Args:
        original: The user's original request.
        action: Key of ``REDO_ACTIONS``.

    Returns:
        Intent, text, label.

    Raises:
        KeyError: Unknown action.
    """
    intent, extra, label = REDO_ACTIONS[action]
    text = f"{original.rstrip()} {extra}".strip() if extra else original
    return intent, text, label
