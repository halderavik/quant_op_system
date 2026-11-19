"""Check that an imported questionnaire uses the source file's exact words, ids, order, and codes.

Text matches when its words and punctuation appear in the same order, with
nothing between them, somewhere in the source. Quote style, dash style, spacing,
brackets, table cell breaks, and red (programmer) text in between are ignored,
so "Finished reading a book (in either print ...)" still matches a source that
has a red ``[US/DE/AT/BR]`` tag inside it.
"""

import re
from dataclasses import dataclass, field

from app.engines.docx_questionnaire import CELL_BREAK, question_id_of
from app.schemas.questionnaire import Question, Questionnaire

_TRANSLATE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "…": "...",
        " ": " ",
    }
)
_IGNORED = {"[", "]", "|", "'", '"', "*", "_", "-", "•"}
_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_RED = re.compile(r"\[RED: ([^\]]*(?:\[[^\]]*\][^\]]*)*)\]")
_CAPS_TAG = re.compile(r"\[(?:PN:[^\]]*|[^\]a-z]*)\]")
_CODES_ONLY = re.compile(r"^[\s\d/.|\[\]-]+$")


@dataclass
class FidelityReport:
    """What did not match the source, by question id ("" for survey-level notes)."""

    issues: dict[str, list[str]] = field(default_factory=dict)
    checked: int = 0

    def add(self, key: str, message: str) -> None:
        """Record one problem."""
        self.issues.setdefault(key, []).append(message)

    @property
    def ok(self) -> bool:
        """True when nothing failed."""
        return not self.issues

    def messages(self, limit: int | None = None) -> list[str]:
        """Flat list of problems."""
        flat = [message for items in self.issues.values() for message in items]
        return flat[:limit] if limit else flat


def tokens(text: str) -> list[str]:
    """Words and punctuation, normalised for comparison."""
    text = text.translate(_TRANSLATE).replace(CELL_BREAK.strip(), " ")
    text = text.replace("[RED:", " ").replace("[/TABLE]", " ").replace("[TABLE]", " ")
    return [token for token in _TOKEN.findall(text) if token not in _IGNORED]


_BARE_TAG = re.compile(
    r"\b(?:ANCHOR(?:ED)?|EXCLUSIVE|MUTUALLY EXCLUSIVE|TERMINATE|DO NOT RANDOMIZE|RANDOMIZE)\b"
)


def _joined(text: str) -> str:
    """Red markers removed so an edit inside a word ("wax[RED: ed] paper") rejoins it."""
    return re.sub(r"\[RED: ([^\]]*)\]", r"\1", text).replace("[RED: ", "")


def _black_text(text: str) -> str:
    """The respondent-facing text: red text, bracketed capital tags, and bare tags such as ANCHOR removed."""
    return _BARE_TAG.sub(" ", _CAPS_TAG.sub(" ", _RED.sub(" ", text)))


class Source:
    """Token streams of the source, with and without red programmer text."""

    def __init__(self, text: str) -> None:
        self.text = text
        plain = text.replace("[TABLE]", " ").replace("[/TABLE]", " ")
        # Reason: red can mark an edit inside a word ("wax[RED: ed] paper"), so the
        # marker joins the text around it instead of splitting it.
        self._full = " " + " ".join(tokens(_joined(plain))) + " "
        # Reason: programmer tags such as [ANCHOR] or [PN: ...] may sit inside a label.
        self._black = " " + " ".join(tokens(_black_text(plain))) + " "

    def contains(self, text: str) -> bool:
        """Whether ``text`` appears in the source word for word."""
        wanted = tokens(text)
        if not wanted:
            return True
        needle = " " + " ".join(wanted) + " "
        return needle in self._full or needle in self._black

    def divergence(self, text: str) -> str:
        """Where ``text`` stops matching: the matched words, then what the file and the text say next."""
        wanted = tokens(text)
        best, stream_at = 0, ""
        for stream in (self._full, self._black):
            low, high = 0, len(wanted)
            while low < high:
                middle = (low + high + 1) // 2
                if " " + " ".join(wanted[:middle]) + " " in stream:
                    low = middle
                else:
                    high = middle - 1
            if low > best or not stream_at:
                best, stream_at = low, stream
        if best == 0:
            return "its opening words are not in the file"
        prefix = " " + " ".join(wanted[:best]) + " "
        start = stream_at.index(prefix) + len(prefix)
        file_next = " ".join(stream_at[start:].split()[:8])
        ours_next = " ".join(wanted[best : best + 8])
        lead = " ".join(wanted[max(0, best - 6) : best])
        return f'after "...{lead}" the file has "{file_next}" but the import has "{ours_next}"'


def check_exact(
    document: Questionnaire, source_text: str, not_questions: set[str] | None = None
) -> FidelityReport:
    """Compare an imported questionnaire with its source text.

    Args:
        document: Imported questionnaire.
        source_text: Rendered source document.

    Returns:
        Problems with wording, missing or reordered questions, and punch codes.
    """
    source = Source(source_text)
    report = FidelityReport()
    for note in document.programming_notes + document.sample_notes:
        _text(report, source, "", "Survey note", note)
    for objective in document.objectives:
        _text(report, source, "", "Objective", objective.description)
    for question in document.questions:
        _question(report, source, question)
    for variable in document.derived_variables:
        _text(report, source, variable.id, f"{variable.id} definition", variable.definition)
    _coverage(report, document, source_text, not_questions or set())
    _codes(report, document, source_text)
    return report


def _question(report: FidelityReport, source: Source, question: Question) -> None:
    """Question wording, instruction, notes, options, and grid rows."""
    _text(report, source, question.id, f"{question.id} text", question.text)
    if question.instruction:
        _text(report, source, question.id, f"{question.id} instruction", question.instruction)
    for note in question.programmer_notes:
        _text(report, source, question.id, f"{question.id} programmer note", note)
    for option in question.options:
        _text(report, source, question.id, f"{question.id} option {option.code}", option.label)
    for index, item in enumerate(question.matrix_items, start=1):
        _text(report, source, question.id, f"{question.id} row {index}", item)


def _text(report: FidelityReport, source: Source, key: str, what: str, text: str) -> None:
    """Record whether one piece of text is in the source."""
    report.checked += 1
    if not source.contains(text) and not _pieces_match(source, text):
        report.add(key, f"{what} is not word for word in the file: {source.divergence(text)}.")


def _pieces_match(source: Source, text: str) -> bool:
    """Whether every line, or failing that every sentence, of ``text`` is in the file.

    A question whose wording spans paragraphs with an instruction line between them
    is transcribed as one text; each paragraph and sentence must still be exact.
    """
    for splitter in (r"\n+", r"(?<=[.?!:])\s+"):
        pieces = [piece for piece in re.split(splitter, text) if tokens(piece)]
        if len(pieces) > 1 and all(source.contains(piece) for piece in pieces):
            return True
    return False


def source_sections(source_text: str) -> list[tuple[str, str]]:
    """Split the source at question ids.

    Args:
        source_text: Rendered source.

    Returns:
        (id, text from that id up to the next id) in source order.
    """
    sections: list[tuple[str, list[str]]] = []
    for line in source_text.splitlines():
        found = None
        for part in line.split(CELL_BREAK) if line.startswith("|") else [line]:
            found = question_id_of(part)
            if found:
                break
        if found and all(found != key for key, _ in sections):
            sections.append((found, [line]))
        elif sections:
            sections[-1][1].append(line)
    return [(key, "\n".join(lines)) for key, lines in sections]


def _norm_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def _coverage(
    report: FidelityReport, document: Questionnaire, source_text: str, not_questions: set[str]
) -> None:
    """Every id in the file is imported, and imported ids keep the file's order."""
    found = [key for key, _ in source_sections(source_text)]
    position = {_norm_id(key): index for index, key in enumerate(found)}
    imported = [_norm_id(q.id) for q in document.questions] + [
        _norm_id(v.id) for v in document.derived_variables
    ]
    skipped = {_norm_id(key) for key in not_questions}
    missing = [
        key for key in found if _norm_id(key) not in imported and _norm_id(key) not in skipped
    ]
    if missing:
        report.add("", "Questions in the file are missing: " + ", ".join(missing[:15]))
    ordered = [
        position[key] for key in (_norm_id(q.id) for q in document.questions) if key in position
    ]
    for before, after in zip(ordered, ordered[1:]):
        if after < before:
            report.add(
                "",
                f"Question order differs from the file: {found[after]} comes after {found[before]}.",
            )
            break


def _codes(report: FidelityReport, document: Questionnaire, source_text: str) -> None:
    """Punch codes the file states must be the ones imported.

    A question whose options carry no numbers in the file is left alone. When some
    of its codes are in the file and others are not, the others were invented.
    """
    sections = {_norm_id(key): text for key, text in source_sections(source_text)}
    for question in document.questions:
        section = sections.get(_norm_id(question.id))
        if not section or not question.options:
            continue
        stated = [
            option
            for option in question.options
            if _code_stated(section, option.code, option.label)
            # Reason: "[SHOW Q41 LIST]" or a scale table above a block of statements
            # puts the codes elsewhere in the file.
            or _code_stated(source_text, option.code, option.label, cells=False)
        ]
        # Reason: an unnumbered list with one coded option (99 Prefer not to answer) is numbered in order.
        if len(stated) * 2 < len(question.options) or len(stated) == len(question.options):
            continue
        for option in question.options:
            if option not in stated:
                report.add(
                    question.id,
                    f'{question.id} option "{option.label[:60]}" has code {option.code}, '
                    "which the file does not give it.",
                )


def _code_stated(section: str, code: int | str, label: str, cells: bool = True) -> bool:
    """Whether the file shows ``code`` for this option."""
    code_str = str(code).strip()
    # Reason: files often zero-pad codes ("01 - Yes").
    code_text = (
        rf"0*{re.escape(code_str.lstrip('0') or '0')}"
        if code_str.isdigit()
        else re.escape(code_str)
    )
    label_tokens = tokens(label)
    if label_tokens and re.fullmatch(code_text, label_tokens[0]):
        return True  # the label carries its own code, as in "5 - Completely describes"
    if label_tokens and re.fullmatch(code_text, label_tokens[-1]):
        return True  # a scale end written with its code after it, as in "Poor // 1"
    head = " ".join(label_tokens[:3])
    for flat in (" ".join(tokens(_joined(section))), " ".join(tokens(_black_text(section)))):
        if head and re.search(rf"(?:^|\s){code_text}\s*[.)]?\s+{re.escape(head)}", flat):
            return True
        whole = " ".join(label_tokens)
        if whole and re.search(rf"{re.escape(whole)}\s+{code_text}(?:\s|$)", flat):
            return True  # "Very Dissatisfied // 1" in a scale table
        if head and re.search(rf"(?:^|\s){code_text}\s*=\s*{re.escape(head)}", flat):
            return True  # "0=Very Unfavorable" scale ends
    if not cells:
        return False
    if re.search(rf"\[\s*{code_text}\s*\]", section):
        return True
    for line in section.splitlines():
        for cell in line.strip().strip("|").split("|"):
            if _CODES_ONLY.match(cell) and re.search(rf"(?:^|[\s/]){code_text}(?:$|[\s/.])", cell):
                return True
    return False


def stated_code(source_text: str, label: str) -> str | None:
    """The one punch code the file writes in front of ``label``, or None when absent or ambiguous.

    Args:
        source_text: Rendered source.
        label: Option label.

    Returns:
        Code text such as ``18``.
    """
    wanted = tokens(label)
    if not wanted:
        return None
    phrase = re.escape(" ".join(wanted))
    flat = " ".join(tokens(_joined(source_text)))
    found = set(re.findall(rf"(?:^|\s)(\d+)\s*[.)=]?\s+{phrase}(?=\s|$)", flat))
    return found.pop() if len(found) == 1 else None


def mark_codes_from_file(document: Questionnaire, source_text: str) -> Questionnaire:
    """Record, per question, whether the file gives its punch codes.

    A question whose options the file does not number (most rating scales) was
    numbered in order on import; programming may then choose the scale direction.

    Args:
        document: Imported questionnaire.
        source_text: Rendered source.

    Returns:
        The questionnaire with ``codes_from_file`` set on questions that have options.
    """
    sections = {_norm_id(key): text for key, text in source_sections(source_text)}
    questions = []
    for question in document.questions:
        if not question.options:
            questions.append(question)
            continue
        section = sections.get(_norm_id(question.id), "")
        stated = sum(
            1
            for option in question.options
            if (section and _code_stated(section, option.code, option.label))
            or _code_stated(source_text, option.code, option.label, cells=False)
        )
        questions.append(
            question.model_copy(update={"codes_from_file": stated * 2 >= len(question.options)})
        )
    return document.model_copy(update={"questions": questions})


def attach_source_excerpts(
    document: Questionnaire, source_text: str, limit: int = 4000
) -> Questionnaire:
    """Store on each question the part of the file it was read from.

    Args:
        document: Imported questionnaire.
        source_text: Rendered source.
        limit: Longest excerpt kept per question.

    Returns:
        The questionnaire with ``source_excerpt`` set where the file has the question id.
    """
    sections = {_norm_id(key): text for key, text in source_sections(source_text)}
    questions = []
    for question in document.questions:
        excerpt = sections.get(_norm_id(question.id))
        if excerpt:
            excerpt = excerpt.replace("[TABLE]", "").replace("[/TABLE]", "").strip()[:limit]
            question = question.model_copy(update={"source_excerpt": excerpt})
        questions.append(question)
    return document.model_copy(update={"questions": questions})
