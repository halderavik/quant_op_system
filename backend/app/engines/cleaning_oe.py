"""Open-end fraud checks. The model only sees text these rules leave undecided."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from app.schemas.cleaning import OpenEndFinding

_PLACEHOLDERS = {
    "na",
    "n a",
    "none",
    "idk",
    "dk",
    "dont know",
    "nothing",
    "no comment",
    "nil",
    "xxx",
    "test",
    "nope",
    "blank",
    "not applicable",
    "no answer",
    "dunno",
}
_WHY = re.compile(r"\b(why|explain|describe|tell us|elaborate|reason)\b", re.I)
_WORD = re.compile(r"[A-Za-z0-9']+")
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_PREVIEW = 160
_DUPLICATE_LENGTH = 25
_REPEAT_LENGTH = 15


@dataclass
class PendingVerbatim:
    """One verbatim the deterministic rules did not decide."""

    surrogate_id: str
    source_row_id: int
    variable: str
    variable_label: str
    text: str


@dataclass
class OpenScan:
    """Open-end flags, exception rows, and verbatims still undecided."""

    flags: dict[int, list[tuple[str, str]]] = field(default_factory=dict)
    findings: list[OpenEndFinding] = field(default_factory=list)
    pending: list[PendingVerbatim] = field(default_factory=list)
    skip_reason: str = ""


def scan_open_ends(frame: pd.DataFrame, text_columns: list[tuple[str, str]]) -> OpenScan:
    """Classify every text cell that the dictionary marked as an open end.

    Args:
        frame: Respondent rows.
        text_columns: Variable name and label pairs.

    Returns:
        Flags, findings, and undecided verbatims. Blank cells are recorded and do not flag.
    """
    if not text_columns:
        return OpenScan(skip_reason="No open-end columns were found.")
    scan = OpenScan()
    row_count = len(frame)
    normalized: list[tuple[int, str, str, str]] = []
    pending_index = 0
    for name, label in text_columns:
        if name not in frame.columns:
            continue
        why = _WHY.search(label) is not None
        for index, raw in enumerate(frame[name].tolist()):
            text = "" if raw is None or _is_na(raw) else str(raw).strip()
            kind = _classify(text, why)
            if kind == "blank":
                continue
            if kind == "pending":
                pending_index += 1
                scan.pending.append(
                    PendingVerbatim(
                        surrogate_id=f"v{pending_index:04d}",
                        source_row_id=index,
                        variable=name,
                        variable_label=label,
                        text=text,
                    )
                )
                normalized.append((index, name, text, _compact(text)))
                continue
            rule_id, detail, affects = _decided_detail(kind, name, why)
            if affects:
                scan.flags.setdefault(index, []).append((rule_id, detail))
            if rule_id:
                scan.findings.append(_finding(index, name, text, rule_id, detail))
            normalized.append((index, name, text, _compact(text)))
    _shared_text(normalized, row_count, scan)
    _repeated_text(normalized, scan)
    return scan


def _is_na(value: object) -> bool:
    """Return whether pandas considers the cell missing.

    Args:
        value: Raw cell.

    Returns:
        True for NaN. Other objects are not missing.
    """
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _classify(text: str, why: bool) -> str:
    """Return the deterministic class for one verbatim.

    Args:
        text: Stripped response.
        why: Whether the question asks for an explanation.

    Returns:
        ``blank``, ``gibberish``, ``placeholder``, ``short``, or ``pending``.
    """
    if not text:
        return "blank"
    if is_gibberish(text):
        return "gibberish"
    if _phrase(text) in _PLACEHOLDERS:
        return "placeholder"
    if why and _short(text):
        return "short"
    return "pending"


def is_gibberish(text: str) -> bool:
    """Return whether the text is a keyboard walk, a repeated character, or letter mash.

    Args:
        text: Stripped response.

    Returns:
        True for gibberish. A sentence with spaces is left for the other rules.
    """
    raw = text.strip().lower()
    compact = re.sub(r"[^a-z]", "", raw)
    if len(compact) < 4:
        return False
    if _keyboard(compact):
        return True
    if re.fullmatch(r"(.)\1{3,}", compact):
        return True
    if len(compact) >= 5 and len(set(compact)) <= 2:
        return True
    if " " in raw:
        return False
    if len(compact) >= 8 and sum(char in "aeiou" for char in compact) / len(compact) < 0.12:
        return True
    return False


def _keyboard(compact: str) -> bool:
    """Return whether the letters are a keyboard-row walk.

    Args:
        compact: Lower-case letters only.

    Returns:
        True for a walk or a repeated walk such as ``asdfasdf``.
    """
    for row in _ROWS:
        if compact in row:
            return True
        for size in range(4, len(row) + 1):
            walk = row[:size]
            if len(compact) % len(walk) == 0 and compact == walk * (len(compact) // len(walk)):
                return True
    return False


def _phrase(text: str) -> str:
    """Normalize a short placeholder for an exact list match.

    Args:
        text: Raw response.

    Returns:
        Lower-case words separated by single spaces.
    """
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _compact(text: str) -> str:
    """Normalize a verbatim for duplicate comparison.

    Args:
        text: Raw response.

    Returns:
        Lower-case letters and digits with punctuation removed.
    """
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _short(text: str) -> bool:
    """Return whether an explanation has fewer than three words.

    Args:
        text: Raw response.

    Returns:
        True when the reply is too short for a why or explain question.
    """
    return len(_WORD.findall(text)) < 3


def _decided_detail(kind: str, name: str, why: bool) -> tuple[str, str, bool]:
    """Map a decided class to a rule id, a sentence, and whether it changes disposition.

    Args:
        kind: Class from ``_classify``.
        name: Variable name.
        why: Whether the question asks for an explanation.

    Returns:
        Rule id, detail, and whether the row should be flagged. A placeholder on a
        question that is not asking for an explanation is recorded and does not flag.
    """
    if kind == "gibberish":
        return "oe_gibberish", f"Open end {name} looks like gibberish.", True
    if kind == "placeholder":
        return "oe_nonsubstantive", f"Open end {name} is a placeholder.", why
    if kind == "short":
        return "oe_short", f"Open end {name} is too short for an explanation.", True
    return "", "", False


def _finding(
    index: int,
    name: str,
    text: str,
    rule_id: str,
    detail: str,
    model_label: str | None = None,
) -> OpenEndFinding:
    """Build one exception row.

    Args:
        index: Row position.
        name: Variable name.
        text: Full text, stored only as a preview.
        rule_id: Rule id.
        detail: Short reason.
        model_label: Model label when this finding came from semantic review.

    Returns:
        Finding. The respondent id is filled in when the report is scored.
    """
    return OpenEndFinding(
        source_row_id=index,
        respondent_id=str(index),
        variable=name,
        text_preview=text[:_PREVIEW],
        rule_id=rule_id,
        detail=detail,
        model_label=model_label,
    )


def _shared_text(
    cells: list[tuple[int, str, str, str]],
    row_count: int,
    scan: OpenScan,
) -> None:
    """Flag identical long verbatims that appear for more than one respondent.

    Args:
        cells: Row, variable, text, and compact form.
        row_count: Respondent count. Unused except to keep the signature stable for callers.
        scan: Open-end result to update.
    """
    del row_count
    grouped: dict[str, list[tuple[int, str, str]]] = {}
    for index, name, text, compact in cells:
        if len(compact) < _DUPLICATE_LENGTH:
            continue
        grouped.setdefault(compact, []).append((index, name, text))
    for copies in grouped.values():
        rows = {index for index, _name, _text in copies}
        if len(rows) < 2:
            continue
        for index, name, text in copies:
            detail = f"Open end {name} matches another respondent."
            scan.flags.setdefault(index, []).append(("oe_duplicate", detail))
            scan.findings.append(_finding(index, name, text, "oe_duplicate", detail))
            scan.pending = [item for item in scan.pending if not _same_cell(item, index, name)]


def _repeated_text(cells: list[tuple[int, str, str, str]], scan: OpenScan) -> None:
    """Flag one respondent who pastes the same text into two open ends.

    Args:
        cells: Row, variable, text, and compact form.
        scan: Open-end result to update.
    """
    by_row: dict[int, list[tuple[str, str, str]]] = {}
    for index, name, text, compact in cells:
        if len(compact) < _REPEAT_LENGTH:
            continue
        by_row.setdefault(index, []).append((name, text, compact))
    for index, items in by_row.items():
        seen: dict[str, str] = {}
        for name, text, compact in items:
            if compact in seen and seen[compact] != name:
                detail = f"The same text is pasted into {seen[compact]} and {name}."
                scan.flags.setdefault(index, []).append(("oe_repeated", detail))
                scan.findings.append(_finding(index, name, text, "oe_repeated", detail))
                scan.pending = [item for item in scan.pending if item.source_row_id != index]
                break
            seen.setdefault(compact, name)


def _same_cell(item: PendingVerbatim, index: int, name: str) -> bool:
    """Return whether a pending verbatim is the cell just decided.

    Args:
        item: Undecided verbatim.
        index: Row position.
        name: Variable name.

    Returns:
        True when the model should not see this cell.
    """
    return item.source_row_id == index and item.variable == name
