"""Export a codeframe and punches in the coded-data workbook layout."""

from io import BytesIO

import pandas as pd
import pyreadstat
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.engines.coding_agg import final_codes, final_sentiment
from app.schemas.coding import Codeframe, CodeNode, CodingAssignment, CodingReport, NetNode


def export_coding_workbook(
    codeframe: Codeframe,
    assignments: list[CodingAssignment],
    report: CodingReport,
) -> bytes:
    """Write coded punches and one codeframe sheet per open end.

    Counts and frequencies are Excel formulas against ``Coded_Data``.
    A Review sheet is included only when a row is flagged for a person.

    Args:
        codeframe: Approved frame.
        assignments: Row assignments.
        report: Frequency report. The substantive count is written as a label.

    Returns:
        XLSX bytes.
    """
    book = Workbook()
    coded = book.active
    coded.title = "Coded_Data"
    punches = _punches(codeframe.codes)
    width = max((len(final_codes(row)) for row in assignments), default=1)
    headers = [codeframe.respondent_id_variable, codeframe.response_variable]
    headers.extend(f"{codeframe.response_variable}_Code{index}" for index in range(1, width + 1))
    coded.append(headers)
    for row in sorted(assignments, key=lambda item: item.source_row_id):
        values: list[object] = [row.respondent_id, row.response_text if row.substantive else ""]
        applied = [punches[code_id] for code_id in final_codes(row) if code_id in punches]
        values.extend(applied)
        values.extend([None] * (width - len(applied)))
        coded.append(values)
    for cell in coded[1]:
        cell.font = Font(name="Calibri", bold=True)
    _codeframe_sheet(book, codeframe, punches, width, report)
    review_rows = [row for row in assignments if row.review_required]
    if review_rows:
        review = book.create_sheet("Review")
        review.append(["record", "response_text", "codes", "sentiment", "review_reason"])
        for row in review_rows:
            applied = [str(punches[code_id]) for code_id in final_codes(row) if code_id in punches]
            review.append(
                [
                    row.respondent_id,
                    row.response_text,
                    " ".join(applied),
                    final_sentiment(row) or "",
                    row.review_reason or "",
                ]
            )
        for cell in review[1]:
            cell.font = Font(name="Calibri", bold=True)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def export_coding_sav(
    source: pd.DataFrame,
    codeframe: Codeframe,
    assignments: list[CodingAssignment],
    destination: str,
) -> None:
    """Append coding indicators to a copy of the source data and write SPSS.

    Args:
        source: Original respondent data.
        codeframe: Codeframe.
        assignments: Assignments aligned by ``source_row_id`` position.
        destination: Output path.
    """
    frame = source.copy()
    by_row = {row.source_row_id: row for row in assignments}
    column_labels = [str(name) for name in frame.columns]
    value_labels: dict[str, dict[int, str]] = {}
    for code in codeframe.codes:
        column_name = f"CODE_{code.id}"
        column = []
        for position in range(len(frame)):
            row = by_row.get(position)
            column.append(1 if row and code.id in final_codes(row) else 0)
        frame[column_name] = column
        column_labels.append(f"Code: {code.label}")
        value_labels[column_name] = {0: "Not applied", 1: "Applied"}
    pyreadstat.write_sav(
        frame,
        destination,
        column_labels=column_labels,
        variable_value_labels=value_labels,
    )


def _codeframe_sheet(
    book: Workbook,
    codeframe: Codeframe,
    punches: dict[str, int],
    width: int,
    report: CodingReport,
) -> None:
    """Write the Net / Code value / Code text / Counts / Frequency sheet.

    Args:
        book: Workbook.
        codeframe: Approved frame.
        punches: Code id to numeric punch.
        width: Number of punch columns on ``Coded_Data``.
        report: Frequency report used for the substantive label.
    """
    sheet = book.create_sheet(_sheet_name(codeframe.response_variable))
    bold = Font(name="Calibri", bold=True, size=11)
    plain = Font(name="Calibri", size=11)
    sheet["A3"] = f"{codeframe.response_variable}: open-end codeframe"
    sheet["A3"].font = bold
    sheet["A4"] = f"Substantive base ({report.substantive_n} in the saved report)"
    sheet["A4"].font = plain
    sheet["B4"] = "=COUNTA(Coded_Data!B:B)-1"
    sheet["B4"].font = plain
    headers = ["Net", "Code value", "Code text", "Counts", "Frequency"]
    for index, header in enumerate(headers, start=1):
        cell = sheet.cell(5, index, header)
        cell.font = bold
    by_id = {code.id: code for code in codeframe.codes}
    placed: set[str] = set()
    groups = list(codeframe.nets)
    loose = [
        code.id for code in codeframe.codes if not any(code.id in net.child_ids for net in groups)
    ]
    if loose:
        groups.append(NetNode(id="other", label="OTHER CODES (NET)", child_ids=loose))
    if not groups:
        groups.append(
            NetNode(
                id="codes", label="CODES (NET)", child_ids=[code.id for code in codeframe.codes]
            )
        )
    row = 7
    for net in groups:
        label = net.label if _net_label(net.label) else f"{net.label} (NET)"
        sheet.cell(row, 1, label).font = bold
        row += 1
        for child_id in net.child_ids:
            if child_id in placed or child_id not in by_id:
                continue
            placed.add(child_id)
            code = by_id[child_id]
            sheet.cell(row, 2, punches[code.id]).font = plain
            sheet.cell(row, 3, code.label).font = plain
            sheet.cell(row, 4, _count_formula(row, width)).font = plain
            frequency = sheet.cell(row, 5, f'=IF($B$4=0,"",D{row}/$B$4)')
            frequency.font = plain
            frequency.number_format = "0%"
            row += 1
        row += 1
    sheet.column_dimensions["A"].width = 48
    sheet.column_dimensions["B"].width = 12
    sheet.column_dimensions["C"].width = 46
    sheet.column_dimensions["D"].width = 12
    sheet.column_dimensions["E"].width = 12


def _count_formula(row: int, width: int) -> str:
    """Count a punch across the coded-data punch columns.

    Args:
        row: Codeframe row whose column B holds the punch.
        width: Number of punch columns.

    Returns:
        SUM of COUNTIF formulas.
    """
    parts = []
    for offset in range(width):
        column = get_column_letter(3 + offset)
        parts.append(f"COUNTIF(Coded_Data!{column}:{column},B{row})")
    return "=" + "+".join(parts)


def _punches(codes: list[CodeNode]) -> dict[str, int]:
    """Assign a unique integer punch to every code.

    Args:
        codes: Codeframe codes.

    Returns:
        Code id to punch.
    """
    used: set[int] = set()
    result: dict[str, int] = {}
    for index, code in enumerate(codes, start=1):
        candidate = code.value
        if candidate is None:
            digits = "".join(character for character in code.id if character.isdigit())
            candidate = int(digits) if digits else index
        while candidate in used:
            candidate += 1
        used.add(int(candidate))
        result[code.id] = int(candidate)
    return result


def _net_label(label: str) -> bool:
    """Return whether a net label already carries a net suffix.

    Args:
        label: Net label.

    Returns:
        True when the label already ends with a net marker.
    """
    folded = label.upper()
    return (
        folded.endswith("(NET)") or folded.endswith("(SUBNET)") or folded.endswith("(SUB-SUBNET)")
    )


def _sheet_name(variable: str) -> str:
    """Return a legal Excel sheet name for one open end.

    Args:
        variable: Response variable name.

    Returns:
        Sheet name of at most 31 characters.
    """
    cleaned = "".join(character if character not in "[]:*?/\\" else "_" for character in variable)
    return f"Codeframe_{cleaned}"[:31]
