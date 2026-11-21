"""House rules for None, Don't know, Prefer not to answer, and Other (specify) answers.

Questionnaires rarely spell these out on every question, and Decipher programmers
apply them the same way everywhere:

* On a select-all question, None of the above, Don't know, Not sure, and Prefer not
  to answer are exclusive, and they are anchored so a shuffle leaves them at the end.
* An answer that asks the respondent to write something in ("Other (please specify)",
  "Prefer to self-describe", "Other: ______") gets a text box.
* "Other (specify)" is not exclusive: someone can buy two listed brands and one more.
  It stays exclusive only when the question's notes say so for that answer.

Rules the notes state for a question always win; these only fill in what they leave out.
"""

import re

from app.schemas.questionnaire import Option, Question, Questionnaire

_NONE_LIKE = re.compile(
    r"^\s*(?:none\b|neither\b|nothing\b|not applicable|n/?a\b|no (?:preference|opinion)\b"
    r"|(?:i\s+)?don.?t know|do not know|not sure|unsure|prefer not|rather not|decline)",
    re.I,
)
_OTHER = re.compile(r"^\s*(?:other|something else|anything else|another)\b", re.I)
_WRITE_IN = re.compile(
    r"\bspecify\b|self[- ]describe|please describe|please write|write[- ]in|_{3,}|\(\s*other\s*\)",
    re.I,
)
_EXCLUSIVE_NOTE = re.compile(r"\bexclusive\b", re.I)
_NOT_EXCLUSIVE_NOTE = re.compile(r"\bnot\s+(?:be\s+)?exclusive\b|\bnon[- ]exclusive\b", re.I)


def apply_house_rules(document: Questionnaire) -> Questionnaire:
    """Apply the None / Other house rules to every list question.

    Args:
        document: Planned questionnaire.

    Returns:
        The questionnaire with exclusive, anchor, and text-box flags filled in.
    """
    return document.model_copy(
        update={"questions": [house_rules(question) for question in document.questions]}
    )


def house_rules(question: Question) -> Question:
    """Apply the house rules to one question.

    Args:
        question: Question with its planned options.

    Returns:
        The question, unchanged when no rule applies.
    """
    if question.type in {"grid", "matrix", "display", "terminate"} or not question.options:
        return question
    notes = "\n".join(question.programmer_notes)
    options = [_option(option, question, notes) for option in question.options]
    if options == question.options:
        return question
    if question.type == "multi_select":
        exclusive_codes = [option.code for option in options if option.exclusive]
    else:
        exclusive_codes = list(question.exclusive_codes)
    return question.model_copy(update={"options": options, "exclusive_codes": exclusive_codes})


def _option(option: Option, question: Question, notes: str) -> Option:
    update: dict = {}
    label = option.label
    if question.type in {"numeric", "allocation"}:
        # Reason: "___%" or "______ weeks" is where the number goes, not a write-in;
        # only an Other row of a number list takes a text box.
        if option.open_text and not _OTHER.search(label):
            update["open_text"] = False
    elif not option.open_text and _WRITE_IN.search(label):
        update["open_text"] = True
    if question.type == "multi_select":
        listed = str(option.code) in {str(code) for code in question.exclusive_codes}
        exclusive = option.exclusive or listed
        if _NONE_LIKE.search(label) and not _says_not_exclusive(notes):
            exclusive = True
            if not option.anchor:
                update["anchor"] = True
        elif exclusive and _OTHER.search(label) and not _says_exclusive(notes, option):
            exclusive = False
        if exclusive != option.exclusive:
            update["exclusive"] = exclusive
    return option.model_copy(update=update) if update else option


def _says_exclusive(notes: str, option: Option) -> bool:
    """Whether the notes make this answer exclusive, naming it or its code."""
    if not _EXCLUSIVE_NOTE.search(notes) or _says_not_exclusive(notes):
        return False
    code = re.escape(str(option.code))
    sentences = re.split(r"(?<=[.;])\s+|\n", notes)
    return any(
        _EXCLUSIVE_NOTE.search(sentence)
        and (re.search(rf"\b{code}\b", sentence) or re.search(r"\bother\b", sentence, re.I))
        for sentence in sentences
    )


def _says_not_exclusive(notes: str) -> bool:
    return bool(_NOT_EXCLUSIVE_NOTE.search(notes))


def is_none_like(option: Option) -> bool:
    """None of the above, Don't know, Not sure, Prefer not to answer, and similar."""
    return bool(_NONE_LIKE.search(option.label))


def is_extra(option: Option) -> bool:
    """An answer added around a list rather than part of it: None, Don't know, Other."""
    return bool(
        option.exclusive
        or option.anchor
        or option.open_text
        or _NONE_LIKE.search(option.label)
        or _OTHER.search(option.label)
    )


__all__ = ["apply_house_rules", "house_rules", "is_extra", "is_none_like"]
