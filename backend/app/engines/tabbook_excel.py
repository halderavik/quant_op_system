"""Excel export for computed tab books, styled as a stacked crosstab workbook."""

from io import BytesIO

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from app.schemas.crosstab import TabBook, TableResult

_NAVY = "1F4E78"
_GRAY = "E7E6E6"
_ZEBRA = "F2F2F2"
_HEADER = "DEEBF7"
_PERCENT = {"category", "net", "top_box", "bottom_box"}


def export_tabbook(book: TabBook) -> bytes:
    """Write a table of contents and one stacked crosstab sheet.

    Percents, counts, and letters are stored as values. The example workbook
    does not contain Excel formulas.

    Args:
        book: Computed tables and exceptions.

    Returns:
        XLSX bytes.
    """
    workbook = Workbook()
    contents = workbook.active
    contents.title = "Table of Contents"
    crosses = workbook.create_sheet("Crosstabs")
    anchors = _write_tables(crosses, book)
    _write_contents(contents, book, anchors)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _write_contents(sheet, book: TabBook, anchors: list[int]) -> None:
    """Write the methodology lines and the jump list.

    Args:
        sheet: Contents worksheet.
        book: Computed book.
        anchors: Title row of each table on the crosstab sheet.
    """
    width = 4
    _band(
        sheet,
        1,
        width,
        "Crosstab Analysis - Table of Contents",
        size=22,
        fill=_NAVY,
        color="FFFFFF",
    )
    notes = [
        (
            "Test Methodology: Two-tailed Z-test for UNPOOLED proportions was performed "
            "across column groups. Weighted tables do not receive significance letters, "
            "because no survey-design variance was supplied."
        ),
        "Base Skipping: Significance tests are skipped and marked '.' if the column sample size (N) is 30 or less.",
        "Markers: UPPERCASE letters indicate significance at 95% confidence; lowercase letters indicate 90% confidence.",
    ]
    for offset, text in enumerate(notes, start=3):
        cell = sheet.cell(offset, 1, text)
        cell.font = _font(11)
        sheet.merge_cells(start_row=offset, start_column=1, end_row=offset, end_column=width)
    headers = ["S.No", "Variable", "Description", "Go to Table"]
    for index, header in enumerate(headers, start=1):
        cell = sheet.cell(7, index, header)
        cell.font = _font(11, bold=True)
        cell.fill = _fill(_HEADER)
        cell.alignment = Alignment(horizontal="center")
    row = 8
    for number, (table, anchor) in enumerate(zip(book.tables, anchors, strict=True), start=1):
        sheet.cell(row, 1, number).font = _font(11)
        sheet.cell(row, 1).alignment = Alignment(horizontal="center")
        sheet.cell(row, 2, table.table_id).font = _font(11)
        sheet.cell(row, 3, table.title).font = _font(11)
        link = sheet.cell(row, 4, "Jump to Table")
        link.font = Font(name="Calibri", size=11, color="0000FF", underline="single")
        link.hyperlink = f"#Crosstabs!A{anchor}"
        row += 1
    for item in book.exceptions:
        sheet.cell(row, 2, item.get("table_id") or "").font = _font(11)
        sheet.cell(row, 3, item.get("message") or "").font = _font(11)
        row += 1
    if not book.tables and not book.exceptions:
        sheet.cell(row, 3, "No tables were computed.").font = _font(11)
    sheet.column_dimensions["A"].width = 10
    sheet.column_dimensions["B"].width = 24
    sheet.column_dimensions["C"].width = 88
    sheet.column_dimensions["D"].width = 16
    sheet.row_dimensions[1].height = 28


def _write_tables(sheet, book: TabBook) -> list[int]:
    """Stack every table on one sheet.

    Args:
        sheet: Crosstab worksheet.
        book: Computed book.

    Returns:
        Title-row numbers, aligned with ``book.tables``.
    """
    anchors: list[int] = []
    row = 1
    widest = 2
    if not book.tables:
        sheet["A1"] = "No tables were computed."
        sheet["A1"].font = _font(11)
        return anchors
    for table in book.tables:
        anchors.append(row)
        row = _write_table(sheet, row, table)
        widest = max(widest, 1 + len(table.columns))
    sheet.column_dimensions["A"].width = 96
    for index in range(2, widest + 1):
        sheet.column_dimensions[get_column_letter(index)].width = 18
    return anchors


def _write_table(sheet, start: int, table: TableResult) -> int:
    """Write one table as a title, a base line, and percent/count/letter triads.

    Args:
        sheet: Crosstab worksheet.
        start: First row to use.
        table: Computed table.

    Returns:
        The next free row after the separator.
    """
    columns = table.columns or []
    width = max(1 + len(columns), 2)
    _band(sheet, start, width, table.title, size=18, fill=_NAVY, color="FFFFFF")
    _band(sheet, start + 1, width, _base_line(table), size=11, fill=_GRAY, color="000000")
    _paint_row(sheet, start + 2, width, _font(12, bold=True, color="FFFFFF"), _fill(_NAVY))
    sheet.cell(start + 2, 1, "Response Category")
    sheet.cell(start + 2, 2, _banner_name(table))
    header_row = start + 3
    for offset, column in enumerate(columns):
        if column.id == "total" or not column.letter:
            text = column.label
        else:
            text = f"{column.label}\n[{column.letter}]"
        cell = sheet.cell(header_row, 2 + offset, text)
        cell.font = _font(11, color="FFFFFF")
        cell.fill = _fill(_NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[header_row].height = 32
    cursor = header_row + 1
    for position, result_row in enumerate(table.rows):
        shade = _fill(_ZEBRA) if position % 2 == 0 else None
        percent = result_row.row_kind in _PERCENT
        label = sheet.cell(cursor, 1, result_row.label)
        label.font = _font(11, bold=True)
        if shade:
            label.fill = shade
        _value_row(sheet, cursor, columns, result_row, shade, percent)
        _count_row(sheet, cursor + 1, columns, result_row, shade)
        _letter_row(sheet, cursor + 2, columns, result_row)
        cursor += 3
    return cursor + 6


def _paint_row(sheet, row: int, width: int, font: Font, fill: PatternFill) -> None:
    """Paint a row without merging it.

    Args:
        sheet: Worksheet.
        row: Row number.
        width: Column count.
        font: Font applied to each cell.
        fill: Fill applied to each cell.
    """
    for column in range(1, width + 1):
        cell = sheet.cell(row, column)
        cell.font = font
        cell.fill = fill


def _value_row(sheet, row: int, columns, result_row, shade, percent: bool) -> None:
    """Write the percentage or statistic row.

    Args:
        sheet: Worksheet.
        row: Row number.
        columns: Table columns.
        result_row: Result row.
        shade: Optional zebra fill.
        percent: Format the estimate as a percentage when true.
    """
    for offset, column in enumerate(columns):
        cell = result_row.cells.get(column.id)
        target = sheet.cell(row, 2 + offset)
        target.font = _font(11)
        target.alignment = Alignment(horizontal="center")
        if shade:
            target.fill = shade
        if cell is None or cell.estimate is None:
            continue
        if percent:
            target.value = cell.estimate / 100.0
            target.number_format = "0.0%"
        else:
            target.value = cell.estimate
            target.number_format = "0.0"


def _count_row(sheet, row: int, columns, result_row, shade) -> None:
    """Write the unweighted count row.

    Args:
        sheet: Worksheet.
        row: Row number.
        columns: Table columns.
        result_row: Result row.
        shade: Optional zebra fill.
    """
    for offset, column in enumerate(columns):
        cell = result_row.cells.get(column.id)
        target = sheet.cell(row, 2 + offset)
        target.font = _font(11)
        target.alignment = Alignment(horizontal="center")
        if shade:
            target.fill = shade
        if cell is not None and cell.unweighted_numerator is not None:
            target.value = cell.unweighted_numerator
            target.number_format = "#,##0"


def _letter_row(sheet, row: int, columns, result_row) -> None:
    """Write the significance-letter row.

    Args:
        sheet: Worksheet.
        row: Row number.
        columns: Table columns.
        result_row: Result row.
    """
    for offset, column in enumerate(columns):
        cell = result_row.cells.get(column.id)
        target = sheet.cell(row, 2 + offset)
        target.font = _font(11, color="FFFFFF")
        target.fill = _fill(_NAVY)
        target.alignment = Alignment(horizontal="center")
        if cell and cell.significance_letters:
            target.value = cell.significance_letters


def _base_line(table: TableResult) -> str:
    """Describe the table base in one line.

    Args:
        table: Computed table.

    Returns:
        Base line such as ``N=100 | Gender | Unweighted``.
    """
    total = next((column for column in table.columns if column.id == "total"), None)
    probe = total or (table.columns[0] if table.columns else None)
    base: int | None = None
    if probe and table.rows:
        cell = table.rows[0].cells.get(probe.id)
        if cell is not None:
            base = cell.unweighted_base
    weight = "Weighted" if table.weight_variable else "Unweighted"
    shown = base if base is not None else "—"
    return f"N={shown} | {_banner_name(table)} | {weight}"


def _banner_name(table: TableResult) -> str:
    """Return the banner id stamped on the column ids.

    Args:
        table: Computed table.

    Returns:
        Banner name, or ``Total`` when the table has no banner.
    """
    names: list[str] = []
    for column in table.columns:
        if column.id == "total" or ":" not in column.id:
            continue
        name = column.id.split(":", 1)[0]
        if name not in names:
            names.append(name)
    return ", ".join(names) if names else "Total"


def _band(sheet, row: int, width: int, text: str, *, size: int, fill: str, color: str) -> None:
    """Merge a row and paint it as a title or base band.

    Args:
        sheet: Worksheet.
        row: Row number.
        width: Column count.
        text: Band text.
        size: Font size.
        fill: Fill color.
        color: Font color.
    """
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
    paint = _fill(fill)
    font = _font(size, bold=True, color=color)
    for column in range(1, width + 1):
        cell = sheet.cell(row, column)
        cell.fill = paint
        cell.font = font
    sheet.cell(row, 1).value = text


def _font(size: int, *, bold: bool = False, color: str = "000000") -> Font:
    """Return a Calibri font.

    Args:
        size: Point size.
        bold: Bold when true.
        color: RGB hex without a leading hash.

    Returns:
        Font.
    """
    return Font(name="Calibri", size=size, bold=bold, color=color)


def _fill(color: str) -> PatternFill:
    """Return a solid fill.

    Args:
        color: RGB hex without a leading hash.

    Returns:
        Fill.
    """
    return PatternFill("solid", fgColor=color)
