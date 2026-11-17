"""Turn a Pydantic model into a JSON schema Claude's structured outputs accept.

Claude's structured outputs reject recursive schemas and some constraints. A
condition here can nest ("A and (B or C)"), which Pydantic writes as a schema
that refers to itself. This module unrolls each self-referring definition to a
fixed depth (two levels of and/or), removes constraints the API does not take,
and closes every object with ``additionalProperties: false``. The answer is
still validated against the full Pydantic model afterwards, so the constraints
removed here are checked in code.
"""

import copy
from typing import Any

from pydantic import BaseModel

NEST_DEPTH = 2
_DROP_KEYS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "default",
    "discriminator",
}
_FORMATS = {
    "date-time",
    "time",
    "date",
    "duration",
    "email",
    "hostname",
    "uri",
    "ipv4",
    "ipv6",
    "uuid",
}
_REF = "#/$defs/"


def claude_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The API-ready JSON schema of ``model``.

    Args:
        model: Pydantic model of the expected answer.

    Returns:
        A schema with no recursion, no unsupported constraints, and closed objects.
    """
    schema = copy.deepcopy(model.model_json_schema())
    defs: dict[str, Any] = schema.pop("$defs", {})
    cyclic = _cyclic(defs)
    out_defs: dict[str, Any] = {}

    def name_for(target: str, depth: int) -> str | None:
        """Definition name for ``target`` at nesting ``depth``; None when too deep."""
        if target not in cyclic:
            if target not in out_defs:
                out_defs[target] = {}  # placeholder stops endless recursion
                out_defs[target] = rewrite(defs[target], 0)
            return target
        if depth >= NEST_DEPTH:
            return None
        name = f"{target}__{depth}"
        if name not in out_defs:
            out_defs[name] = {}
            out_defs[name] = rewrite(defs[target], depth + 1)
        return name

    def rewrite(node: Any, depth: int) -> Any:
        if isinstance(node, list):
            return [rewrite(item, depth) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node and node["$ref"].startswith(_REF):
            name = name_for(node["$ref"][len(_REF) :], depth)
            return (
                None
                if name is None
                else {**{k: v for k, v in node.items() if k != "$ref"}, "$ref": _REF + name}
            )
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key in _DROP_KEYS:
                continue
            if key == "format" and value not in _FORMATS:
                continue
            if key in {"anyOf", "oneOf", "allOf"}:
                options = [item for item in (rewrite(v, depth) for v in value) if item is not None]
                # Reason: integer and number side by side double the grammar for no gain.
                if {"type": "number"} in options and {"type": "integer"} in options:
                    options.remove({"type": "integer"})
                if not options:
                    return None
                result["anyOf" if key == "oneOf" else key] = options
                continue
            if key == "properties":
                result[key] = {
                    prop: rewritten
                    for prop, sub in value.items()
                    if (rewritten := rewrite(sub, depth)) is not None
                }
                continue
            rewritten = rewrite(value, depth)
            if rewritten is None and key in {"items", "additionalProperties"}:
                return None
            result[key] = rewritten
        if result.get("type") == "object" or "properties" in result:
            result["additionalProperties"] = False
            if "required" in result:
                result["required"] = [
                    p for p in result["required"] if p in result.get("properties", {})
                ]
        return result

    body = rewrite(schema, 0)
    if out_defs:
        body["$defs"] = out_defs
    return body


def _cyclic(defs: dict[str, Any]) -> set[str]:
    """Definitions that can reach themselves through references."""
    edges = {name: _refs(body) for name, body in defs.items()}
    cyclic: set[str] = set()
    for start in defs:
        stack, seen = list(edges[start]), set()
        while stack:
            current = stack.pop()
            if current == start:
                cyclic.add(start)
                break
            if current in seen or current not in edges:
                continue
            seen.add(current)
            stack.extend(edges[current])
    return cyclic


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF):
            found.add(ref[len(_REF) :])
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= _refs(item)
    return found
