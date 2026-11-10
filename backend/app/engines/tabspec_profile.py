"""Dataset columns the validator is allowed to name."""

import re
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.engines.derived import in_codes
from app.engines.tabspec_banners import is_weight_name
from app.engines.tabspec_build import _is_admin
from app.engines.tabspec_text import format_expr
from app.schemas.questionnaire import Question, Questionnaire

_PUNCH = re.compile(r"^(?P<stem>[A-Za-z_][A-Za-z0-9_]*?)r(?P<code>\d+)$")
_CODE_CAP = 15

Shape = Literal["single", "numeric", "text", "empty", "admin", "multi"]


class ColumnProfile(BaseModel):
    """One dataset column, with the facts a tabulation decision needs."""

    name: str
    label: str
    value_labels: dict[str, str] = Field(default_factory=dict)
    user_missing: list[str] = Field(default_factory=list)
    observed_codes: list[str] = Field(default_factory=list)
    nonmissing_n: int = 0
    shape: Shape
    family: str = ""
    question_id: str | None = None
    question_type: str | None = None
    display_if: str | None = None
    note: str = ""


class FamilyProfile(BaseModel):
    """Punch columns that belong on one multiple-response table."""

    family: str
    members: list[str]
    question_id: str | None = None
    question_type: str | None = None
    display_if: str | None = None


class DatasetProfile(BaseModel):
    """The only variable list the validator may use."""

    columns: list[ColumnProfile]
    families: list[FamilyProfile] = Field(default_factory=list)


def build_profile(
    frame: pd.DataFrame,
    variables: list[dict[str, Any]],
    questionnaire: Questionnaire | None = None,
) -> DatasetProfile:
    """Describe each column from the data, not from a guessed question id.

    Args:
        frame: Respondent data.
        variables: Variable dictionary.
        questionnaire: Active instrument, when one is saved.

    Returns:
        Column facts and multi-response families.
    """
    questions = list(questionnaire.questions) if questionnaire else []
    names = [str(item["name"]) for item in variables]
    families = _families(names, questions)
    member_of = {name: family for family, members in families.items() for name in members}
    attached = _questions_for_columns(questions, set(names), families)
    columns: list[ColumnProfile] = []
    for item in variables:
        name = str(item["name"])
        question = attached.get(name)
        columns.append(_column(frame, item, member_of.get(name, ""), question))
    family_rows = [
        FamilyProfile(
            family=family,
            members=members,
            question_id=family if any(question.id == family for question in questions) else None,
            question_type=_family_type(questions, family),
            display_if=_family_base(questions, family),
        )
        for family, members in families.items()
    ]
    return DatasetProfile(columns=columns, families=family_rows)


def tabbable(profile: DatasetProfile) -> bool:
    """Return whether any column can become a crosstab stub.

    Args:
        profile: Column facts.

    Returns:
        True when a single, numeric, or multi column has observed data.
    """
    return any(
        column.shape in {"single", "numeric", "multi"} and column.nonmissing_n > 0
        for column in profile.columns
    )


def _families(names: list[str], questions: list[Question]) -> dict[str, list[str]]:
    """Group punch columns that share a question stem.

    Args:
        names: Dataset column names.
        questions: Instrument items.

    Returns:
        Family id to member names, only when a family has two or more members.
    """
    found: dict[str, list[str]] = {}
    for name in names:
        match = _PUNCH.match(name)
        if match:
            found.setdefault(match.group("stem"), []).append(name)
    present = set(names)
    for question in questions:
        members = [name for name in question.variable_names if name in present]
        if question.type == "multi_select" and len(members) >= 2:
            current = found.setdefault(question.id, [])
            for name in members:
                if name not in current:
                    current.append(name)
    return {
        family: _punch_sorted(members) for family, members in found.items() if len(members) >= 2
    }


def _punch_sorted(names: list[str]) -> list[str]:
    """Order punch columns by their code, then by name.

    Args:
        names: Member names.

    Returns:
        Sorted names.
    """

    def _key(name: str) -> tuple[int, int, str]:
        match = _PUNCH.match(name)
        if match:
            return (0, int(match.group("code")), name)
        return (1, 0, name)

    return sorted(names, key=_key)


def _questions_for_columns(
    questions: list[Question], names: set[str], families: dict[str, list[str]]
) -> dict[str, Question]:
    """Attach a question to the columns it programs.

    Args:
        questions: Instrument items.
        names: Dataset column names.
        families: Multi-response families.

    Returns:
        Column name to question.
    """
    found: dict[str, Question] = {}
    by_id = {question.id: question for question in questions}
    for question in questions:
        targets = [name for name in question.variable_names if name in names]
        if not targets and question.id in names:
            targets = [question.id]
        for name in targets:
            found.setdefault(name, question)
    for family, members in families.items():
        question = by_id.get(family)
        if question is None:
            continue
        for name in members:
            found.setdefault(name, question)
    return found


def _column(
    frame: pd.DataFrame,
    item: dict[str, Any],
    family: str,
    question: Question | None,
) -> ColumnProfile:
    """Profile one column.

    Args:
        frame: Respondent data.
        item: Variable dictionary entry.
        family: Multi-response family id, or empty.
        question: Matching question, when one is known.

    Returns:
        Column profile.
    """
    name = str(item["name"])
    labels = {str(key): str(value) for key, value in dict(item.get("value_labels") or {}).items()}
    missing = [str(code) for code in list(item.get("user_missing_values") or [])]
    series = frame[name] if name in frame.columns else pd.Series(dtype="object")
    count, observed, truncated = _observed(series, list(item.get("user_missing_values") or []))
    shape, note = _shape(name, item, family, count, observed, labels, truncated)
    display = format_expr(question.display_if) if question and question.display_if else None
    if display == "All":
        display = None
    return ColumnProfile(
        name=name,
        label=str(item.get("label") or name),
        value_labels=labels,
        user_missing=missing,
        observed_codes=[] if shape == "numeric" else observed,
        nonmissing_n=count,
        shape=shape,
        family=family if shape == "multi" else "",
        question_id=question.id if question else None,
        question_type=question.type if question else None,
        display_if=display,
        note=note,
    )


def _observed(series: pd.Series, missing: list[Any]) -> tuple[int, list[str], bool]:
    """Count non-missing rows and list the codes that appear.

    Args:
        series: Column.
        missing: User-missing codes.

    Returns:
        Non-missing count, code text, and whether the code list was cut off.
    """
    mask = ~series.isna()
    if missing:
        mask = mask & ~in_codes(series, missing)
    count = int(mask.sum())
    seen: list[str] = []
    for value in series[mask].drop_duplicates().tolist():
        seen.append(_code_text(value))
    truncated = len(seen) > _CODE_CAP
    return count, seen[:_CODE_CAP], truncated


def _shape(
    name: str,
    item: dict[str, Any],
    family: str,
    count: int,
    observed: list[str],
    labels: dict[str, str],
    truncated: bool,
) -> tuple[Shape, str]:
    """Classify a column for tabulation.

    Args:
        name: Variable name.
        item: Variable dictionary entry.
        family: Multi-response family id, or empty.
        count: Non-missing rows.
        observed: Observed code text.
        labels: Value labels.
        truncated: Whether more than the code cap was observed.

    Returns:
        Shape and a short note.
    """
    if _is_admin(name) or is_weight_name(name):
        return "admin", "Admin, paradata, or weight"
    if item.get("is_text"):
        return "text", "Text is coded before it is tabulated"
    if count == 0:
        return "empty", "Empty (n=0)"
    if family and not truncated:
        return "multi", ""
    if truncated or (not labels and len(observed) > _CODE_CAP):
        return "numeric", "Many distinct values"
    if labels or observed:
        return "single", ""
    return "numeric", ""


def _family_type(questions: list[Question], family: str) -> str | None:
    """Return the question type for a family stem.

    Args:
        questions: Instrument items.
        family: Family id.

    Returns:
        Question type, or None.
    """
    for question in questions:
        if question.id == family:
            return question.type
    return None


def _family_base(questions: list[Question], family: str) -> str | None:
    """Return the display rule for a family, when it names a real comparison.

    Args:
        questions: Instrument items.
        family: Family id.

    Returns:
        Base sentence, or None.
    """
    for question in questions:
        if question.id == family and question.display_if is not None:
            text = format_expr(question.display_if)
            return None if text == "All" else text
    return None


def _code_text(value: Any) -> str:
    """Render an observed value as a short code.

    Args:
        value: Cell value.

    Returns:
        Integer text when the value is an integral number, otherwise its text.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)
