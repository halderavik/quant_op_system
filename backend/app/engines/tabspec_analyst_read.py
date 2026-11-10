"""Read a five-sheet analyst crosstab plan back into a tab spec."""

from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.engines.tabspec_text import (
    low_base_flag,
    parse_banner_plans,
    parse_base,
    parse_definition,
    parse_derived_definition,
    parse_row_instruction,
    parse_selected_codes,
)
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    DerivedVariable,
    SignificanceSpec,
    StudyDefaults,
    TableBase,
    TableSpec,
    TabSpec,
)

_PLAN_TYPE = {
    "Single": "categorical",
    "Multi": "multiple_response",
    "Grid item": "categorical",
    "Grid summary": "grid",
    "Ranking": "multiple_response",
    "Open end": "categorical",
}


def import_analyst(data: bytes) -> TabSpec:
    """Read an analyst plan back into a tab spec.

    Args:
        data: XLSX bytes.

    Returns:
        Tab spec. A base cell that is not ``All`` and not a code comparison
        is stored as a note and blocks that table.
    """
    book = load_workbook(BytesIO(data), data_only=False)
    overview = _map(_rows(book["Overview"]))
    defaults = _defaults(overview)
    banners = _read_banners(book["Banner specs"], defaults.sample_size)
    derived = _read_derived(book["Derived variables"])
    tables = _read_tables(book["Table plan"], banners, defaults)
    exclusions = []
    for row in _rows(book["Not tabbed"])[1:]:
        if row and row[0]:
            exclusions.append({"question_id": str(row[0]), "reason": str(row[1] or "")})
    return TabSpec(
        spec_id=str(overview.get("dataset id") or overview.get("study") or "imported"),
        dataset_id=overview.get("dataset id") or None,
        study_defaults=defaults,
        banners=banners,
        tables=tables,
        derived_variables=derived,
        exclusions=exclusions,
    )


def _defaults(overview: dict[str, str]) -> StudyDefaults:
    """Read study settings from the overview labels.

    Args:
        overview: Lower-cased label to value.

    Returns:
        Study defaults.
    """
    weighting = overview.get("weighting", "")
    weight = None
    if weighting.lower().startswith("weighted by "):
        weight = weighting.split(" ", 2)[-1].strip() or None
    sample_text = overview.get("sample", "")
    sample_size = None
    digits = "".join(character for character in sample_text if character.isdigit())
    if digits:
        sample_size = int(digits)
    minimum = 20 if "under 20" in overview.get("minimum base", "") else 30
    return StudyDefaults(
        weight_variable=weight,
        minimum_unweighted_base_for_display=minimum,
        study_title=overview.get("study", ""),
        sample_note=sample_text,
        sample_size=sample_size,
        assumptions=overview.get("assumptions to confirm", ""),
    )


def _read_banners(sheet: Worksheet, sample_size: int | None) -> list[Banner]:
    """Rebuild banner groups from column rows.

    Args:
        sheet: Banner specs worksheet.
        sample_size: Total n from the overview, used when the Total cell is a formula.

    Returns:
        Banners. The Total row is not a category.
    """
    grouped: dict[tuple[str, str], Banner] = {}
    order = 0
    for row in _rows(sheet)[1:]:
        if not row or not row[0] or str(row[2] or "").strip().lower() == "total":
            continue
        plan = str(row[0]).strip()
        group = str(row[2] or row[3] or plan)
        key = (plan, group)
        banner = grouped.get(key)
        variable_note = str(row[7] or "")
        variable_name = _variable_name(variable_note, str(row[4] or ""))
        if banner is None:
            banner = Banner(
                id=_banner_id(plan, group),
                label=group,
                group=group,
                plan=plan,
                variable_name=variable_name,
                variable_note=variable_note,
                include_total=True,
            )
            grouped[key] = banner
        parsed = parse_definition(str(row[4] or ""))
        codes = parsed[1] if parsed else []
        count = (
            row[5] if isinstance(row[5], (int, float)) and not isinstance(row[5], bool) else None
        )
        count_int = int(count) if count is not None else None
        low = row[6] if isinstance(row[6], str) and not str(row[6]).startswith("=") else ""
        banner.categories.append(
            BannerCategory(
                label=str(row[3] or ""),
                codes=codes,
                order=order,
                letter=str(row[1] or ""),
                n=count_int,
                low_base=low or low_base_flag(count_int),
                definition=str(row[4] or ""),
            )
        )
        order += 1
    if sample_size is not None:
        for banner in grouped.values():
            banner.include_total = True
    return list(grouped.values())


def _read_tables(
    sheet: Worksheet, banners: list[Banner], defaults: StudyDefaults
) -> list[TableSpec]:
    """Rebuild tables. An unparsed base blocks that table only.

    Args:
        sheet: Table plan worksheet.
        banners: Banners already read.
        defaults: Study defaults, including the minimum base.

    Returns:
        Tables.
    """
    tables: list[TableSpec] = []
    for index, row in enumerate(_rows(sheet)[1:], start=1):
        if not row or not row[0]:
            continue
        plan_type = str(row[4] or "Single")
        base_text = str(row[5] or "All")
        comparison, confirmed = parse_base(base_text)
        instruction = str(row[7] or "")
        nets, top, bottom = parse_row_instruction(instruction)
        plans = parse_banner_plans(str(row[8] or ""))
        notes = [str(row[10])] if len(row) > 10 and row[10] else []
        if not confirmed:
            notes.append(f"Confirm the base before this table runs: {base_text}")
        method = str(row[9] or "crosstab")
        enabled = "crosstab_sig" in method
        base_n = (
            row[6] if isinstance(row[6], (int, float)) and not isinstance(row[6], bool) else None
        )
        tables.append(
            TableSpec(
                id=str(row[0]),
                section=str(row[1] or ""),
                stub_label=str(row[2] or ""),
                title=str(row[3] or row[0]),
                row_variable_names=_stub_names(str(row[2] or "")),
                selected_codes=parse_selected_codes(instruction),
                table_type=_PLAN_TYPE.get(plan_type, "categorical"),  # type: ignore[arg-type]
                plan_type=plan_type,
                base_text=base_text,
                base_n=int(base_n) if base_n is not None else None,
                base=TableBase(filter=comparison),
                row_instruction=instruction,
                banner_plans=plans,
                banner_ids=[banner.id for banner in banners if banner.plan in plans],
                method=method,
                nets=nets,
                top_box_codes=top,
                bottom_box_codes=bottom,
                notes=notes,
                needs_confirmation=not confirmed,
                order=index,
                significance=SignificanceSpec(
                    enabled=enabled,
                    minimum_effective_base=defaults.minimum_unweighted_base_for_display,
                    secondary_alpha=0.10,
                ),
            )
        )
    return tables


def _read_derived(sheet: Worksheet) -> list[DerivedVariable]:
    """Rebuild derived variables. Unparsed definitions are kept and not applied.

    Args:
        sheet: Derived variables worksheet.

    Returns:
        Derived variables.
    """
    items: list[DerivedVariable] = []
    for row in _rows(sheet)[1:]:
        if not row or not row[0]:
            continue
        kind = str(row[1] or "")
        source = str(row[2] or "")
        definition = str(row[3] or "")
        parsed = parse_derived_definition(kind, definition, source)
        recipe = "recode"
        params: dict[str, Any] = {}
        apply = False
        if parsed:
            recipe, params = parsed
            source = str(params.pop("source", source))
            apply = True
        elif kind in {"recode", "band", "reverse", "top_box", "net_flag"}:
            recipe = kind
            apply = False
        items.append(
            DerivedVariable(
                name=str(row[0]),
                recipe=recipe,  # type: ignore[arg-type]
                source=source or str(row[0]),
                params=params,
                kind=kind,
                definition=definition,
                purpose=str(row[4] or ""),
                apply=apply,
            )
        )
    return items


def _variable_name(note: str, definition: str) -> str | None:
    """Choose the column variable from the Variable cell or the definition.

    Args:
        note: Variable cell.
        definition: Definition cell.

    Returns:
        Variable name, or None for a total column.
    """
    cleaned = note.strip()
    if cleaned in {"", "—", "-", "–"}:
        parsed = parse_definition(definition)
        return parsed[0] if parsed else None
    if cleaned.lower().endswith("(as is)"):
        return cleaned[: -len("(as is)")].strip() or None
    return cleaned


def _stub_names(text: str) -> list[str]:
    """Split the variable cell into executable names.

    Args:
        text: Variable(s) cell.

    Returns:
        Names. A ``$set: a, b`` cell uses the member list.
    """
    raw = text.strip()
    if raw.startswith("$") and ": " in raw:
        raw = raw.split(": ", 1)[1]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _banner_id(plan: str, group: str) -> str:
    """Build a stable banner id from the plan letter and group name.

    Args:
        plan: A or B.
        group: Group label.

    Returns:
        Id.
    """
    slug = "".join(character.lower() if character.isalnum() else "_" for character in group)
    slug = "_".join(part for part in slug.split("_") if part) or "group"
    return f"{plan}_{slug}"[:48]


def _map(rows: list[list[Any]]) -> dict[str, str]:
    """Index overview labels.

    Args:
        rows: Sheet rows.

    Returns:
        Lower-cased label to string value.
    """
    found: dict[str, str] = {}
    for row in rows:
        if row and row[0]:
            found[str(row[0]).strip().lower()] = (
                "" if len(row) < 2 or row[1] is None else str(row[1])
            )
    return found


def _rows(sheet: Worksheet) -> list[list[Any]]:
    """Return sheet rows as lists.

    Args:
        sheet: Worksheet.

    Returns:
        Rows.
    """
    return [list(row) for row in sheet.iter_rows(values_only=True)]
