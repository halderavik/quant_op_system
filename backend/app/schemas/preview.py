"""Respondent screens read from a Decipher survey XML file."""

from typing import Literal

from pydantic import BaseModel, Field


class PreviewRow(BaseModel):
    """One row, loop row, or choice list item."""

    label: str
    text: str
    exclusive: bool = False
    open: bool = False
    randomize: bool = True


class PreviewColumn(BaseModel):
    """One grid column or rank choice."""

    label: str
    text: str


class PreviewAnswer(BaseModel):
    """The respondent's answer for one question label."""

    rows: list[str] = Field(default_factory=list)
    cells: dict[str, str] = Field(default_factory=dict)
    value: str | None = None
    row_values: dict[str, str] = Field(default_factory=dict)
    open_text: dict[str, str] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    """One step through a survey XML file."""

    xml: str
    answers: dict[str, PreviewAnswer] = Field(default_factory=dict)
    current_label: str | None = None


class PreviewScreen(BaseModel):
    """What the respondent sees on the next screen."""

    status: Literal["question", "terminated", "complete", "error"]
    label: str | None = None
    element: str | None = None
    title: str = ""
    comment: str | None = None
    required: bool = False
    atleast: int | None = None
    rows: list[PreviewRow] = Field(default_factory=list)
    cols: list[PreviewColumn] = Field(default_factory=list)
    choices: list[PreviewColumn] = Field(default_factory=list)
    shuffle: bool = False
    verify: str | None = None
    check: Literal["none", "date", "total100"] = "none"
    warning: str | None = None
    message: str = ""
