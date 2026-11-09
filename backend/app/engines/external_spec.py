"""Detect non-canonical tab-spec workbooks and refuse ambiguous mappings."""

from io import BytesIO
from typing import Any

from openpyxl import Workbook, load_workbook

from app.engines.tabspec_analyst import ANALYST_SHEETS
from app.engines.tabspec_excel import _SHEETS
from app.errors import AppError
from app.schemas.tabspec import ExternalMappingPreview

_ALT_REQUIRED = {
    "table_id": ["tableid", "table_id", "id"],
    "title": ["title", "table_title"],
    "stub": ["stub", "row", "rows", "question"],
    "banner": ["banner", "column", "banner_var"],
}
_SIG_ALIASES = ["sig_letters", "significance_letters", "sig_letter_map", "letters"]


def preview_external(data: bytes) -> ExternalMappingPreview:
    """Inspect a workbook and describe the mapping. Do not compute tables.

    Args:
        data: XLSX or CSV bytes. CSV is accepted when it has a header row.

    Returns:
        Mapping preview. Low confidence sets ``requires_confirmation``.
    """
    if data[:2] == b"PK" or data[:1] == b"P":
        return _preview_xlsx(data)
    text = data.decode("utf-8", errors="replace")
    header = [part.strip().lower() for part in text.splitlines()[0].split(",")]
    return _from_headers(header, "csv", [])


def _preview_xlsx(data: bytes) -> ExternalMappingPreview:
    """Inspect the first sheet, or recognise the canonical workbook.

    Args:
        data: XLSX bytes.

    Returns:
        Mapping preview.
    """
    try:
        book = load_workbook(BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:
        raise AppError("The workbook could not be opened.", "bad_workbook") from exc
    if all(name in book.sheetnames for name in _SHEETS):
        return ExternalMappingPreview(
            format_id="canonical",
            mapping_confidence="high",
            mapped_fields={name: name for name in _SHEETS},
            requires_confirmation=False,
        )
    if all(name in book.sheetnames for name in ANALYST_SHEETS):
        return ExternalMappingPreview(
            format_id="analyst",
            mapping_confidence="high",
            mapped_fields={name: name for name in ANALYST_SHEETS},
            requires_confirmation=False,
        )
    sheet = book[book.sheetnames[0]]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise AppError("The workbook has no rows.", "bad_workbook")
    header = [str(cell).strip().lower() if cell is not None else "" for cell in rows[0]]
    return _from_headers(header, "xlsx_table", [str(cell) for cell in rows[0]])


def _from_headers(header: list[str], format_id: str, original: list[str]) -> ExternalMappingPreview:
    """Map known headers and flag ambiguous significance columns.

    Args:
        header: Lower-cased headers.
        format_id: Detected format id.
        original: Original header labels.

    Returns:
        Preview. Ambiguous significance columns require confirmation.
    """
    mapped: dict[str, str] = {}
    for field, aliases in _ALT_REQUIRED.items():
        match = next((name for name in header if name in aliases), None)
        if match:
            mapped[field] = match
    unmapped = [name for name in header if name and name not in mapped.values()]
    sig_hits = [name for name in header if name in _SIG_ALIASES or "sig" in name]
    warnings: list[str] = []
    unsupported: list[str] = []
    requires = False
    confidence: Any = "high"
    if len(sig_hits) > 1:
        requires = True
        confidence = "low"
        warnings.append(
            "More than one significance-letter column was found. "
            "Review the mapping before execution. No tables have been computed."
        )
        unsupported.extend(sig_hits)
    if len(mapped) < len(_ALT_REQUIRED):
        requires = True
        confidence = "low"
        warnings.append("Some required table fields could not be mapped.")
    return ExternalMappingPreview(
        format_id=format_id if mapped else "unknown",
        mapping_confidence=confidence,
        mapped_fields=mapped,
        unmapped_fields=unmapped,
        warnings=warnings,
        requires_confirmation=requires,
        unsupported_entries=unsupported,
        tables=[{"headers": original or header}],
    )


def external_workbook(headers: list[str], rows: list[list[Any]]) -> bytes:
    """Build a simple one-sheet workbook for tests and fixtures.

    Args:
        headers: Column titles.
        rows: Data rows.

    Returns:
        XLSX bytes.
    """
    book = Workbook()
    sheet = book.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()
