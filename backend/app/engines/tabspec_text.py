"""Human-readable banner definitions, bases, and net instructions."""

import re
from typing import Any

from app.schemas.expression import Comparison, Expr
from app.schemas.tabspec import NetSpec

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_DEF = re.compile(rf"^(?P<var>{_IDENT})\s*=\s*(?P<codes>.+)$")
_BASE = re.compile(rf"({_IDENT})\s*=\s*([0-9][0-9,\s–-]*)")
_NET = re.compile(r"NET\s+(.+?)\s*\(([^)]+)\)", re.IGNORECASE)
_BOX = re.compile(r"(Top-2|Bottom-2)\s*\(([^)]+)\)", re.IGNORECASE)
_DERIVED_PART = re.compile(
    rf"^(?P<code>\d+)\s*=\s*(?P<label>.+?)\s*\((?P<src>{_IDENT})\s*=\s*(?P<codes>[^)]+)\)$"
)
_RANK = re.compile(
    rf"1 if (?P<src>{_IDENT}) (?:=|is answered) \(?(?P<codes>[0-9][0-9,\s–-]*)\)?",
    re.IGNORECASE,
)


def low_base_flag(count: int | None) -> str:
    """Flag a banner column the way the analyst plan does.

    Args:
        count: Unweighted column base, when known.

    Returns:
        ``Not tested`` below 20, ``*low base`` from 20 to 29, otherwise empty.
    """
    if count is None:
        return ""
    if count < 20:
        return "Not tested"
    if count < 30:
        return "*low base"
    return ""


def format_codes(codes: list[Any]) -> str:
    """Format codes as a comma list, or an en-dash span when they are consecutive.

    Args:
        codes: Category or net codes.

    Returns:
        Display text such as ``1, 2`` or ``2–5``.
    """
    numbers: list[int] = []
    for code in codes:
        if isinstance(code, bool) or not isinstance(code, (int, float)):
            return ", ".join(str(code) for code in codes)
        if isinstance(code, float) and not code.is_integer():
            return ", ".join(str(code) for code in codes)
        numbers.append(int(code))
    if not numbers:
        return ""
    span = list(range(numbers[0], numbers[0] + len(numbers)))
    if numbers == span and len(numbers) >= 3:
        return f"{numbers[0]}–{numbers[-1]}"
    return ", ".join(str(number) for number in numbers)


def parse_code_list(text: str) -> list[int] | None:
    """Parse ``1, 2`` or ``2–5`` into integers.

    Args:
        text: Code cell.

    Returns:
        Codes, or None when the text is not a code list.
    """
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return None
    codes: list[int] = []
    for part in parts:
        span = re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", part)
        if span:
            start, end = int(span.group(1)), int(span.group(2))
            if end < start or end - start > 50:
                return None
            codes.extend(range(start, end + 1))
            continue
        if not re.fullmatch(r"\d+", part):
            return None
        codes.append(int(part))
    return codes


def parse_definition(text: str) -> tuple[str, list[int]] | None:
    """Parse a banner definition such as ``S1 = 1, 2``.

    Args:
        text: Definition cell.

    Returns:
        Variable name and codes, or None for a total row or free text.
    """
    match = _DEF.match((text or "").strip())
    if not match:
        return None
    codes = parse_code_list(match.group("codes"))
    if not codes:
        return None
    return match.group("var"), codes


def format_expr(expr: Expr | None) -> str:
    """Render a filter as a base sentence.

    Args:
        expr: Table filter, or None for everyone.

    Returns:
        ``All`` or a comparison such as ``Q8 = 2–5``.
    """
    if expr is None:
        return "All"
    if isinstance(expr, Comparison):
        if expr.op == "eq":
            return f"{expr.ref} = {expr.value}"
        if expr.op == "in" and isinstance(expr.value, list):
            return f"{expr.ref} = {format_codes(list(expr.value))}"
        return f"{expr.ref} {expr.op} {expr.value}"
    joiner = " and " if expr.op == "and" else " or "
    if expr.op == "not" and expr.args:
        return f"not ({format_expr(expr.args[0])})"
    return joiner.join(format_expr(arg) for arg in expr.args)


def parse_base(text: str) -> tuple[Comparison | None, bool]:
    """Parse a base cell. Unparsed prose is not turned into a filter.

    Args:
        text: Base cell from the table plan.

    Returns:
        A comparison when the cell names codes, and whether the cell is confirmed.
        ``All`` is confirmed and has no filter.
    """
    raw = (text or "").strip()
    folded = raw.lower()
    if folded == "" or folded == "all" or folded.startswith("all ") or folded.startswith("all("):
        return None, True
    match = _BASE.search(raw)
    if not match:
        return None, False
    codes = parse_code_list(match.group(2))
    if not codes:
        return None, False
    if len(codes) == 1:
        return Comparison(op="eq", ref=match.group(1), value=codes[0]), True
    return Comparison(op="in", ref=match.group(1), value=codes), True


def parse_row_instruction(
    text: str,
) -> tuple[list[NetSpec], list[int], list[int]]:
    """Read nets and top/bottom boxes out of a rows cell.

    Args:
        text: ``Rows / nets / stats`` cell.

    Returns:
        Nets, top-box codes, and bottom-box codes. Semantic net names are kept.
    """
    nets: list[NetSpec] = []
    for index, match in enumerate(_NET.finditer(text or ""), start=1):
        codes = parse_code_list(match.group(2))
        if not codes:
            continue
        nets.append(
            NetSpec(id=f"N{index}", label=f"NET {match.group(1).strip()}", child_codes=codes)
        )
    top: list[int] = []
    bottom: list[int] = []
    for match in _BOX.finditer(text or ""):
        codes = parse_code_list(match.group(2)) or []
        if match.group(1).lower().startswith("top"):
            top = codes
        else:
            bottom = codes
    return nets, top, bottom


def parse_derived_definition(
    kind: str, definition: str, source: str
) -> tuple[str, dict[str, Any]] | None:
    """Recover a whitelist recipe from a derived-variable definition.

    Args:
        kind: Banner, Ranking flag, or Top-2 box flag.
        definition: Definition cell.
        source: Source column from the sheet.

    Returns:
        Recipe name and params, or None when the sentence is not executable.
    """
    if kind == "Banner":
        mapping: dict[str, int] = {}
        found_source = source
        for part in (definition or "").split(";"):
            match = _DERIVED_PART.match(part.strip())
            if not match:
                return None
            found_source = match.group("src")
            codes = parse_code_list(match.group("codes"))
            if not codes:
                return None
            for code in codes:
                mapping[str(code)] = int(match.group("code"))
        if not mapping:
            return None
        return "recode", {"map": mapping, "source": found_source}
    if kind in {"Ranking flag", "Top-2 box flag"}:
        match = _RANK.search(definition or "")
        if not match:
            return None
        codes = parse_code_list(match.group("codes"))
        if not codes:
            return None
        recipe = "top_box" if kind == "Top-2 box flag" else "net_flag"
        return recipe, {"codes": codes, "source": match.group("src")}
    return None


def banner_plan_cell(plans: list[str]) -> str:
    """Join banner plans the way the table-plan sheet does.

    Args:
        plans: Plan letters such as ``A`` and ``B``.

    Returns:
        ``A``, ``B``, ``A + B``, or an empty cell.
    """
    return " + ".join(plan for plan in plans if plan)


def parse_banner_plans(text: str) -> list[str]:
    """Split ``A + B`` into plan letters.

    Args:
        text: Banner cell.

    Returns:
        Plan letters in order.
    """
    plans: list[str] = []
    for part in re.split(r"\s*\+\s*", (text or "").strip()):
        letter = part.strip().upper()
        if letter in {"A", "B"} and letter not in plans:
            plans.append(letter)
    return plans
