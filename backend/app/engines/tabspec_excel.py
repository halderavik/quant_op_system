"""Canonical tab-spec workbook import and export."""

import json
from io import BytesIO
from typing import Any

from openpyxl import Workbook, load_workbook

from app.errors import AppError
from app.schemas.expression import BoolExpr, Comparison
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    DerivedVariable,
    MappingItem,
    NetSpec,
    SignificanceSpec,
    StudyDefaults,
    TableSpec,
    TabSpec,
)

_SHEETS = [
    "README",
    "Study",
    "Tables",
    "Banners",
    "Nets",
    "Derived_Variables",
    "Significance",
    "Mappings",
    "Validation",
]


def export_tabspec(spec: TabSpec) -> bytes:
    """Write the canonical workbook.

    Args:
        spec: Tab spec.

    Returns:
        XLSX bytes.
    """
    book = Workbook()
    readme = book.active
    readme.title = "README"
    readme["A1"] = (
        "Canonical survey studio tab spec. Do not run embedded macros. Arrays are pipe-separated."
    )
    study = book.create_sheet("Study")
    study.append(["key", "value"])
    study.append(["spec_id", spec.spec_id])
    study.append(["dataset_id", spec.dataset_id or ""])
    study.append(["percent_type", spec.study_defaults.percent_type])
    study.append(["weight_variable", spec.study_defaults.weight_variable or ""])
    study.append(["alpha", spec.study_defaults.alpha])
    study.append(["decimals", spec.study_defaults.decimals])
    tables = book.create_sheet("Tables")
    tables.append(
        [
            "id",
            "title",
            "type",
            "source_variables",
            "weight",
            "banner_ids",
            "stats",
            "decimals",
            "order",
        ]
    )
    for table in spec.tables:
        tables.append(
            [
                table.id,
                table.title,
                table.table_type,
                "|".join(table.row_variable_names),
                table.weight_variable or "",
                "|".join(table.banner_ids),
                "|".join(table.statistics),
                table.display_decimals,
                table.order,
            ]
        )
    banners = book.create_sheet("Banners")
    banners.append(
        [
            "banner_id",
            "banner_label",
            "variable",
            "category_label",
            "codes",
            "order",
            "include_total",
        ]
    )
    for banner in spec.banners:
        if not banner.categories:
            banners.append(
                [
                    banner.id,
                    banner.label,
                    banner.variable_name or "",
                    "",
                    "",
                    0,
                    banner.include_total,
                ]
            )
        for category in banner.categories:
            banners.append(
                [
                    banner.id,
                    banner.label,
                    banner.variable_name or "",
                    category.label,
                    "|".join(str(code) for code in category.codes),
                    category.order,
                    banner.include_total,
                ]
            )
    nets = book.create_sheet("Nets")
    nets.append(["table_id", "net_id", "label", "child_codes", "child_variables"])
    for table in spec.tables:
        for net in table.nets:
            nets.append(
                [
                    table.id,
                    net.id,
                    net.label,
                    "|".join(str(code) for code in net.child_codes),
                    "|".join(net.child_variables),
                ]
            )
    derived = book.create_sheet("Derived_Variables")
    derived.append(["name", "recipe", "source", "params_json"])
    for item in spec.derived_variables:
        derived.append([item.name, item.recipe, item.source, json.dumps(item.params)])
    significance = book.create_sheet("Significance")
    significance.append(
        [
            "table_id",
            "enabled",
            "alpha",
            "comparison",
            "correction",
            "minimum_base",
            "secondary_alpha",
        ]
    )
    for table in spec.tables:
        significance.append(
            [
                table.id,
                table.significance.enabled,
                table.significance.alpha,
                table.significance.comparison,
                table.significance.correction,
                table.significance.minimum_effective_base,
                table.significance.secondary_alpha,
            ]
        )
    mappings = book.create_sheet("Mappings")
    mappings.append(["question_id", "variable_names", "status", "reason"])
    for item in spec.unresolved_mappings:
        mappings.append(
            [item.question_id, "|".join(item.variable_names), item.status, item.reason or ""]
        )
    validation = book.create_sheet("Validation")
    validation.append(["issue"])
    for item in spec.exclusions:
        validation.append([f"{item.get('question_id')}: {item.get('reason')}"])
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def import_tabspec(data: bytes) -> TabSpec:
    """Read a canonical workbook back into a tab spec.

    Args:
        data: XLSX bytes.

    Returns:
        Tab spec.

    Raises:
        AppError: When required sheets are missing.
    """
    try:
        book = load_workbook(BytesIO(data), data_only=True)
    except Exception as exc:
        raise AppError("The workbook could not be opened.", "bad_workbook") from exc
    missing = [name for name in _SHEETS if name not in book.sheetnames]
    if missing:
        raise AppError(
            f"This is not a canonical tab spec. Missing sheets: {', '.join(missing)}",
            "bad_workbook",
        )
    study = _rows(book["Study"])
    study_map = {row[0]: row[1] for row in study[1:] if row and row[0]}
    defaults = StudyDefaults(
        percent_type=study_map.get("percent_type") or "column",
        weight_variable=study_map.get("weight_variable") or None,
        alpha=float(study_map.get("alpha") or 0.05),
        decimals=int(study_map.get("decimals") or 1),
    )
    sig_by_table = {row[0]: row for row in _rows(book["Significance"])[1:] if row and row[0]}
    nets_by_table: dict[str, list[NetSpec]] = {}
    for row in _rows(book["Nets"])[1:]:
        if not row or not row[0]:
            continue
        nets_by_table.setdefault(str(row[0]), []).append(
            NetSpec(
                id=str(row[1]),
                label=str(row[2]),
                child_codes=_split(row[3]),
                child_variables=_split(row[4]),
            )
        )
    tables: list[TableSpec] = []
    for row in _rows(book["Tables"])[1:]:
        if not row or not row[0]:
            continue
        sig = sig_by_table.get(row[0])
        tables.append(
            TableSpec(
                id=str(row[0]),
                title=str(row[1]),
                table_type=row[2],
                row_variable_names=_split(row[3]),
                weight_variable=row[4] or None,
                banner_ids=_split(row[5]),
                statistics=_split(row[6]) or ["column_pct"],
                display_decimals=int(row[7] or 1),
                order=int(row[8] or 0),
                nets=nets_by_table.get(str(row[0]), []),
                significance=_sig(sig),
            )
        )
    banners = _banners(book)
    derived = []
    for row in _rows(book["Derived_Variables"])[1:]:
        if not row or not row[0]:
            continue
        derived.append(
            DerivedVariable(
                name=str(row[0]),
                recipe=row[1],
                source=str(row[2]),
                params=json.loads(row[3] or "{}"),
            )
        )
    mappings = []
    for row in _rows(book["Mappings"])[1:]:
        if not row or not row[0]:
            continue
        mappings.append(
            MappingItem(
                question_id=str(row[0]),
                variable_names=_split(row[1]),
                status=row[2] or "unresolved",
                reason=row[3] or None,
            )
        )
    return TabSpec(
        spec_id=str(study_map.get("spec_id") or "imported"),
        dataset_id=study_map.get("dataset_id") or None,
        study_defaults=defaults,
        banners=banners,
        tables=tables,
        derived_variables=derived,
        unresolved_mappings=mappings,
    )


def _banners(book: Any) -> list[Banner]:
    """Rebuild banners from category rows.

    Args:
        book: Open workbook.

    Returns:
        Banners.
    """
    grouped: dict[str, Banner] = {}
    for row in _rows(book["Banners"])[1:]:
        if not row or not row[0]:
            continue
        banner = grouped.get(str(row[0]))
        if banner is None:
            banner = Banner(
                id=str(row[0]),
                label=str(row[1] or row[0]),
                variable_name=row[2] or None,
                include_total=bool(row[6]) if len(row) > 6 else True,
            )
            grouped[banner.id] = banner
        if row[3]:
            banner.categories.append(
                BannerCategory(
                    label=str(row[3]),
                    codes=_coerce_codes(_split(row[4])),
                    order=int(row[5] or 0),
                )
            )
    return list(grouped.values())


def _sig(row: tuple[Any, ...] | list[Any] | None) -> SignificanceSpec:
    """Build a significance spec from a sheet row.

    Args:
        row: Significance row, or None.

    Returns:
        Significance spec.
    """
    if not row:
        return SignificanceSpec()
    return SignificanceSpec(
        enabled=bool(row[1]),
        alpha=float(row[2] or 0.05),
        comparison=row[3] or "pairwise_columns",
        correction=row[4] or "none",
        minimum_effective_base=int(row[5] or 30),
        secondary_alpha=float(row[6]) if len(row) > 6 and row[6] not in (None, "") else 0.10,
    )


def _rows(sheet: Any) -> list[list[Any]]:
    """Return sheet rows as lists.

    Args:
        sheet: Worksheet.

    Returns:
        Rows.
    """
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def _split(value: Any) -> list[str]:
    """Split a pipe-separated cell.

    Args:
        value: Cell value.

    Returns:
        Non-empty parts.
    """
    if value is None or value == "":
        return []
    return [part for part in str(value).split("|") if part != ""]


def _coerce_codes(parts: list[str]) -> list[Any]:
    """Convert numeric code text back to numbers.

    Args:
        parts: Code strings.

    Returns:
        Codes.
    """
    codes: list[Any] = []
    for part in parts:
        try:
            number = float(part)
        except ValueError:
            codes.append(part)
            continue
        codes.append(int(number) if number.is_integer() else number)
    return codes


def parse_filter(payload: str | None) -> Comparison | BoolExpr | None:
    """Parse a stored filter. Present so callers do not eval text.

    Args:
        payload: JSON expression or empty.

    Returns:
        Expression or None.
    """
    if not payload:
        return None
    data = json.loads(payload)
    if data.get("kind") == "bool":
        return BoolExpr.model_validate(data)
    return Comparison.model_validate(data)
