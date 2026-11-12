"""Closed-end fraud checks. User-missing is not treated as a real answer."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.engines.cleaning_columns import ColumnFact, column_weights, prepare_columns, respondent_ids
from app.engines.cleaning_patterns import flag_batteries, flag_duplicates
from app.schemas.cleaning import CleaningRule

_SELECT = re.compile(r"\b(?:select|choose|pick|click)\s+(?:code\s+|option\s+)?(\d+)\b", re.I)
_PASS_LABEL = re.compile(r"\b(correct|pass|right answer)\b", re.I)
_MIN_NONRESPONSE = 5
_NONRESPONSE = 0.40
_ELIGIBLE_RATE = 0.80

RULES: dict[str, tuple[str, str, str]] = {
    "speeding": (
        "Speeding",
        "soft",
        "Duration is under one-third of the median positive length of interview.",
    ),
    "straightline": (
        "Straight-lining",
        "soft",
        "The same non-missing code is used on every item of a scale battery of at least four items.",
    ),
    "patterned_grid": (
        "Patterned grid",
        "soft",
        "A scale battery repeats a sequence or alternates two codes.",
    ),
    "checkbox_flat": (
        "Checkbox flatline",
        "soft",
        "Every punch in a checkbox battery of at least four items is yes, or every punch is no.",
    ),
    "exact_duplicate": (
        "Exact duplicate",
        "hard",
        "Closed-end answers match an earlier respondent. The later row is the duplicate.",
    ),
    "near_duplicate": (
        "Near duplicate",
        "soft",
        "At least 95 percent of 15 or more comparable closed-end answers match an earlier row.",
    ),
    "duplicate_id": (
        "Duplicate id",
        "hard",
        "The respondent id repeats an earlier row. The later row is removed.",
    ),
    "trap_fail": (
        "Attention check",
        "hard",
        "An attention, trap, red-herring, or quality-check item is not the labeled pass code.",
    ),
    "high_nonresponse": (
        "High item nonresponse",
        "soft",
        "More than 40 percent of eligible closed ends are blank or user-missing. A closed end "
        "is eligible when at least 80 percent of respondents answered it.",
    ),
    "age_range": (
        "Age out of range",
        "soft",
        "An age value is outside 0 to 120.",
    ),
}


@dataclass
class ClosedScan:
    """Flags and column roles the open-end pass and the scorer both need."""

    row_count: int
    flags: dict[int, list[tuple[str, str]]]
    rules: list[CleaningRule]
    skipped: list[str]
    respondent_ids: list[str]
    weights: list[float] | None
    weight_name: str | None
    text_columns: list[tuple[str, str]] = field(default_factory=list)


def scan_closed(frame: pd.DataFrame, variables: list[dict[str, Any]]) -> ClosedScan:
    """Run the closed-end checks on one data frame.

    Args:
        frame: Respondent rows.
        variables: SPSS dictionary. Labels and user-missing codes come from here.

    Returns:
        Flags by row, rule status, and the text columns left for the open-end pass.
    """
    facts = prepare_columns(frame, variables)
    flags: dict[int, list[tuple[str, str]]] = {index: [] for index in range(len(frame))}
    skipped: list[str] = []
    ran: dict[str, tuple[bool, str]] = {rule_id: (True, "") for rule_id in RULES}
    _speeding(facts, flags, ran, skipped)
    flag_batteries(facts, flags, ran, skipped)
    flag_duplicates(facts, flags, ran, skipped)
    _ids(facts, flags, ran, skipped)
    _attention(facts, flags, ran, skipped)
    _nonresponse(facts, flags, ran, skipped)
    _age(facts, flags, ran, skipped)
    return ClosedScan(
        row_count=len(frame),
        flags=flags,
        rules=[_rule(rule_id, ran[rule_id][0], ran[rule_id][1]) for rule_id in RULES],
        skipped=skipped,
        respondent_ids=respondent_ids(facts, len(frame)),
        weights=column_weights(facts),
        weight_name=next((item.name for item in facts if item.role == "weight"), None),
        text_columns=[(item.name, item.label) for item in facts if item.role == "text"],
    )


def _rule(rule_id: str, ran: bool, reason: str) -> CleaningRule:
    """Build one rule row.

    Args:
        rule_id: Stable id.
        ran: Whether the check had the columns it needs.
        reason: Why it was skipped.

    Returns:
        Rule record.
    """
    label, severity, definition = RULES[rule_id]
    return CleaningRule(
        id=rule_id,
        label=label,
        definition=definition,
        severity=severity,  # type: ignore[arg-type]
        ran=ran,
        skip_reason=reason,
    )


def _speeding(
    facts: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
    ran: dict[str, tuple[bool, str]],
    skipped: list[str],
) -> None:
    """Flag interviews under one-third of the median positive duration.

    Args:
        facts: Prepared columns.
        flags: Accumulator.
        ran: Rule status.
        skipped: Skip sentences.
    """
    column = next((item for item in facts if item.role == "duration"), None)
    if column is None:
        reason = "Speeding was not run because no duration variable was found."
        ran["speeding"] = (False, reason)
        skipped.append(reason)
        return
    positive = [float(value) for value in column.values if value is not None and float(value) > 0]
    if not positive:
        reason = "Speeding was not run because no positive duration was found."
        ran["speeding"] = (False, reason)
        skipped.append(reason)
        return
    median = statistics.median(positive)
    cutoff = median / 3
    for index, value in enumerate(column.values):
        if value is None:
            continue
        duration = float(value)
        if 0 < duration < cutoff:
            flags[index].append(
                (
                    "speeding",
                    f"{column.name} is {duration:g}, under one-third of the median {median:g}.",
                )
            )


def _ids(
    facts: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
    ran: dict[str, tuple[bool, str]],
    skipped: list[str],
) -> None:
    """Flag a repeated respondent id on the later row.

    Args:
        facts: Prepared columns.
        flags: Accumulator.
        ran: Rule status.
        skipped: Skip sentences.
    """
    column = next((item for item in facts if item.role == "id"), None)
    if column is None:
        reason = "No respondent id column was found."
        ran["duplicate_id"] = (False, reason)
        skipped.append(reason)
        return
    seen: dict[str, int] = {}
    for index, value in enumerate(column.values):
        if value is None:
            continue
        if value in seen:
            flags[index].append(
                ("duplicate_id", f"Respondent id {value} repeats row {seen[value]}.")
            )
        else:
            seen[value] = index


def _attention(
    facts: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
    ran: dict[str, tuple[bool, str]],
    skipped: list[str],
) -> None:
    """Flag a wrong answer on a labeled attention check.

    Args:
        facts: Prepared columns.
        flags: Accumulator.
        ran: Rule status.
        skipped: Skip sentences.
    """
    columns = [item for item in facts if item.role == "attention"]
    if not columns:
        reason = "No attention check was found."
        ran["trap_fail"] = (False, reason)
        skipped.append(reason)
        return
    usable = False
    for column in columns:
        passed = _pass_code(column)
        if passed is None:
            skipped.append(f"Attention variable {column.name} had no labeled pass code.")
            continue
        usable = True
        for index, value in enumerate(column.values):
            if value is None or value == passed:
                continue
            flags[index].append(
                ("trap_fail", f"{column.name} is {value}, not the pass code {passed}.")
            )
    if not usable:
        ran["trap_fail"] = (False, "No attention check had a labeled pass code.")


def _pass_code(column: ColumnFact) -> str | None:
    """Read the pass code from the label or from a value label marked correct.

    Args:
        column: Attention column.

    Returns:
        Pass code, or None when it is not explicit.
    """
    match = _SELECT.search(column.label)
    if match:
        return match.group(1)
    marked = [code for code, text in column.labels.items() if _PASS_LABEL.search(text)]
    if len(marked) == 1:
        return marked[0]
    return None


def _nonresponse(
    facts: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
    ran: dict[str, tuple[bool, str]],
    skipped: list[str],
) -> None:
    """Flag rows that skip more than 40 percent of eligible closed ends.

    A closed end is eligible when at least 80 percent of respondents answered it. Lower answer
    rates mean the question was routed, hidden, or looped, so a blank there is not a skip.

    Args:
        facts: Prepared columns.
        flags: Accumulator.
        ran: Rule status.
        skipped: Skip sentences.
    """
    columns = [
        item
        for item in facts
        if item.role in {"closed", "attention", "age"} and _answer_rate(item) >= _ELIGIBLE_RATE
    ]
    if len(columns) < _MIN_NONRESPONSE:
        reason = (
            "Item nonresponse was not run because fewer than 5 closed-end columns were "
            "answered by at least 80 percent of respondents."
        )
        ran["high_nonresponse"] = (False, reason)
        skipped.append(reason)
        return
    width = len(columns)
    for index in range(len(columns[0].values)):
        missing = sum(item.values[index] is None for item in columns)
        if missing / width > _NONRESPONSE:
            flags[index].append(
                ("high_nonresponse", f"{missing} of {width} closed ends are blank or user-missing.")
            )


def _answer_rate(column: ColumnFact) -> float:
    """Return the share of respondents with a non-missing value.

    Args:
        column: Prepared column.

    Returns:
        Share from 0 to 1. An empty column returns 0.
    """
    if not column.values:
        return 0.0
    return sum(value is not None for value in column.values) / len(column.values)


def _age(
    facts: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
    ran: dict[str, tuple[bool, str]],
    skipped: list[str],
) -> None:
    """Flag an age outside 0 to 120.

    Args:
        facts: Prepared columns.
        flags: Accumulator.
        ran: Rule status.
        skipped: Skip sentences.
    """
    column = next((item for item in facts if item.role == "age"), None)
    if column is None:
        reason = "No age variable was found."
        ran["age_range"] = (False, reason)
        skipped.append(reason)
        return
    for index, value in enumerate(column.values):
        if value is None:
            continue
        try:
            age = float(value)
        except ValueError:
            continue
        if age < 0 or age > 120:
            flags[index].append(("age_range", f"Age {age:g} is outside 0 to 120."))
