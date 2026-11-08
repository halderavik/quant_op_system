"""Whitelist boolean expression tree. Never evaluated as Python source."""

from typing import Literal

from pydantic import BaseModel, field_validator

_REF = r"^[A-Za-z_][A-Za-z0-9_]*$"
_Scalar = str | int | float | bool


class Comparison(BaseModel):
    """A comparison against one named variable or question id."""

    kind: Literal["cmp"] = "cmp"
    op: Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "answered", "not_answered"]
    ref: str
    # Reason: OpenAI structured output rejects Any, which emits a schema with no type.
    value: _Scalar | list[_Scalar] | None = None

    @field_validator("ref")
    @classmethod
    def _safe_ref(cls, value: str) -> str:
        """Reject references that are not plain identifiers.

        Args:
            value: Proposed variable or question id.

        Returns:
            The identifier when it matches the allowlist pattern.
        """
        import re

        if "__" in value or not re.match(_REF, value):
            raise ValueError("Expression references must be plain identifiers")
        return value


class BoolExpr(BaseModel):
    """A boolean combination of comparisons or nested expressions."""

    kind: Literal["bool"] = "bool"
    op: Literal["and", "or", "not"]
    args: list["Expr"]


# Reason: a discriminator keyword is not valid in a strict response schema.
# The kind literal still selects the variant during validation.
Expr = Comparison | BoolExpr
BoolExpr.model_rebuild()
