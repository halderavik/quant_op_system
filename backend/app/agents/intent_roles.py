"""Parse named analysis roles out of a chat message."""

import re
from typing import Any


def fill_roles(text: str, fields: dict[str, Any], missing: list[str], method: str) -> None:
    """Pull variable roles out of phrases like 'of purchase on trust and age'.

    The analysis planner chooses clustering and descriptive variables from the
    dataset profile. A regression, test, or correspondence request still has to
    name its dependent variable, predictors, or pair. This function records
    those hints and asks only when that named role is absent.

    Args:
        text: User text.
        fields: Contract fields to update.
        missing: Missing-role accumulator. Clustering and other profile-based
            methods leave variable choice to the planner.
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
    if planner_decides(text):
        # Reason: a chained, banded, or subgroup request needs the planner to read the
        # whole sentence; one method's keyword roles would ask for the wrong things.
        return
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


def planner_decides(text: str) -> bool:
    """Return whether the analysis planner, not keyword roles, should read this request.

    Args:
        text: User text.

    Returns:
        True when the request names more than one method or asks for a
        filter, banding, subgroup, or chained step.
    """
    from app.agents.intent import _METHODS
    from app.engines.analysis.compile import MULTI_STEP

    lowered = text.lower()
    named = sum(1 for _name, pattern in _METHODS if re.search(pattern, lowered))
    return named > 1 or bool(MULTI_STEP.search(text))


def _names(text: str) -> list[str]:
    """Split a list of variable names.

    Args:
        text: Comma or 'and' separated names.

    Returns:
        Names.
    """
    parts = re.split(r",|\band\b", text)
    return [part.strip() for part in parts if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part.strip())]
