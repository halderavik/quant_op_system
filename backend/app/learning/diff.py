"""Structured diffs of the artifacts users edit. Only structure and wording are kept."""

import difflib
import re
from typing import Any

from app.engines.offscale import is_off_scale_label

_FIELDS = (
    "type",
    "instruction",
    "required",
    "randomize_options",
    "display_if",
    "routing",
    "matrix_items",
    "exclusive_codes",
)
_SCALE_TYPES = {"single_select", "rating", "grid", "matrix", "screener"}
_TEXT_LIMIT = 2000


def questionnaire_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two questionnaire revisions question by question.

    Questions match by id. A question whose id changed but whose type and
    wording stayed close is treated as the same question, not a delete and an add.

    Args:
        before: Earlier questionnaire JSON.
        after: Later questionnaire JSON.

    Returns:
        Added, removed, modified, and moved questions, document-level changes,
        counts, and one-line summaries. Empty lists when nothing changed.
    """
    old = {str(item["id"]): item for item in before.get("questions") or []}
    new = {str(item["id"]): item for item in after.get("questions") or []}
    renamed = _match_renamed(
        {key: old[key] for key in old.keys() - new.keys()},
        {key: new[key] for key in new.keys() - old.keys()},
    )
    pairs = [(key, key) for key in old if key in new] + list(renamed.items())
    paired_old = {left for left, _ in pairs}
    paired_new = {right for _, right in pairs}
    order_new = [str(item["id"]) for item in after.get("questions") or []]
    added = [
        {
            "id": key,
            "position": order_new.index(key) + 1,
            "type": new[key].get("type"),
            "text": _clip(new[key].get("text")),
            "option_count": len(new[key].get("options") or []),
            "after_id": order_new[order_new.index(key) - 1] if order_new.index(key) else None,
        }
        for key in order_new
        if key not in paired_new
    ]
    removed = [
        {"id": key, "type": item.get("type"), "text": _clip(item.get("text"))}
        for key, item in old.items()
        if key not in paired_old
    ]
    modified = []
    for left, right in pairs:
        change = _question_change(old[left], new[right])
        if left != right:
            change["renamed_from"] = left
        if change:
            change["id"] = right
            modified.append(change)
    moved = _moved(
        [
            str(item["id"])
            for item in before.get("questions") or []
            if str(item["id"]) in paired_old
        ],
        [key for key in order_new if key in paired_new],
        renamed,
    )
    document = _document_change(before, after)
    summary = _summary(added, removed, modified, moved, document)
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "moved": moved,
        "document": document,
        "counts": {
            "questions_before": len(old),
            "questions_after": len(new),
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "moved": len(moved),
        },
        "summary": summary,
    }


def report_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare the editable report parts of two analysis revisions.

    Args:
        before: Earlier analysis artifact content.
        after: Later analysis artifact content.

    Returns:
        Changed sections with clipped before and after text, and caveat changes.
    """
    old = {str(item.get("id")): item.get("narrative", "") for item in _sections(before)}
    new = {str(item.get("id")): item.get("narrative", "") for item in _sections(after)}
    sections = [
        {"id": key, "before": _clip(old.get(key, "")), "after": _clip(new.get(key, ""))}
        for key in sorted(old.keys() | new.keys())
        if (old.get(key) or "").strip() != (new.get(key) or "").strip()
    ]
    old_caveats = list(((before.get("report") or {}).get("caveats")) or [])
    new_caveats = list(((after.get("report") or {}).get("caveats")) or [])
    caveats = {
        "added": [item for item in new_caveats if item not in old_caveats],
        "removed": [item for item in old_caveats if item not in new_caveats],
    }
    summary = []
    if sections:
        summary.append("Edited report sections: " + ", ".join(item["id"] for item in sections))
    if caveats["added"] or caveats["removed"]:
        summary.append(f"Caveats: {len(caveats['added'])} added, {len(caveats['removed'])} removed")
    return {"sections": sections, "caveats": caveats, "summary": summary}


def generic_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Name the top-level fields that changed in any other artifact type."""
    keys = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    return {"changed_fields": keys, "summary": [f"Changed {', '.join(keys)}"] if keys else []}


def has_changes(diff: dict[str, Any]) -> bool:
    """Return whether a diff recorded any change."""
    return bool(diff.get("summary"))


def _question_change(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Field-level change for one matched question; empty when unchanged."""
    change: dict[str, Any] = {}
    if _norm(old.get("text")) != _norm(new.get("text")):
        change["text"] = {"before": _clip(old.get("text")), "after": _clip(new.get("text"))}
    fields = [name for name in _FIELDS if old.get(name) != new.get(name)]
    if fields:
        change["fields"] = {
            name: {"before": old.get(name), "after": new.get(name)} for name in fields
        }
    options = _options_change(old, new)
    if options:
        change["options"] = options
    return change


def _options_change(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Added, removed, and relabelled options, plus scale and special-code flags."""
    before = {str(item.get("code")): item for item in old.get("options") or []}
    after = {str(item.get("code")): item for item in new.get("options") or []}
    labels_before = {_norm(item.get("label")) for item in before.values()}
    added = [
        item.get("label")
        for code, item in after.items()
        if code not in before and _norm(item.get("label")) not in labels_before
    ]
    labels_after = {_norm(item.get("label")) for item in after.values()}
    removed = [
        item.get("label")
        for code, item in before.items()
        if code not in after and _norm(item.get("label")) not in labels_after
    ]
    relabelled = [
        {"code": code, "before": before[code].get("label"), "after": after[code].get("label")}
        for code in before.keys() & after.keys()
        if _norm(before[code].get("label")) != _norm(after[code].get("label"))
    ]
    flags = {
        key: [
            str(item.get("label"))
            for code, item in after.items()
            if item.get(key) and not (before.get(code) or {}).get(key)
        ]
        for key in ("exclusive", "open_text", "terminate", "anchor")
    }
    flags = {key: value for key, value in flags.items() if value}
    if not (added or removed or relabelled or flags):
        return {}
    result: dict[str, Any] = {
        "count_before": len(before),
        "count_after": len(after),
        "added": added,
        "removed": removed,
        "relabelled": relabelled,
    }
    if flags:
        result["flags_added"] = flags
    dont_know = [label for label in added if is_off_scale_label(str(label))]
    if dont_know:
        result["dont_know_added"] = dont_know
    scale_before = _scale_points(old)
    scale_after = _scale_points(new)
    if scale_before and scale_after and scale_before != scale_after:
        result["scale_points"] = {"before": scale_before, "after": scale_after}
    return result


def _scale_points(question: dict[str, Any]) -> int:
    """Count substantive scale points on a single-choice or rating question."""
    if str(question.get("type") or "").lower() not in _SCALE_TYPES:
        return 0
    return sum(
        1
        for item in question.get("options") or []
        if not item.get("open_text") and not is_off_scale_label(str(item.get("label") or ""))
    )


def _match_renamed(
    removed: dict[str, dict[str, Any]], added: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Pair questions whose id changed but whose type and wording stayed close."""
    pairs: dict[str, str] = {}
    taken: set[str] = set()
    for old_id, old in removed.items():
        best, score = "", 0.0
        for new_id, new in added.items():
            if new_id in taken or old.get("type") != new.get("type"):
                continue
            ratio = difflib.SequenceMatcher(
                None, _norm(old.get("text")), _norm(new.get("text"))
            ).ratio()
            if ratio > score:
                best, score = new_id, ratio
        if best and score >= 0.85:
            pairs[old_id] = best
            taken.add(best)
    return pairs


def _moved(before: list[str], after: list[str], renamed: dict[str, str]) -> list[dict[str, Any]]:
    """Questions that changed position, beyond the shift caused by adds and deletes.

    The longest run of questions that kept their relative order stays put;
    everything outside it moved.
    """
    mapped = [renamed.get(key, key) for key in before]
    position = {key: index for index, key in enumerate(after)}
    sequence = [position[key] for key in mapped if key in position]
    keep = set(_longest_increasing(sequence))
    return [
        {"id": key, "from": index + 1, "to": position[key] + 1}
        for index, key in enumerate(mapped)
        if key in position and position[key] not in keep
    ]


def _longest_increasing(values: list[int]) -> list[int]:
    """Return one longest strictly increasing subsequence."""
    best: list[list[int]] = []
    for value in values:
        candidates = [run for run in best if run[-1] < value]
        longest = max(candidates, key=len, default=[])
        best.append([*longest, value])
    return max(best, key=len, default=[])


def _document_change(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Title, length estimate, objectives, and modules."""
    change: dict[str, Any] = {}
    if before.get("title") != after.get("title"):
        change["title"] = {"before": before.get("title"), "after": after.get("title")}
    if before.get("estimated_minutes") != after.get("estimated_minutes"):
        change["estimated_minutes"] = {
            "before": before.get("estimated_minutes"),
            "after": after.get("estimated_minutes"),
        }
    old = {_norm(item.get("description")) for item in before.get("objectives") or []}
    new = {_norm(item.get("description")) for item in after.get("objectives") or []}
    if old != new:
        change["objectives"] = {"added": sorted(new - old), "removed": sorted(old - new)}
    old_modules = [item.get("title") for item in before.get("modules") or []]
    new_modules = [item.get("title") for item in after.get("modules") or []]
    if old_modules != new_modules:
        change["modules"] = {"before": old_modules, "after": new_modules}
    return change


def _summary(
    added: list[dict[str, Any]],
    removed: list[dict[str, Any]],
    modified: list[dict[str, Any]],
    moved: list[dict[str, Any]],
    document: dict[str, Any],
) -> list[str]:
    """One-line descriptions a later lesson step can read."""
    lines = [f"Added {item['id']} ({item['type']}): {item['text'][:120]}" for item in added]
    lines += [f"Removed {item['id']} ({item['type']}): {item['text'][:120]}" for item in removed]
    for item in modified:
        parts = []
        if "renamed_from" in item:
            parts.append(f"renamed from {item['renamed_from']}")
        if "text" in item:
            parts.append("reworded")
        options = item.get("options") or {}
        if options.get("scale_points"):
            points = options["scale_points"]
            parts.append(f"scale {points['before']} to {points['after']} points")
        if options.get("dont_know_added"):
            parts.append("added Don't know")
        if options.get("added") or options.get("removed") or options.get("relabelled"):
            parts.append(
                f"options +{len(options.get('added', []))} -{len(options.get('removed', []))} "
                f"relabelled {len(options.get('relabelled', []))}"
            )
        parts += [f"{name} changed" for name in (item.get("fields") or {})]
        lines.append(f"Changed {item['id']}: " + "; ".join(parts))
    lines += [f"Moved {item['id']} from {item['from']} to {item['to']}" for item in moved]
    lines += [f"Document {name} changed" for name in document]
    return lines


def _sections(content: dict[str, Any]) -> list[dict[str, Any]]:
    return list(((content.get("report") or {}).get("sections")) or [])


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _clip(text: Any) -> str:
    value = str(text or "")
    return value if len(value) <= _TEXT_LIMIT else value[:_TEXT_LIMIT] + "…"
