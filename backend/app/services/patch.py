"""Semantic patches against canonical artifact JSON."""

import copy
from typing import Any

from app.errors import AppError
from app.schemas.artifact import SemanticPatch


def apply_semantic_patch(content: dict[str, Any], patch: SemanticPatch) -> dict[str, Any]:
    """Apply one patch and return a new document.

    Args:
        content: Current canonical JSON.
        patch: Patch request.

    Returns:
        Updated document.
    """
    updated = copy.deepcopy(content)
    if patch.op == "set_question":
        if not patch.question_id or not isinstance(patch.value, dict):
            raise AppError("A question patch needs a question id and a value object.", "bad_patch")
        for question in updated.get("questions", []):
            if question.get("id") == patch.question_id:
                question.update(patch.value)
                return updated
        raise AppError(f"Question {patch.question_id} is not in this instrument.", "bad_patch")
    if patch.op in {"replace", "add"}:
        if not patch.path:
            raise AppError("This patch needs a JSON pointer path.", "bad_patch")
        _set_pointer(updated, patch.path, patch.value)
        return updated
    if patch.op == "remove":
        if not patch.path:
            raise AppError("This patch needs a JSON pointer path.", "bad_patch")
        _remove_pointer(updated, patch.path)
        return updated
    raise AppError(f"Unsupported patch operation '{patch.op}'.", "bad_patch")


def _set_pointer(document: Any, path: str, value: Any) -> None:
    """Set a JSON pointer.

    Args:
        document: Root document.
        path: Pointer such as ``/questions/0/text``.
        value: Replacement value.
    """
    parts = [part for part in path.split("/") if part != ""]
    if not parts:
        raise AppError("The patch path is empty.", "bad_patch")
    current = document
    for part in parts[:-1]:
        current = _step(current, part)
    _put(current, parts[-1], value)


def _remove_pointer(document: Any, path: str) -> None:
    """Remove a JSON pointer.

    Args:
        document: Root document.
        path: Pointer.
    """
    parts = [part for part in path.split("/") if part != ""]
    current = document
    for part in parts[:-1]:
        current = _step(current, part)
    last = parts[-1]
    if isinstance(current, list):
        current.pop(int(last))
    else:
        current.pop(last, None)


def _step(current: Any, part: str) -> Any:
    """Move one pointer segment.

    Args:
        current: Current node.
        part: Segment.

    Returns:
        Child node.
    """
    if isinstance(current, list):
        return current[int(part)]
    if part not in current:
        raise AppError(f"Patch path is missing '{part}'.", "bad_patch")
    return current[part]


def _put(current: Any, part: str, value: Any) -> None:
    """Write the final pointer segment.

    Args:
        current: Parent node.
        part: Final segment.
        value: Value to store.
    """
    if isinstance(current, list):
        current[int(part)] = value
    else:
        current[part] = value
