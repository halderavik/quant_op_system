"""Export a questionnaire to PDF with the same sections as the DOCX."""

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.engines.qexport import (
    _RULE as _PROGRAMMING_RULE,
)
from app.engines.qexport import (
    _option_label,
    _programmer_lines,
    _respondent_instruction,
    _sections,
)
from app.errors import AppError
from app.schemas.questionnaire import Question, Questionnaire

_BLUE = (4, 50, 255)
_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"


def to_pdf(document: Questionnaire) -> bytes:
    """Render a PDF instrument with programming notes in blue.

    Args:
        document: Questionnaire.

    Returns:
        PDF bytes.
    """
    pdf = _document()
    pdf.add_page()
    _heading(pdf, document.title, 18)
    _body(pdf, document.estimated_minutes_note)
    if document.objectives:
        _heading(pdf, "Objectives", 14)
        for objective in document.objectives:
            _body(pdf, f"{objective.id}: {objective.description}")
    if document.sample_notes:
        _heading(pdf, "Sample and quotas", 14)
        for note in document.sample_notes:
            _body(pdf, note)
    _heading(pdf, "Programming instructions", 14)
    _note(pdf, _PROGRAMMING_RULE)
    for note in document.programming_notes:
        _note(pdf, note)
    if document.modules:
        _heading(pdf, "Outline", 14)
        for module in document.modules:
            _body(pdf, module.title)
    for title, questions in _sections(document):
        _heading(pdf, title, 14)
        for question in questions:
            _question(pdf, question)
    return bytes(pdf.output())


def _document() -> FPDF:
    """Open an A4 document using the vendored DejaVu fonts.

    Returns:
        PDF document with Unicode fonts registered.
    """
    pdf = FPDF(format="A4", unit="mm")
    pdf.add_font("DejaVu", "", str(_font("DejaVuSans.ttf")))
    pdf.add_font("DejaVu", "B", str(_font("DejaVuSans-Bold.ttf")))
    pdf.add_font("DejaVu", "I", str(_font("DejaVuSans-Oblique.ttf")))
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    return pdf


def _font(name: str) -> Path:
    """Return one vendored font file.

    Args:
        name: Font filename.

    Returns:
        Absolute path.

    Raises:
        AppError: The font file is not installed with the app.
    """
    path = _FONT_DIR / name
    if not path.is_file():
        raise AppError("The PDF font is missing from the server install.", "export_missing")
    return path


def _question(pdf: FPDF, question: Question) -> None:
    """Add one question, its answers, and its programming notes.

    Args:
        pdf: Document being built.
        question: Question.
    """
    _heading(pdf, f"{question.id}. {question.text}", 12)
    instruction = _respondent_instruction(question)
    if instruction:
        _body(pdf, instruction)
    if question.type in {"grid", "matrix"} and question.matrix_items and question.options:
        scale = " | ".join(f"{option.code}. {option.label}" for option in question.options)
        _body(pdf, scale)
        for item in question.matrix_items:
            _body(pdf, item)
    elif question.options:
        for option in question.options:
            _body(pdf, f"{option.code}. {_option_label(option)}")
    for note in _programmer_lines(question):
        _note(pdf, note)


def _heading(pdf: FPDF, text: str, size: int) -> None:
    """Write a bold heading.

    Args:
        pdf: Document being built.
        text: Heading text.
        size: Font size in points.
    """
    pdf.ln(2)
    _line(pdf, text, size=size, style="B")


def _body(pdf: FPDF, text: str) -> None:
    """Write one black paragraph.

    Args:
        pdf: Document being built.
        text: Paragraph text.
    """
    if text:
        _line(pdf, text, size=11, style="")


def _note(pdf: FPDF, text: str) -> None:
    """Write one programming note in blue.

    Args:
        pdf: Document being built.
        text: Note text.
    """
    if text:
        _line(pdf, text, size=10, style="I", color=_BLUE)


def _line(
    pdf: FPDF,
    text: str,
    *,
    size: int,
    style: str,
    color: tuple[int, int, int] = (0, 0, 0),
) -> None:
    """Write wrapping text and restore black body type.

    Args:
        pdf: Document being built.
        text: Paragraph text.
        size: Font size in points.
        style: Empty, ``B``, or ``I``.
        color: RGB color.
    """
    pdf.set_text_color(*color)
    pdf.set_font("DejaVu", style, size)
    pdf.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "", 11)
