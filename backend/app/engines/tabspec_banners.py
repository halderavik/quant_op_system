"""Banner plans A and B, including small-base collapses."""

import re
from typing import Any

import pandas as pd

from app.engines.derived import in_codes
from app.engines.tabspec_text import format_codes, low_base_flag
from app.schemas.questionnaire import Question
from app.schemas.tabspec import Banner, BannerCategory, DerivedVariable

_PROFILE = {"gender", "age", "age_band", "region"}


def build_banner_plan(
    questions: list[Question],
    module_of: dict[str, str],
    by_name: dict[str, dict[str, Any]],
    frame: pd.DataFrame | None,
) -> tuple[list[Banner], list[DerivedVariable]]:
    """Build plan A from profile variables and plan B from marked banners.

    Args:
        questions: Instrument items.
        module_of: Question id to section title.
        by_name: Variable dictionary.
        frame: Data used to collapse categories under n=20.

    Returns:
        Banners and any collapse variables.
    """
    chosen: list[tuple[str, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for question in questions:
        names = question.variable_names or [question.id]
        plan = _question_plan(question, module_of.get(question.id, ""), names[0])
        if plan and names[0] not in seen:
            info = by_name.get(names[0]) or {
                "name": names[0],
                "label": question.text,
                "value_labels": {},
            }
            chosen.append((plan, names[0], info))
            seen.add(names[0])
    for name, info in by_name.items():
        if name in seen or is_weight_name(name) or info.get("is_text"):
            continue
        if name.lower() in _PROFILE or re.fullmatch(r"S\d+[A-Za-z0-9_]*", name):
            chosen.append(("A", name, info))
            seen.add(name)
    banners: list[Banner] = []
    derived: list[DerivedVariable] = []
    letters = {plan: 0 for plan in ("A", "B")}
    for plan, name, info in chosen:
        banner, extra = _one_banner(plan, name, info, frame, letters)
        banners.append(banner)
        if extra:
            derived.append(extra)
    return banners, derived


def is_weight_name(name: str) -> bool:
    """Return whether a name looks like a weight.

    Args:
        name: Variable name.

    Returns:
        True when the name contains ``weight``.
    """
    return "weight" in name.lower()


def coerce_code(code: Any) -> Any:
    """Convert a value-label key back to a number when it is numeric.

    Args:
        code: Label key stored as text.

    Returns:
        Int, float, or the original text.
    """
    try:
        number = float(code)
    except (TypeError, ValueError):
        return code
    if number.is_integer():
        return int(number)
    return number


def is_int_code(code: Any) -> bool:
    """Return whether a code can be a banner integer.

    Args:
        code: Code value.

    Returns:
        True for ints and integral floats, excluding booleans.
    """
    if isinstance(code, bool) or not isinstance(code, (int, float)):
        return False
    return float(code).is_integer()


def _question_plan(question: Question, section: str, name: str) -> str:
    """Decide whether a question is banner A, banner B, or not a banner.

    Args:
        question: Question.
        section: Module title.
        name: First variable name.

    Returns:
        ``A``, ``B``, or an empty string.
    """
    if question.type == "screener" or _profile_name(name) or _profile_section(section):
        return "A"
    notes = " ".join(question.notes + question.programmer_notes + question.reporting.stats)
    if "banner" in notes.lower():
        return "B"
    return ""


def _one_banner(
    plan: str,
    name: str,
    info: dict[str, Any],
    frame: pd.DataFrame | None,
    letters: dict[str, int],
) -> tuple[Banner, DerivedVariable | None]:
    """Build one group, collapsing categories with a base under 20.

    Args:
        plan: A or B.
        name: Source variable.
        info: Variable dictionary entry.
        frame: Data, or None when bases are unknown.
        letters: Next letter index per plan.

    Returns:
        Banner and an optional derived collapse.
    """
    label = str(info.get("label") or name)
    group = f"{label} ({name})" if label != name else name
    categories = _categories(info)
    for category in categories:
        if frame is not None and name in frame.columns:
            category.n = int(in_codes(frame[name], category.codes).sum())
            category.low_base = low_base_flag(category.n)
    derived = None
    variable_name = name
    note = f"{name} (as is)"
    small = [item for item in categories if item.n is not None and item.n < 20]
    if small and len(small) < len(categories):
        variable_name, note, categories, derived = _collapse(name, categories, small)
    for category in categories:
        category.letter = _letter(letters, plan)
        if not category.definition:
            category.definition = f"{variable_name} = {format_codes(category.codes)}"
    banner = Banner(
        id=f"{plan}_{name}",
        label=group,
        group=group,
        plan=plan,
        variable_name=variable_name,
        source_variable=name,
        variable_note=note,
        categories=categories,
        include_total=True,
    )
    return banner, derived


def _collapse(
    name: str,
    categories: list[BannerCategory],
    small: list[BannerCategory],
) -> tuple[str, str, list[BannerCategory], DerivedVariable]:
    """Bundle categories under n=20 into one derived code.

    Args:
        name: Source variable.
        categories: Original categories.
        small: Categories with a base under 20.

    Returns:
        Derived name, variable note, replacement categories, and the recipe.
    """
    ban_name = f"BAN_{re.sub(r'[^A-Za-z0-9]+', '_', name).upper()}"
    kept = [item for item in categories if item not in small]
    new_code = max((int(item.codes[0]) for item in kept if is_int_code(item.codes[0])), default=0)
    new_code += 1
    mapping: dict[str, int] = {}
    rebuilt: list[BannerCategory] = []
    parts: list[str] = []
    for item in kept:
        kept_code = int(item.codes[0]) if is_int_code(item.codes[0]) else new_code
        mapping[str(item.codes[0])] = kept_code
        item.definition = f"{ban_name} = {format_codes(item.codes)}"
        rebuilt.append(item)
        source_codes = format_codes(item.codes)
        parts.append(f"{source_codes} = {item.label} ({name}={source_codes})")
    small_codes = [item.codes[0] for item in small]
    for code in small_codes:
        mapping[str(code)] = new_code
    collapsed_n = sum(item.n or 0 for item in small)
    other = BannerCategory(
        label="Other collapsed",
        codes=[new_code],
        order=len(rebuilt),
        n=collapsed_n,
        low_base=low_base_flag(collapsed_n),
        definition=f"{ban_name} = {new_code}",
    )
    rebuilt.append(other)
    parts.append(f"{new_code} = Other collapsed ({name}={format_codes(small_codes)})")
    derived = DerivedVariable(
        name=ban_name,
        recipe="recode",
        source=name,
        params={"map": mapping},
        kind="Banner",
        definition="; ".join(parts),
        purpose="Collapse small cells so each banner column has a usable base",
    )
    return ban_name, ban_name, rebuilt, derived


def _categories(info: dict[str, Any]) -> list[BannerCategory]:
    """Build categories from value labels.

    Args:
        info: Variable dictionary entry.

    Returns:
        Categories in label order.
    """
    categories = []
    for order, (code, text) in enumerate((info.get("value_labels") or {}).items()):
        categories.append(BannerCategory(label=str(text), codes=[coerce_code(code)], order=order))
    return categories


def _profile_name(name: str) -> bool:
    """Return whether a name is a screener or demographic banner.

    Args:
        name: Variable or question id.

    Returns:
        True for ``S1`` style names and the standard demographic names.
    """
    return name.lower() in _PROFILE or re.fullmatch(r"S\d+[A-Za-z0-9_]*", name) is not None


def _profile_section(section: str) -> bool:
    """Return whether a module title marks profile questions.

    Args:
        section: Module title.

    Returns:
        True when the title says screener, profile, or demographic.
    """
    folded = section.lower()
    return any(word in folded for word in ("screener", "profile", "demographic"))


def _letter(letters: dict[str, int], plan: str) -> str:
    """Take the next column letter inside one banner plan.

    Args:
        letters: Next index per plan.
        plan: A or B.

    Returns:
        A letter, or an empty string past Z.
    """
    index = letters.get(plan, 0)
    letters[plan] = index + 1
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return alphabet[index] if index < len(alphabet) else ""
