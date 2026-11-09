"""Five-sheet analyst crosstab plan, matching the example workbook style."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from app.engines.tabspec_text import banner_plan_cell, format_codes, format_expr
from app.schemas.tabspec import Banner, TableSpec, TabSpec

ANALYST_SHEETS = [
    "Overview",
    "Banner specs",
    "Table plan",
    "Derived variables",
    "Not tabbed",
]


def export_analyst(spec: TabSpec) -> bytes:
    """Write the analyst plan.

    Args:
        spec: Tab spec.

    Returns:
        XLSX bytes.
    """
    book = Workbook()
    overview = book.active
    overview.title = "Overview"
    _overview(overview, spec)
    banners = book.create_sheet("Banner specs")
    _banners(banners, spec)
    tables = book.create_sheet("Table plan")
    _tables(tables, spec)
    derived = book.create_sheet("Derived variables")
    _derived(derived, spec)
    skipped = book.create_sheet("Not tabbed")
    _skipped(skipped, spec)
    for sheet in (banners, tables, derived, skipped):
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    _polish(book)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


_NAVY = PatternFill("solid", fgColor="1F3864")
_ORANGE = PatternFill("solid", fgColor="FCE4D6")
_HEADER = Font(name="Arial", size=11, bold=True, color="FFFFFF")
_BODY = Font(name="Arial", size=10)
_LABEL = Font(name="Arial", size=10, bold=True)
_TITLE = Font(name="Arial", size=14, bold=True)
_THIN = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)
_WRAP = Alignment(wrap_text=True, vertical="top")
_CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")
_WIDTHS = {
    "Overview": {"A": 30, "B": 95},
    "Banner specs": {"A": 8, "B": 6, "C": 24, "D": 44, "E": 26, "F": 7, "G": 14, "H": 22},
    "Table plan": {
        "A": 8,
        "B": 22,
        "C": 18,
        "D": 52,
        "E": 14,
        "F": 32,
        "G": 10,
        "H": 52,
        "I": 10,
        "J": 22,
        "K": 40,
    },
    "Derived variables": {"A": 26, "B": 16, "C": 16, "D": 80, "E": 40},
    "Not tabbed": {"A": 90, "B": 60},
}
_ROW_HEIGHT = {
    "Banner specs": 18,
    "Table plan": 36,
    "Derived variables": 24,
    "Not tabbed": 18,
}


def _polish(book: Workbook) -> None:
    """Apply the example workbook's fonts, widths, header bar, and low-base shading.

    Args:
        book: Analyst workbook.
    """
    for name in ANALYST_SHEETS:
        sheet = book[name]
        sheet.sheet_view.showGridLines = False
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToPage = True
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        for letter, width in _WIDTHS[name].items():
            sheet.column_dimensions[letter].width = width
        if name == "Overview":
            _polish_overview(sheet)
            continue
        sheet.auto_filter.ref = sheet.dimensions
        sheet.row_dimensions[1].height = 27
        for cell in sheet[1]:
            cell.font = _HEADER
            cell.fill = _NAVY
            cell.alignment = _CENTER
            cell.border = _THIN
        for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=sheet.max_column):
            low = name == "Banner specs" and _low_base_row(row[5].value)
            sheet.row_dimensions[row[0].row].height = _ROW_HEIGHT[name]
            for cell in row:
                cell.font = _BODY
                cell.alignment = _WRAP
                cell.border = _THIN
                if low:
                    cell.fill = _ORANGE


def _polish_overview(sheet: Worksheet) -> None:
    """Style the briefing sheet.

    Args:
        sheet: Overview worksheet.
    """
    sheet["A1"].font = _TITLE
    sheet.row_dimensions[1].height = 22
    for row in sheet.iter_rows(min_row=3, max_row=sheet.max_row, max_col=2):
        row[0].font = _LABEL
        row[0].alignment = Alignment(vertical="top")
        row[1].font = _BODY
        row[1].alignment = _WRAP
        sheet.row_dimensions[row[0].row].height = 32


def _low_base_row(value: object) -> bool:
    """Tell whether a banner base should be shaded like the example.

    Args:
        value: Count in the n column.

    Returns:
        True when the base is 20 to 29.
    """
    return isinstance(value, int | float) and 20 <= value < 30


def _overview(sheet: Worksheet, spec: TabSpec) -> None:
    """Fill the study briefing.

    Args:
        sheet: Overview worksheet.
        spec: Tab spec.
    """
    defaults = spec.study_defaults
    title = defaults.study_title or spec.spec_id
    minimum = defaults.minimum_unweighted_base_for_display
    weight = defaults.weight_variable
    weighting = (
        f"Weighted by {weight}"
        if weight
        else "None — dataset has no weight variable; all tables unweighted"
    )
    sample = defaults.sample_note or (
        f"n = {defaults.sample_size}" if defaults.sample_size is not None else ""
    )
    sheet["A1"] = f"Crosstab plan — {title}"
    rows = [
        ("Study", title),
        ("Dataset ID", spec.dataset_id or ""),
        ("Sample", sample),
        ("Weighting", weighting),
        (
            "Significance testing",
            "Column proportions, uppercase letters at 95% (alpha 0.05), "
            "lowercase at 90% (alpha 0.10). Tested within each banner group, not against Total.",
        ),
        (
            "Minimum base",
            f"Columns under {minimum} are not tested. "
            "Columns with n 20–29 are flagged '*low base' when the minimum is 20.",
        ),
        (
            "Percentages",
            "Column %, base = respondents shown the question. Means on ordinal scales use the code values shown.",
        ),
        ("Number of tables", "=COUNTA('Table plan'!A:A)-1"),
        ("Banner A (columns incl. Total)", "=COUNTIF('Banner specs'!A:A,\"A\")"),
        ("Banner B (columns incl. Total)", "=COUNTIF('Banner specs'!A:A,\"B\")"),
        ("Derived variables needed", "=COUNTA('Derived variables'!A:A)-1"),
        (
            "Run order",
            "1) Create each derived variable. 2) Run Banner A. 3) Repeat with Banner B. "
            "4) Code open ends before those tables are run.",
        ),
        ("Assumptions to confirm", defaults.assumptions),
    ]
    for offset, (label, value) in enumerate(rows, start=3):
        sheet.cell(offset, 1, label)
        sheet.cell(offset, 2, value)


def _banners(sheet: Worksheet, spec: TabSpec) -> None:
    """Write one row per banner column, including Total.

    Args:
        sheet: Banner specs worksheet.
        spec: Tab spec.
    """
    sheet.append(
        ["Banner", "Col", "Group", "Column label", "Definition", "n", "Low base?", "Variable"]
    )
    grouped: dict[str, list[Banner]] = {"A": [], "B": []}
    for banner in spec.banners:
        grouped.setdefault(banner.plan or "A", []).append(banner)
    sample = spec.study_defaults.sample_size
    for plan in [key for key in ("A", "B") if grouped.get(key)] + [
        key for key in grouped if key not in {"A", "B"} and grouped[key]
    ]:
        sheet.append([plan, "T", "Total", "Total", "All respondents", sample, "", "—"])
        for banner in grouped[plan]:
            note = banner.variable_note or (
                f"{banner.variable_name} (as is)" if banner.variable_name else "—"
            )
            group = banner.group or banner.label
            for category in banner.categories:
                definition = category.definition or (
                    f"{banner.variable_name} = {format_codes(category.codes)}"
                    if banner.variable_name
                    else ""
                )
                sheet.append(
                    [
                        plan,
                        category.letter,
                        group,
                        category.label,
                        definition,
                        category.n,
                        (
                            _low_base_formula(sheet.max_row + 1)
                            if category.n is not None
                            else category.low_base
                        ),
                        note,
                    ]
                )


def _low_base_formula(row: int) -> str:
    """Excel formula that flags a small banner column.

    Args:
        row: 1-based row of the column base.

    Returns:
        Formula. Bases under 20 are not tested. Bases of 20 to 29 are low.
    """
    cell = f"F{row}"
    return f'=IF({cell}<20,"Not tested",IF({cell}<30,"*low base",""))'


def _tables(sheet: Worksheet, spec: TabSpec) -> None:
    """Write one row per table.

    Args:
        sheet: Table plan worksheet.
        spec: Tab spec.
    """
    sheet.append(
        [
            "Table",
            "Section",
            "Variable(s)",
            "Question / table title",
            "Type",
            "Base",
            "Base n",
            "Rows / nets / stats",
            "Banner",
            "Method",
            "Notes",
        ]
    )
    for table in spec.tables:
        plans = table.banner_plans or _plans_from_ids(table, spec.banners)
        sheet.append(
            [
                table.id,
                table.section,
                table.stub_label or ", ".join(table.row_variable_names),
                table.title,
                table.plan_type or _human_type(table.table_type),
                table.base_text or format_expr(table.base.filter),
                table.base_n,
                table.row_instruction or _instruction(table),
                banner_plan_cell(plans),
                table.method or ("crosstab_sig" if table.significance.enabled else "crosstab"),
                " ".join(table.notes),
            ]
        )


def _derived(sheet: Worksheet, spec: TabSpec) -> None:
    """Write derived variables.

    Args:
        sheet: Derived variables worksheet.
        spec: Tab spec.
    """
    sheet.append(["New variable", "Kind", "Source", "Definition", "Purpose"])
    for item in spec.derived_variables:
        sheet.append(
            [item.name, item.kind or item.recipe, item.source, item.definition, item.purpose]
        )


def _skipped(sheet: Worksheet, spec: TabSpec) -> None:
    """Write variables that are not tabulated.

    Args:
        sheet: Not tabbed worksheet.
        spec: Tab spec.
    """
    sheet.append(["Variables", "Reason"])
    for item in spec.exclusions:
        sheet.append([item.get("question_id", ""), item.get("reason", "")])


def _plans_from_ids(table: TableSpec, banners: list[Banner]) -> list[str]:
    """Infer plan letters for a spec that only stored banner ids.

    Args:
        table: Table.
        banners: Banner catalog.

    Returns:
        Plan letters.
    """
    plans: list[str] = []
    by_id = {banner.id: banner for banner in banners}
    for banner_id in table.banner_ids:
        plan = (by_id.get(banner_id).plan if banner_id in by_id else "") or "A"
        if plan not in plans:
            plans.append(plan)
    return plans


def _instruction(table: TableSpec) -> str:
    """Build the rows cell from structured nets and boxes.

    Args:
        table: Table.

    Returns:
        Instruction text.
    """
    parts = ["All codes"]
    for net in table.nets:
        parts.append(f"{net.label} ({format_codes(net.child_codes)})")
    if table.top_box_codes:
        parts.append(f"Top-2 ({format_codes(table.top_box_codes)})")
    if table.bottom_box_codes:
        parts.append(f"Bottom-2 ({format_codes(table.bottom_box_codes)})")
    return "; ".join(parts)


def _human_type(table_type: str) -> str:
    """Map an engine type to the analyst word.

    Args:
        table_type: Engine table type.

    Returns:
        Plan type.
    """
    return {
        "multiple_response": "Multi",
        "numeric": "Single",
        "grid": "Grid item",
    }.get(table_type, "Single")
