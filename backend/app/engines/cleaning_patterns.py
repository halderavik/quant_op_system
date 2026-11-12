"""Straight-lining, patterned grids, checkbox flatlines, and duplicate respondents."""

from __future__ import annotations

import re

import numpy as np

from app.engines.cleaning_columns import ColumnFact

_STEM = re.compile(r"^(?P<stem>[A-Za-z][A-Za-z0-9]*?)(?:_|r)(?P<idx>\d+)$")
_YES = re.compile(r"\byes\b|selected|checked", re.I)
_NO = re.compile(r"\bno\b|not selected|unchecked", re.I)
_MIN_CLOSED = 8
_MIN_NEAR = 15


def flag_batteries(
    facts: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
    ran: dict[str, tuple[bool, str]],
    skipped: list[str],
) -> None:
    """Flag straight-lining, patterns, and checkbox flatlines.

    Args:
        facts: Prepared columns.
        flags: Accumulator.
        ran: Rule status.
        skipped: Skip sentences.
    """
    grouped: dict[str, list[ColumnFact]] = {}
    for item in facts:
        if item.role not in {"closed", "attention", "age"}:
            continue
        match = _STEM.match(item.name)
        if match:
            grouped.setdefault(match.group("stem"), []).append(item)
    scales: list[tuple[str, list[ColumnFact]]] = []
    checks: list[tuple[str, list[ColumnFact]]] = []
    for stem, members in grouped.items():
        ordered = sorted(members, key=_item_index)
        if len(ordered) < 4:
            continue
        keys = {_label_key(item.labels) for item in ordered}
        if len(keys) != 1 or not ordered[0].labels:
            continue
        if len(ordered[0].labels) >= 3:
            scales.append((stem, ordered))
        else:
            checks.append((stem, ordered))
    if not scales:
        reason = "No scale battery of at least four items was found."
        ran["straightline"] = (False, reason)
        ran["patterned_grid"] = (False, reason)
        skipped.append(reason)
    else:
        for stem, members in scales:
            _scale_battery(stem, members, flags)
    if not checks:
        reason = "No checkbox battery of at least four items was found."
        ran["checkbox_flat"] = (False, reason)
        skipped.append(reason)
    else:
        for stem, members in checks:
            _checkbox_battery(stem, members, flags)


def flag_duplicates(
    facts: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
    ran: dict[str, tuple[bool, str]],
    skipped: list[str],
) -> None:
    """Flag exact copies and 95 percent matches on the closed-end vector.

    Args:
        facts: Prepared columns.
        flags: Accumulator.
        ran: Rule status.
        skipped: Skip sentences.
    """
    columns = [item for item in facts if item.role in {"closed", "attention", "age"}]
    if len(columns) < _MIN_CLOSED:
        reason = "Duplicate comparison was not run because fewer than 8 closed-end columns are available."
        ran["exact_duplicate"] = (False, reason)
        ran["near_duplicate"] = (False, reason)
        skipped.append(reason)
        return
    vectors = [[item.values[index] for item in columns] for index in range(len(columns[0].values))]
    seen: dict[tuple[str | None, ...], int] = {}
    exact: set[int] = set()
    for index, vector in enumerate(vectors):
        key = tuple(vector)
        if not any(value is not None for value in key):
            continue
        if key in seen:
            exact.add(index)
            flags[index].append(("exact_duplicate", f"Closed-end answers match row {seen[key]}."))
        else:
            seen[key] = index
    if len(columns) < _MIN_NEAR:
        reason = "Near-duplicate comparison needs at least 15 closed-end columns."
        ran["near_duplicate"] = (False, reason)
        skipped.append(reason)
        return
    _near_duplicates(vectors, exact, flags)


def _item_index(item: ColumnFact) -> int:
    """Return the numeric suffix used to order a battery.

    Args:
        item: Column in a stem group.

    Returns:
        Item index, or zero when the name does not match.
    """
    match = _STEM.match(item.name)
    if match is None:
        return 0
    return int(match.group("idx"))


def _label_key(labels: dict[str, str]) -> tuple[str, ...]:
    """Return the label codes that define a shared scale.

    Args:
        labels: Value labels.

    Returns:
        Sorted codes.
    """
    return tuple(sorted(labels))


def _scale_battery(
    stem: str,
    members: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
) -> None:
    """Flag one scale battery.

    Args:
        stem: Shared name stem.
        members: Items in code order.
        flags: Accumulator.
    """
    for index in range(len(members[0].values)):
        values = [item.values[index] for item in members]
        if any(value is None for value in values):
            continue
        if len(set(values)) == 1:
            flags[index].append(
                ("straightline", f"Battery {stem} is code {values[0]} on every item.")
            )
            continue
        if _patterned(values):
            flags[index].append(
                ("patterned_grid", f"Battery {stem} repeats a sequence or alternates.")
            )


def _patterned(values: list[str | None]) -> bool:
    """Return whether a fully answered battery is a sequence or an alternation.

    Args:
        values: Non-missing codes.

    Returns:
        True when the series repeats with a period of at least two.
    """
    if len(values) >= 4 and values[0] != values[1]:
        if all(values[index] == values[index % 2] for index in range(len(values))):
            return True
    width = len(values)
    for period in range(2, width // 2 + 1):
        if width < period * 2:
            continue
        unit = values[:period]
        if len(set(unit)) < 2:
            continue
        if all(values[index] == unit[index % period] for index in range(width)):
            return True
    return False


def _checkbox_battery(
    stem: str,
    members: list[ColumnFact],
    flags: dict[int, list[tuple[str, str]]],
) -> None:
    """Flag an all-yes or all-no checkbox battery.

    Args:
        stem: Shared name stem.
        members: Punch columns.
        flags: Accumulator.
    """
    yes, no = _poles(members[0].labels)
    if yes is None and no is None:
        return
    for index in range(len(members[0].values)):
        values = [item.values[index] for item in members]
        if any(value is None for value in values):
            continue
        if yes is not None and all(value == yes for value in values):
            flags[index].append(("checkbox_flat", f"Battery {stem} is yes on every punch."))
        elif no is not None and all(value == no for value in values):
            flags[index].append(("checkbox_flat", f"Battery {stem} is no on every punch."))


def _poles(labels: dict[str, str]) -> tuple[str | None, str | None]:
    """Find the yes and no codes on a checkbox battery.

    Args:
        labels: Shared value labels.

    Returns:
        Yes code and no code. Either may be missing.
    """
    yes = None
    no = None
    for code, label in labels.items():
        if _YES.search(label):
            yes = code
        if _NO.search(label):
            no = code
    if yes is None and no is None and set(labels) <= {"0", "1"}:
        return "1", "0"
    return yes, no


def _near_duplicates(
    vectors: list[list[str | None]],
    exact: set[int],
    flags: dict[int, list[tuple[str, str]]],
) -> None:
    """Flag later rows that agree with an earlier row on 95 percent of shared answers.

    Args:
        vectors: Closed-end tokens.
        exact: Rows already removed as exact copies.
        flags: Accumulator.
    """
    # Reason: exact copies are already a hard fail. Near-duplicate is the softer remainder.
    tokens = sorted({value for vector in vectors for value in vector if value is not None})
    lookup = {token: position + 1 for position, token in enumerate(tokens)}
    matrix = np.zeros((len(vectors), len(vectors[0])), dtype=np.int32)
    for row_index, vector in enumerate(vectors):
        for column_index, value in enumerate(vector):
            if value is not None:
                matrix[row_index, column_index] = lookup[value]
    for index in range(1, len(vectors)):
        if index in exact:
            continue
        current = matrix[index]
        previous = matrix[:index]
        both = (previous != 0) & (current != 0)
        comparable = both.sum(axis=1)
        agree = ((previous == current) & both).sum(axis=1)
        matched = (comparable >= _MIN_NEAR) & (agree * 20 >= comparable * 19)
        if not np.any(matched):
            continue
        earlier = int(np.flatnonzero(matched)[0])
        flags[index].append(("near_duplicate", f"Closed-end answers closely match row {earlier}."))
