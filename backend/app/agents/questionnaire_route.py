"""Tell a questionnaire edit apart from a note or another specialist request."""

import re

_EDIT_VERB = re.compile(
    r"\b(add|insert|include|remove|delete|drop|change|update|edit|revise|rewrite|move|replace|rename)\b"
)
_EDIT_TARGET = re.compile(
    r"\b(question|questions|option|options|bracket|brackets|choice|choices|screener|wording|scale)\b|\b[sq]\d+\b"
)
_OTHER_WORK = (
    "codeframe",
    "crosstab",
    "cross-tab",
    "tab spec",
    "tabspec",
    "chart",
)


def is_question_edit(text: str) -> bool:
    """Return whether the message asks to add, change, or remove survey content.

    Args:
        text: Lower-cased user text.

    Returns:
        True for a question, option, or bracket edit that is not another specialist task.
    """
    if any(token in text for token in _OTHER_WORK):
        return False
    # Reason: method phrases such as "chi-square" belong to analysis even if they
    # mention a question. Importing here avoids a cycle with the intent module.
    from app.agents.intent import _method

    if _method(text):
        return False
    return bool(_EDIT_VERB.search(text) and _EDIT_TARGET.search(text))


def is_project_note(text: str) -> bool:
    """Return whether the message is a stored note rather than an instrument edit.

    Args:
        text: Lower-cased user text.

    Returns:
        True for codename memory and explicit notes.
    """
    return "codename" in text or "save a note" in text or text.startswith("note:")


def assistant_published_questionnaire(text: str) -> bool:
    """Return whether an assistant message saved or updated a questionnaire.

    Args:
        text: Assistant message.

    Returns:
        True when the previous turn published an instrument.
    """
    lowered = text.lower()
    if "saved your note" in lowered:
        return False
    if lowered.startswith("saved ") and "question" in lowered:
        return True
    return "updated the questionnaire" in lowered
