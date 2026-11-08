"""Evaluate the Decipher conditions this compiler writes. Never uses eval."""

import re
from dataclasses import dataclass
from typing import Any

_TOKEN = re.compile(
    r"\s+|\"(?:\\.|[^\"\\])*\"|==|!=|>=|<=|>|<|\(|\)|\.|-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*"
)
_KEYWORDS = {"and", "or", "not"}


class ConditionError(Exception):
    """The condition is outside the grammar this preview reads."""

    def __init__(self, condition: str) -> None:
        """Store the condition text that could not be read.

        Args:
            condition: Original Decipher condition.
        """
        super().__init__(condition)
        self.condition = condition


@dataclass
class _Token:
    """One lexer token."""

    kind: str
    text: str


def condition_holds(condition: str, facts: dict[str, Any]) -> bool:
    """Return whether a Decipher condition is true for the current answers.

    Args:
        condition: Condition attribute from the survey XML.
        facts: Dotted names such as ``S1.r1`` or ``Q3.ival`` and their values.

    Returns:
        True when the condition holds.

    Raises:
        ConditionError: The condition uses syntax this preview does not read.
    """
    return _Parser(condition, facts).parse()


def _tokenize(condition: str) -> list[_Token]:
    """Split a condition into tokens.

    Args:
        condition: Condition attribute.

    Returns:
        Tokens with whitespace removed.

    Raises:
        ConditionError: A character is outside the grammar.
    """
    tokens: list[_Token] = []
    cursor = 0
    for match in _TOKEN.finditer(condition):
        if match.start() != cursor:
            raise ConditionError(condition)
        cursor = match.end()
        text = match.group()
        if text.isspace():
            continue
        tokens.append(_Token(_kind(text), text))
    if cursor != len(condition):
        raise ConditionError(condition)
    return tokens


def _kind(text: str) -> str:
    """Classify one token.

    Args:
        text: Token text.

    Returns:
        Token kind.
    """
    if text in {"(", ")"}:
        return "paren"
    if text in {"==", "!=", ">=", "<=", ">", "<"}:
        return "op"
    if text == ".":
        return "dot"
    if text.startswith('"'):
        return "string"
    if text[0].isdigit() or text.startswith("-"):
        return "number"
    return "word"


def _unquote(token: str) -> str:
    """Decode a double-quoted Decipher literal.

    Args:
        token: Quoted token, including the surrounding quotes.

    Returns:
        The string value.
    """
    body = token[1:-1]
    characters: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == "\\" and index + 1 < len(body):
            characters.append(body[index + 1])
            index += 2
            continue
        characters.append(body[index])
        index += 1
    return "".join(characters)


def _truth(value: Any) -> bool:
    """Return the boolean reading of a condition value.

    Args:
        value: Number, string, flag, or missing value.

    Returns:
        False for missing, zero, and empty text.
    """
    if value is None or value is False:
        return False
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        return value != ""
    return bool(value)


def _compare(left: Any, op: str, right: Any) -> bool:
    """Compare two condition values.

    Args:
        left: Left side.
        right: Right side.
        op: Comparison operator.

    Returns:
        False when either side is missing or a numeric compare is not numeric.
    """
    if left is None or right is None:
        return False
    if op == "==":
        return left == right or str(left) == str(right)
    if op == "!=":
        return not (left == right or str(left) == str(right))
    try:
        number = float(left)
        other = float(right)
    except (TypeError, ValueError):
        return False
    if op == ">":
        return number > other
    if op == ">=":
        return number >= other
    if op == "<":
        return number < other
    if op == "<=":
        return number <= other
    return False


class _Parser:
    """Recursive descent parser for one condition."""

    def __init__(self, condition: str, facts: dict[str, Any]) -> None:
        """Store the condition and the answer facts.

        Args:
            condition: Original condition, kept for error text.
            facts: Answer values keyed by dotted name.
        """
        self.condition = condition
        self.facts = facts
        self.tokens = _tokenize(condition)
        self.index = 0

    def parse(self) -> bool:
        """Parse and evaluate the whole condition.

        Returns:
            Condition result.

        Raises:
            ConditionError: Tokens remain after a valid expression.
        """
        value = self._or()
        if self.index < len(self.tokens):
            raise ConditionError(self.condition)
        return value

    def _peek(self) -> _Token | None:
        """Return the next token without consuming it.

        Returns:
            Token, or None at the end.
        """
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def _accept(self, kind: str, text: str | None = None) -> _Token | None:
        """Consume the next token when it matches.

        Args:
            kind: Expected kind.
            text: Expected text, when it matters.

        Returns:
            The token, or None when it does not match.
        """
        token = self._peek()
        if token is None or token.kind != kind:
            return None
        if text is not None and token.text != text:
            return None
        self.index += 1
        return token

    def _or(self) -> bool:
        """Parse an ``or`` chain.

        Returns:
            Combined result.
        """
        value = self._and()
        while self._accept("word", "or"):
            value = value or self._and()
        return value

    def _and(self) -> bool:
        """Parse an ``and`` chain.

        Returns:
            Combined result.
        """
        value = self._not()
        while self._accept("word", "and"):
            value = value and self._not()
        return value

    def _not(self) -> bool:
        """Parse a ``not`` prefix.

        Returns:
            Negated or primary result.
        """
        if self._accept("word", "not"):
            return not self._not()
        return self._cmp()

    def _cmp(self) -> bool:
        """Parse a parenthesized expression or a comparison.

        Returns:
            Boolean result.

        Raises:
            ConditionError: A parenthesis is not closed.
        """
        if self._accept("paren", "("):
            value = self._or()
            if not self._accept("paren", ")"):
                raise ConditionError(self.condition)
            return value
        left = self._atom()
        op = self._accept("op")
        if op is None:
            return _truth(left)
        return _compare(left, op.text, self._atom())

    def _atom(self) -> Any:
        """Parse a number, string, or dotted reference.

        Returns:
            The value to compare or test.

        Raises:
            ConditionError: The next token is not a value.
        """
        peeked = self._peek()
        if peeked is not None and peeked.text in _KEYWORDS:
            raise ConditionError(self.condition)
        word = self._accept("word")
        if word:
            return self._ref(word.text)
        number = self._accept("number")
        if number:
            return float(number.text) if "." in number.text else int(number.text)
        quoted = self._accept("string")
        if quoted:
            return _unquote(quoted.text)
        raise ConditionError(self.condition)

    def _ref(self, first: str) -> Any:
        """Look up a dotted name such as ``Q2.r1.c1``.

        Args:
            first: First identifier.

        Returns:
            Stored value, or None when the answer has no such name.

        Raises:
            ConditionError: A dot is not followed by a name.
        """
        parts = [first]
        while self._accept("dot"):
            nxt = self._accept("word")
            if nxt is None:
                raise ConditionError(self.condition)
            parts.append(nxt.text)
        return self.facts.get(".".join(parts))
