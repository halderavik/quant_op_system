"""Excel workbook for a fraud recommendation."""

from io import BytesIO

from openpyxl import Workbook, load_workbook

from app.schemas.cleaning import CleaningReport
from app.schemas.common import ValidationCheck


def export_cleaning(report: CleaningReport) -> bytes:
    """Write the rules, the counts, every respondent, and the open-end exceptions.

    Args:
        report: Recommendation.

    Returns:
        XLSX bytes.
    """
    book = Workbook()
    _rules(book, report)
    _summary(book, report)
    _respondents(book, report)
    _open_ends(book, report)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def workbook_row_check(payload: bytes, row_count: int) -> ValidationCheck:
    """Check that the respondent sheet has one data row per respondent.

    Args:
        payload: Workbook bytes.
        row_count: Expected respondent count.

    Returns:
        Pass or fail check.
    """
    found = _respondent_rows(payload)
    return ValidationCheck(
        id="workbook_rows",
        status="passed" if found == row_count else "failed",
        details=f"Workbook respondents {found}; dataset rows {row_count}.",
    )


def _respondent_rows(payload: bytes) -> int:
    """Count data rows on the Respondents sheet.

    Args:
        payload: Workbook bytes.

    Returns:
        Data rows. The header is not counted.
    """
    book = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    try:
        sheet = book["Respondents"]
        found = 0
        for index, row in enumerate(sheet.iter_rows(values_only=True)):
            if index == 0 or row[0] is None:
                continue
            found += 1
        return found
    finally:
        book.close()


def _rules(book: Workbook, report: CleaningReport) -> None:
    """Write the rule catalog.

    Args:
        book: Workbook. The active sheet is reused.
        report: Recommendation.
    """
    sheet = book.active
    sheet.title = "Rules"
    sheet.append(["Rule", "Label", "Severity", "Ran", "Skip reason", "Definition"])
    for rule in report.rules:
        sheet.append(
            [
                rule.id,
                rule.label,
                rule.severity,
                "yes" if rule.ran else "no",
                rule.skip_reason,
                rule.definition,
            ]
        )


def _summary(book: Workbook, report: CleaningReport) -> None:
    """Write the count sheet.

    Args:
        book: Workbook.
        report: Recommendation.
    """
    sheet = book.create_sheet("Summary")
    summary = report.summary
    rows = [
        ("Respondents", summary.row_count),
        ("Keep", summary.keep_n),
        ("Review", summary.review_n),
        ("Remove", summary.remove_n),
        ("Weight variable", summary.weight_variable or ""),
        ("Weighted remove share", summary.weighted_remove_share),
        ("Weighted review share", summary.weighted_review_share),
        ("Semantic review", summary.semantic_review),
        ("Not run", "; ".join(summary.skipped)),
    ]
    sheet.append(["Metric", "Value"])
    for name, value in rows:
        sheet.append([name, value])
    sheet.append([])
    sheet.append(["Rule", "Respondents"])
    for rule_id, count in sorted(summary.rule_counts.items()):
        sheet.append([rule_id, count])


def _respondents(book: Workbook, report: CleaningReport) -> None:
    """Write one row per respondent.

    Args:
        book: Workbook.
        report: Recommendation.
    """
    sheet = book.create_sheet("Respondents")
    sheet.append(["Row", "Respondent id", "Disposition", "Rules", "Details"])
    for row in report.respondents:
        sheet.append(
            [
                row.source_row_id,
                row.respondent_id,
                row.disposition,
                ", ".join(row.rule_ids),
                " | ".join(flag.detail for flag in row.flags),
            ]
        )


def _open_ends(book: Workbook, report: CleaningReport) -> None:
    """Write the open-end exception list.

    Args:
        book: Workbook.
        report: Recommendation.
    """
    sheet = book.create_sheet("Open ends")
    sheet.append(["Row", "Respondent id", "Variable", "Preview", "Rule", "Detail", "Model label"])
    for finding in report.open_ends:
        sheet.append(
            [
                finding.source_row_id,
                finding.respondent_id,
                finding.variable,
                finding.text_preview,
                finding.rule_id,
                finding.detail,
                finding.model_label or "",
            ]
        )
