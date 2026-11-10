"""Decide when a chat turn should run the saved tab spec instead of authoring one."""

import re

_CROSSTAB = re.compile(r"\bcross[-\s]?tabs?\b|\bcrosstabs?\b", re.I)
_SPEC_POINTER = re.compile(
    r"\b(?:tabspecs?|tab specs?|tab plans?|banner books?|specs|the spec|this spec|the plan)\b",
    re.I,
)
_SPEC_NOUN = re.compile(r"\b(?:tabspecs?|tab specs?|tab plans?|banner books?)\b", re.I)
_RUN_VERB = re.compile(r"\b(?:run|execute|produce)\b", re.I)
_TABLES = re.compile(r"\btables\b", re.I)
_AUTHOR_VERB = re.compile(
    r"\b(?:build|create|draft|write|make|author|design|prepare|generate)\b",
    re.I,
)
_SPEC_PRODUCT = re.compile(
    r"\b(?:tabspecs?|tab[-\s]specs?|tab plans?|banner books?|"
    r"cross[-\s]?tab specs?|crosstab specs?)\b",
    re.I,
)
_BUILD_IT = re.compile(
    r"(?:(?:please|can you|could you|would you)\s+)*(?:just\s+)?"
    r"(?:okay|ok|yeah|yep|yes|sure|go ahead|do it|do that|"
    r"(?:build|create|make|generate|draft)(?:\s+(?:it|one|that|them|the spec|a spec))?)"
    r"\s*[.!?]*",
    re.I,
)
_AUTHORING = ("tab spec", "tabspec", "tab plan", "banner book")


def mentions_crosstab(text: str) -> bool:
    """Return whether the message asks for a crosstab.

    Args:
        text: User message.

    Returns:
        True for crosstab, cross-tab, and cross tab, including the plural forms.
    """
    return _CROSSTAB.search(text) is not None


def tab_spec_intent(
    text: str,
    *,
    has_tabspec: bool,
    names_row_and_banner: bool,
    offered_tabspec: bool = False,
) -> str | None:
    """Choose a tab-spec intent before a new plan is authored.

    Args:
        text: User message.
        has_tabspec: Whether the project already has a saved tab spec.
        names_row_and_banner: Whether the message names one row and one banner.
        offered_tabspec: Whether the previous reply asked the user to build a spec.

    Returns:
        ``run_saved_tabspec``, ``build_tabspec``, or None.
    """
    if _asks_to_author_spec(text):
        return "build_tabspec"
    if offered_tabspec and confirms_tabspec_build(text):
        return "build_tabspec"
    if _requests_saved_spec_run(
        text, has_tabspec=has_tabspec, names_row_and_banner=names_row_and_banner
    ):
        return "run_saved_tabspec"
    # Reason: "tab-specs" is the same request as "tab specs". A hyphen is not a new artifact.
    normalized = text.lower().replace("-", " ")
    if any(token in normalized for token in _AUTHORING):
        return "build_tabspec"
    return None


def assistant_offered_tabspec(text: str) -> bool:
    """Return whether the previous reply asked the user to build a tab spec.

    Args:
        text: Previous assistant message.

    Returns:
        True for the missing-spec reply.
    """
    return "no saved tab spec" in text.lower()


def confirms_tabspec_build(text: str) -> bool:
    """Return whether a short reply accepts the offer to build a tab spec.

    Args:
        text: User message.

    Returns:
        True for ``build it``, ``yes``, and ``can you build it``.
    """
    return _BUILD_IT.fullmatch(text.strip()) is not None


def _asks_to_author_spec(text: str) -> bool:
    """Return whether the user wants a tab spec written.

    Args:
        text: User message.

    Returns:
        True when the product is the spec. ``build the cross-tab spec`` and
        ``build tab-specs`` are true. ``generate cross-tabs based on the specs``
        stays false because the product is the tables.
    """
    # Reason: "cross-tab spec" contains both a crosstab word and a spec word.
    # The verb decides which of those the user wants created.
    if _AUTHOR_VERB.search(text) is None:
        return False
    return _SPEC_PRODUCT.search(text) is not None


def _requests_saved_spec_run(text: str, *, has_tabspec: bool, names_row_and_banner: bool) -> bool:
    """Return whether this turn should execute the saved spec.

    Args:
        text: User message.
        has_tabspec: Whether a tab spec is already saved.
        names_row_and_banner: Whether one row and one banner were named.

    Returns:
        True when the saved book should run. A named ``row by banner`` request
        stays a one-table job unless the message also points at the spec.
    """
    # Reason: "run the crosstabs from the tab spec" must not rebuild the plan,
    # and "specs by region" must not be read as a banner name.
    if _explicit_spec_execution(text):
        return True
    if names_row_and_banner:
        return False
    return has_tabspec and mentions_crosstab(text)


def _explicit_spec_execution(text: str) -> bool:
    """Return whether the user asked to run tables from a spec.

    Args:
        text: User message.

    Returns:
        True for a run against the spec. Authoring requests such as
        ``generate a tab spec`` stay false.
    """
    if not _SPEC_POINTER.search(text):
        return False
    if mentions_crosstab(text) or _TABLES.search(text):
        return True
    return _RUN_VERB.search(text) is not None and _SPEC_NOUN.search(text) is not None
