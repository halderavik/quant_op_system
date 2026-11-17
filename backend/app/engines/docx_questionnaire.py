"""Read a Word questionnaire as text that keeps punch codes, cells, and programmer colour.

The plain brief reader joins every line of a table cell with spaces and drops
Word's automatic list numbers. For a questionnaire both carry meaning: a cell
holding ``1 / 2 / 99`` lines up with a cell of answer labels, and list numbers
are the punch codes. This reader keeps them:

* automatic list numbers are written in front of the paragraph (``3. Asian``),
* table rows are ``| cell | cell |`` and lines inside a cell are joined with `` // ``,
* red text, which questionnaires use for programming instructions, is wrapped
  in ``[RED: ...]``.
"""

import io
import re
from dataclasses import dataclass, field

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

CELL_BREAK = " // "
_ROMAN = [
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
]
# A question id at the start of a line: S1., Q12a., CAT11_US, C3_DEAT., SEM1.
QUESTION_ID = re.compile(
    r"^(?:\|\s*)?(?:\[RED:\s*)?([A-Z]{1,6}\d{1,3}[A-Za-z]{0,2}(?:_[A-Z][A-Za-z/]*)?)(?:\.|:|\s|$)"
)

# A question numbered only by Word ("1. What is ...?", "9a. Please tell us ...?").
# Answer options rarely end in a question mark or colon, so those two endings mark it.
NUMBERED_QUESTION = re.compile(r"^(\d{1,3}[a-z]?)[.)]\s+(?=.{15,}).*[?:]\s*(?:\[[^\]]*\]\s*)*$")


# An id alone on its line in a camel-case style: qAGE, hType, qCATFREQ. Type markers
# such as SC, MC, or INFONODE have no lower-case prefix and are not matched.
CAMEL_ID = re.compile(r"^([a-z]{1,2}[A-Z][A-Za-z0-9_]{1,24})$")


def question_id_of(text: str) -> str | None:
    """The question id a line starts with: S1, CAT11_US, Q1 for a plain "1. ...?" line, or qAGE alone."""
    stripped = text.strip()
    match = QUESTION_ID.match(stripped)
    if match:
        return match.group(1)
    numbered = NUMBERED_QUESTION.match(stripped)
    if numbered:
        return f"Q{numbered.group(1)}"
    alone = CAMEL_ID.match(stripped)
    return alone.group(1) if alone else None


@dataclass
class _Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = "%1."


@dataclass
class _Numbering:
    """Word list definitions and the running counters."""

    levels: dict[str, dict[int, _Level]] = field(default_factory=dict)  # numId -> ilvl -> level
    abstract_of: dict[str, str] = field(default_factory=dict)
    restarts: set[str] = field(default_factory=set)  # numIds with a start override
    counters: dict[str, dict[int, int]] = field(default_factory=dict)


def questionnaire_text(data: bytes) -> str:
    """Render a .docx questionnaire in body order.

    Args:
        data: File bytes.

    Returns:
        One line per paragraph or table row.
    """
    document = Document(io.BytesIO(data))
    numbering = _load_numbering(document)
    lines: list[str] = []
    for child in document.element.body:
        if child.tag == qn("w:p"):
            text = _paragraph(Paragraph(child, document), numbering)
            if text:
                lines.append(text)
        elif child.tag == qn("w:tbl"):
            lines.append("[TABLE]")
            lines.extend(_table(Table(child, document), numbering))
            lines.append("[/TABLE]")
    return "\n".join(lines)


def question_ids(text: str) -> list[str]:
    """Question ids that start a line or a table row, in order, without repeats.

    Args:
        text: Rendered questionnaire text.

    Returns:
        Ids such as ``S2`` or ``CAT11_US``.
    """
    seen: list[str] = []
    for line in text.splitlines():
        for part in line.split(CELL_BREAK) if line.startswith("|") else [line]:
            found = question_id_of(part)
            if found and found not in seen:
                seen.append(found)
    return seen


def looks_like_questionnaire(text: str) -> bool:
    """Return whether rendered text is a finished questionnaire rather than a brief.

    Args:
        text: Rendered document text.

    Returns:
        True when at least five question ids start lines.
    """
    return len(question_ids(text)) >= 5


def _paragraph(paragraph: Paragraph, numbering: _Numbering) -> str:
    """Paragraph text with its list number and red runs marked."""
    text = _runs_text(paragraph).strip()
    if not text:
        return ""
    prefix = _number(paragraph, numbering)
    return f"{prefix} {text}" if prefix else text


def _runs_text(paragraph: Paragraph) -> str:
    """Join runs, wrapping each stretch of red text in [RED: ...]."""
    parts: list[str] = []
    red_open = False
    for node in paragraph._p.iter(qn("w:r"), qn("w:hyperlink")):
        if node.tag != qn("w:r"):
            continue
        piece = "".join(
            "\t"
            if part.tag == qn("w:tab")
            else ("\n" if part.tag == qn("w:br") else part.text or "")
            for part in node
            if part.tag in {qn("w:t"), qn("w:tab"), qn("w:br")}
        )
        if not piece:
            continue
        red = _is_red(node)
        if red and not red_open and piece.strip():
            parts.append("[RED: ")
            red_open = True
        elif not red and red_open and piece.strip():
            parts.append("]")
            red_open = False
        parts.append(piece)
    if red_open:
        parts.append("]")
    joined = "".join(parts)
    joined = re.sub(r"\[RED: (\s*)\]", r"\1", joined)
    return (
        " ".join(joined.split())
        if "\n" not in joined
        else "\n".join(" ".join(line.split()) for line in joined.split("\n"))
    )


def _is_red(run) -> bool:
    """A run is red when its colour has a strong red channel and weak green and blue."""
    props = run.find(qn("w:rPr"))
    if props is None:
        return False
    color = props.find(qn("w:color"))
    if color is None:
        return False
    value = (color.get(qn("w:val")) or "").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        return False
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return red >= 0x99 and green <= 0x60 and blue <= 0x60


def _table(table: Table, numbering: _Numbering) -> list[str]:
    """Rows as | cell | cell |, then any nested tables."""
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
            texts: list[str] = []
            for child in cell._tc.iterchildren():
                if child.tag == qn("w:p"):
                    text = _paragraph(Paragraph(child, cell), numbering)
                    if text:
                        texts.extend(line for line in text.split("\n") if line.strip())
                elif child.tag == qn("w:tbl"):
                    nested.append(Table(child, cell))
            cells.append(CELL_BREAK.join(texts))
        if any(cells):
            lines.append("| " + " | ".join(cells) + " |")
        for child in nested:
            lines.extend(_table(child, numbering))
    return lines


def _load_numbering(document: DocumentType) -> _Numbering:
    """Read list formats, start values, and overrides from numbering.xml."""
    numbering = _Numbering()
    try:
        root = document.part.numbering_part.element
    except (KeyError, NotImplementedError, AttributeError):
        return numbering
    abstracts: dict[str, dict[int, _Level]] = {}
    for abstract in root.findall(qn("w:abstractNum")):
        abstracts[abstract.get(qn("w:abstractNumId"))] = _levels(abstract)
    for num in root.findall(qn("w:num")):
        num_id = num.get(qn("w:numId"))
        ref = num.find(qn("w:abstractNumId"))
        abstract_id = ref.get(qn("w:val")) if ref is not None else ""
        levels = {
            key: _Level(lv.start, lv.fmt, lv.text)
            for key, lv in abstracts.get(abstract_id, {}).items()
        }
        for override in num.findall(qn("w:lvlOverride")):
            ilvl = int(override.get(qn("w:ilvl")) or 0)
            start = override.find(qn("w:startOverride"))
            level = levels.setdefault(ilvl, _Level())
            if start is not None:
                level.start = int(start.get(qn("w:val")) or 1)
                numbering.restarts.add(num_id)
            replacement = override.find(qn("w:lvl"))
            if replacement is not None:
                levels[ilvl] = _levels_one(replacement, level)
        numbering.levels[num_id] = levels
        numbering.abstract_of[num_id] = abstract_id
    return numbering


def _levels(abstract) -> dict[int, _Level]:
    """Levels of one abstract list."""
    return {
        int(lvl.get(qn("w:ilvl")) or 0): _levels_one(lvl, _Level())
        for lvl in abstract.findall(qn("w:lvl"))
    }


def _levels_one(lvl, base: _Level) -> _Level:
    """One level's start, number format, and label pattern."""
    start = lvl.find(qn("w:start"))
    fmt = lvl.find(qn("w:numFmt"))
    text = lvl.find(qn("w:lvlText"))
    return _Level(
        start=int(start.get(qn("w:val"))) if start is not None else base.start,
        fmt=fmt.get(qn("w:val")) if fmt is not None else base.fmt,
        text=text.get(qn("w:val")) if text is not None else base.text,
    )


def _num_props(paragraph: Paragraph) -> tuple[str, int] | None:
    """numId and level from the paragraph, or from its style chain."""
    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None:
        num_id = p_pr.numPr.numId
        ilvl = p_pr.numPr.ilvl
        if num_id is not None:
            return str(num_id.val), int(ilvl.val) if ilvl is not None else 0
    style = paragraph.style if hasattr(paragraph, "style") else None
    while style is not None:
        props = style.element.pPr
        if props is not None and props.numPr is not None and props.numPr.numId is not None:
            ilvl = props.numPr.ilvl
            return str(props.numPr.numId.val), int(ilvl.val) if ilvl is not None else 0
        style = style.base_style
    return None


def _number(paragraph: Paragraph, numbering: _Numbering) -> str:
    """The list label Word would draw for this paragraph, or ''."""
    props = _num_props(paragraph)
    if props is None:
        return ""
    num_id, ilvl = props
    if num_id == "0" or num_id not in numbering.levels:
        return ""
    levels = numbering.levels[num_id]
    level = levels.get(ilvl, _Level())
    if level.fmt in {"bullet", "none"}:
        return "-" if level.fmt == "bullet" else ""
    # Reason: Word continues one count across lists that share a definition unless
    # the list restarts with a start override.
    key = (
        num_id if num_id in numbering.restarts else f"a{numbering.abstract_of.get(num_id, num_id)}"
    )
    counters = numbering.counters.setdefault(key, {})
    counters[ilvl] = counters.get(ilvl, levels.get(ilvl, _Level()).start - 1) + 1
    for deeper in [k for k in counters if k > ilvl]:
        del counters[deeper]
    label = level.text
    for depth in range(ilvl + 1):
        value = counters.get(depth, levels.get(depth, _Level()).start)
        label = label.replace(f"%{depth + 1}", _format(value, levels.get(depth, _Level()).fmt))
    return label.strip()


def _format(value: int, fmt: str) -> str:
    """Render one counter in Word's number format."""
    if fmt == "lowerLetter":
        return _letters(value).lower()
    if fmt == "upperLetter":
        return _letters(value)
    if fmt in {"lowerRoman", "upperRoman"}:
        roman = _roman(value)
        return roman if fmt == "lowerRoman" else roman.upper()
    return str(value)


def _letters(value: int) -> str:
    """1 -> A, 27 -> AA (Word repeats the letter)."""
    if value < 1:
        return str(value)
    letter = chr(ord("A") + (value - 1) % 26)
    return letter * ((value - 1) // 26 + 1)


def _roman(value: int) -> str:
    """Lower-case roman numeral."""
    out = ""
    for amount, symbol in _ROMAN:
        while value >= amount:
            out += symbol
            value -= amount
    return out
