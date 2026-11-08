"""Parse a supplied codeframe from JSON, CSV, or a simple workbook."""

from __future__ import annotations

import csv
import io
import json

from openpyxl import load_workbook
from pydantic import BaseModel, Field

from app.errors import AppError
from app.schemas.coding import Codeframe, CodeNode, NetNode

_KNOWN = {
    "id",
    "label",
    "parent_id",
    "definition",
    "include_examples",
    "exclude_examples",
    "child_ids",
    "response_variable",
    "respondent_id_variable",
    "value",
}


class ParsedCodeframe(BaseModel):
    """A codeframe plus columns the parser did not apply."""

    codeframe: Codeframe
    ignored_columns: list[str] = Field(default_factory=list)


def parse_codeframe_bytes(
    filename: str,
    payload: bytes,
    *,
    response_variable: str = "response",
    respondent_id_variable: str = "respondent_id",
) -> ParsedCodeframe:
    """Parse JSON, CSV, or XLSX bytes into a codeframe.

    Args:
        filename: Original filename. The suffix selects the parser.
        payload: File bytes.
        response_variable: Default open-end column when the file omits one.
        respondent_id_variable: Default respondent id column.

    Returns:
        Parsed frame and any ignored columns.

    Raises:
        AppError: When the file type or the table is unusable.
    """
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "json":
        return _from_json(payload, response_variable, respondent_id_variable)
    if suffix == "csv":
        return _from_rows(_csv_rows(payload), response_variable, respondent_id_variable)
    if suffix == "xlsx":
        return _from_xlsx(payload, response_variable, respondent_id_variable)
    raise AppError("Codeframes can be imported from JSON, CSV, or XLSX.", "unsupported_file")


def _from_json(
    payload: bytes, response_variable: str, respondent_id_variable: str
) -> ParsedCodeframe:
    """Parse a JSON object.

    Args:
        payload: JSON bytes.
        response_variable: Default open-end column.
        respondent_id_variable: Default respondent id column.

    Returns:
        Parsed frame.
    """
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError("The codeframe JSON could not be read.", "bad_codeframe") from exc
    if not isinstance(raw, dict):
        raise AppError("The codeframe JSON must be an object.", "bad_codeframe")
    ignored = sorted(
        key
        for key in raw
        if key not in _KNOWN
        and key
        not in {
            "codes",
            "nets",
            "codeframe_id",
            "version",
            "allow_multiple_codes",
            "sentiment",
            "placeholders",
            "weight_variable",
        }
    )
    body = dict(raw)
    body.setdefault("response_variable", response_variable)
    body.setdefault("respondent_id_variable", respondent_id_variable)
    body.setdefault("codeframe_id", "cf-import")
    try:
        frame = Codeframe.model_validate(body)
    except Exception as exc:
        raise AppError(
            "The codeframe JSON does not match the codeframe schema.", "bad_codeframe"
        ) from exc
    return ParsedCodeframe(codeframe=frame, ignored_columns=ignored)


def _csv_rows(payload: bytes) -> list[dict[str, str]]:
    """Read a CSV into row dictionaries.

    Args:
        payload: CSV bytes.

    Returns:
        Rows keyed by header.
    """
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise AppError("The codeframe CSV needs a header row.", "bad_codeframe")
    return [dict(row) for row in reader]


def _from_xlsx(
    payload: bytes, response_variable: str, respondent_id_variable: str
) -> ParsedCodeframe:
    """Read the first sheet, plus a sheet named nets when present.

    Args:
        payload: Workbook bytes.
        response_variable: Default open-end column.
        respondent_id_variable: Default respondent id column.

    Returns:
        Parsed frame.
    """
    book = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    if not book.worksheets:
        raise AppError("The workbook has no sheets.", "bad_codeframe")
    parsed = _from_rows(_sheet_rows(book.worksheets[0]), response_variable, respondent_id_variable)
    nets_sheet = next((sheet for sheet in book.worksheets if sheet.title.lower() == "nets"), None)
    if nets_sheet is None:
        return parsed
    extra = _from_rows(_sheet_rows(nets_sheet), response_variable, respondent_id_variable)
    frame = parsed.codeframe.model_copy(deep=True)
    frame.nets = list(frame.nets) + list(extra.codeframe.nets)
    ignored = sorted(set(parsed.ignored_columns + extra.ignored_columns))
    return ParsedCodeframe(codeframe=frame, ignored_columns=ignored)


def _sheet_rows(sheet: object) -> list[dict[str, str]]:
    """Convert a worksheet to row dictionaries.

    Args:
        sheet: Openpyxl worksheet.

    Returns:
        Rows.
    """
    rows = list(sheet.iter_rows(values_only=True))  # type: ignore[attr-defined]
    if not rows:
        raise AppError("The codeframe sheet is empty.", "bad_codeframe")
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    if "id" not in headers:
        raise AppError("The codeframe sheet needs an id column.", "bad_codeframe")
    parsed: list[dict[str, str]] = []
    for raw in rows[1:]:
        if raw is None or all(cell is None or str(cell).strip() == "" for cell in raw):
            continue
        item: dict[str, str] = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            value = raw[index] if index < len(raw) else ""
            item[header] = "" if value is None else str(value)
        parsed.append(item)
    return parsed


def _from_rows(
    rows: list[dict[str, str]], response_variable: str, respondent_id_variable: str
) -> ParsedCodeframe:
    """Build codes and nets from tabular rows.

    Args:
        rows: Header-keyed rows.
        response_variable: Default open-end column.
        respondent_id_variable: Default respondent id column.

    Returns:
        Parsed frame.
    """
    if not rows:
        raise AppError("The codeframe file has no rows.", "bad_codeframe")
    ignored = sorted({key for row in rows for key in row if key and key not in _KNOWN})
    codes: list[CodeNode] = []
    nets: list[NetNode] = []
    response = response_variable
    respondent = respondent_id_variable
    for row in rows:
        if row.get("response_variable"):
            response = row["response_variable"].strip()
        if row.get("respondent_id_variable"):
            respondent = row["respondent_id_variable"].strip()
        code_id = (row.get("id") or "").strip()
        label = (row.get("label") or code_id).strip()
        if not code_id:
            continue
        children = _parts(row.get("child_ids") or "")
        if children:
            nets.append(NetNode(id=code_id, label=label, child_ids=children))
            continue
        codes.append(
            CodeNode(
                id=code_id,
                label=label,
                value=_optional_int(row.get("value") or ""),
                parent_id=(row.get("parent_id") or "").strip() or None,
                definition=(row.get("definition") or "").strip(),
                include_examples=_parts(row.get("include_examples") or ""),
                exclude_examples=_parts(row.get("exclude_examples") or ""),
            )
        )
    if not codes:
        raise AppError("The codeframe file has no codes.", "bad_codeframe")
    frame = Codeframe(
        codeframe_id="cf-import",
        response_variable=response,
        respondent_id_variable=respondent,
        codes=codes,
        nets=nets,
    )
    return ParsedCodeframe(codeframe=frame, ignored_columns=ignored)


def _optional_int(value: str) -> int | None:
    """Parse a numeric punch, or return None when the cell is blank.

    Args:
        value: Cell text.

    Returns:
        Integer punch, or None.
    """
    text = value.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parts(value: str) -> list[str]:
    """Split a pipe-separated cell.

    Args:
        value: Cell text.

    Returns:
        Non-empty parts.
    """
    return [part.strip() for part in str(value).split("|") if part.strip()]
