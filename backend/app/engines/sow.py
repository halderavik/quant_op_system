"""Extract plain text and objective lines from study materials."""

from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from app.errors import AppError
from app.schemas.questionnaire import StudyBrief


def extract_brief(path: Path, filename: str) -> StudyBrief:
    """Read a SOW file into text and simple objective lines.

    Args:
        path: File on disk.
        filename: Original filename used to choose a parser.

    Returns:
        Study brief. Instructions inside the file are data, not system policy.
    """
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8")
        elif suffix == ".docx":
            text = docx_plain_text(Document(str(path)))
        elif suffix == ".pdf":
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            raise AppError(
                "Upload a PDF, DOCX, TXT, or Markdown statement of work.",
                "unsupported_file",
            )
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            "The document could not be read. Check that the file is not corrupt.",
            "bad_document",
        ) from exc
    return StudyBrief(
        source_name=filename,
        text=text,
        objectives=_objectives(text),
        audience=_line_after(text, "audience"),
        method_notes=_method_notes(text),
    )


def extract_brief_bytes(data: bytes, filename: str) -> StudyBrief:
    """Extract a brief from in-memory bytes.

    Args:
        data: File bytes.
        filename: Original filename.

    Returns:
        Study brief.
    """
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".txt", ".md", ".json"}:
            text = data.decode("utf-8")
            return StudyBrief(
                source_name=filename,
                text=text,
                objectives=_objectives(text),
            )
        buffer = BytesIO(data)
        if suffix == ".docx":
            text = docx_plain_text(Document(buffer))
            return StudyBrief(source_name=filename, text=text, objectives=_objectives(text))
        if suffix == ".pdf":
            reader = PdfReader(buffer)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return StudyBrief(source_name=filename, text=text, objectives=_objectives(text))
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            "The document could not be read. Check that the file is not corrupt.",
            "bad_document",
        ) from exc
    raise AppError("Upload a PDF, DOCX, TXT, or Markdown statement of work.", "unsupported_file")


def docx_plain_text(document: Document) -> str:
    """Read a DOCX in body order, including table rows.

    Args:
        document: Parsed Word document.

    Returns:
        Paragraphs and table rows. Repeated merged cells in a row are kept once.
    """
    lines: list[str] = []
    for child in document.element.body:
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            if text:
                lines.append(text)
        elif child.tag == qn("w:tbl"):
            lines.extend(_table_lines(Table(child, document)))
    return "\n".join(lines)


def _table_lines(table: Table) -> list[str]:
    """Render one table, then any nested tables, as pipe-separated rows.

    Args:
        table: Word table.

    Returns:
        Non-empty rows.
    """
    lines: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        nested: list[Table] = []
        seen: set[int] = set()
        for cell in row.cells:
            # Reason: a horizontal merge repeats the same cell element across grid columns.
            key = id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            text = " ".join(cell.text.split())
            if text:
                cells.append(text)
            nested.extend(cell.tables)
        if cells:
            lines.append(" | ".join(cells))
        for child in nested:
            lines.extend(_table_lines(child))
    return lines


def _objectives(text: str) -> list[str]:
    """Collect bullet lines and lines that start with 'Objective'.

    Args:
        text: Document text.

    Returns:
        Objective strings.
    """
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*").strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("objective") or raw.strip().startswith(("-", "*")):
            cleaned = line.split(":", 1)[-1].strip() if lower.startswith("objective") else line
            if cleaned and cleaned.lower() not in {"objectives", "objective"}:
                found.append(cleaned)
    return found


def _line_after(text: str, label: str) -> str | None:
    """Return the text after a ``label:`` prefix.

    Args:
        text: Document text.
        label: Prefix to find.

    Returns:
        Remainder of the matching line, if any.
    """
    for raw in text.splitlines():
        if raw.lower().strip().startswith(label):
            parts = raw.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return None


def _method_notes(text: str) -> list[str]:
    """Collect methodology lines.

    Args:
        text: Document text.

    Returns:
        Notes.
    """
    notes = []
    for raw in text.splitlines():
        lower = raw.lower()
        if "eligib" in lower or "quota" in lower or "method" in lower or "sample" in lower:
            notes.append(raw.strip())
    return notes
