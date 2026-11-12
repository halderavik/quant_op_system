"""Correct survey XML using the errors Decipher returns.

The repairs are structural. Question text, option codes, and routing conditions
are left as written. An error that does not name one of these changes is left
unresolved so a later upload can report it.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from app.engines.decipher_markup import _comment_body

_PREFIX = re.compile(r"^(?:(?:parse|survey|error):\s*)?(?:line\s+\d+:\s*)?", re.IGNORECASE)
_REQUIRE_ATTR = re.compile(
    r"require\s+([A-Za-z_][\w:]*)\s*=\s*['\"]?([^'\"\s]+)['\"]?",
    re.IGNORECASE,
)
_TAG_INSIDE = re.compile(
    r"this tag \(([^)]+)\) is not permitted inside (?:a|an) ([A-Za-z_][\w]*) tag",
    re.IGNORECASE,
)
_ATTR_FORBIDDEN = re.compile(
    r"attribute\s+(?:['\"]([^'\"]+)['\"]|\(([^)]+)\))\s+is not (?:permitted|allowed)"
    r"(?:\s+on\s+(?:a\s+|an\s+|the\s+)?(?:element\s+)?['\"]?([A-Za-z_][\w]*)['\"]?)?",
    re.IGNORECASE,
)
_NOT_A_TAG = {"this", "element", "tag"}
_STYLE = re.compile(r"while using style ['\"]?(?:[\w.-]+/)*([A-Za-z_]\w*)/v\d+", re.IGNORECASE)
# Reason: attributes the studio writes only for a style. They mean nothing once the style is gone.
_STYLE_ATTRS = {"ranksort": {"minRanks"}}


@dataclass(frozen=True)
class XmlRepair:
    """XML after one repair pass."""

    xml: str
    fixes: list[str]
    changed: bool


def repair_survey_xml(xml: str, errors: list[str]) -> XmlRepair:
    """Apply every safe correction named by Decipher's error list.

    Args:
        xml: Survey document Decipher rejected.
        errors: ``message`` strings from the ``extra`` array, or the same text
            with a ``survey:`` prefix.

    Returns:
        The original document when nothing safe can be changed. Otherwise the
        corrected document and a short description of each change.
    """
    messages = [_message(item) for item in errors if item.strip()]
    if not messages:
        return XmlRepair(xml=xml, fixes=[], changed=False)
    try:
        root = _parse(xml)
    except ET.ParseError:
        return XmlRepair(xml=xml, fixes=[], changed=False)
    fixes = _require_attributes(root, messages)
    fixes.extend(_lift_tags(root, messages))
    fixes.extend(_drop_attributes(root, messages))
    fixes.extend(_drop_styles(root, messages))
    unique = _unique(fixes)
    if not unique:
        return XmlRepair(xml=xml, fixes=[], changed=False)
    return XmlRepair(xml=_serialize(root, xml), fixes=unique, changed=True)


def _message(raw: str) -> str:
    """Drop a type prefix and a line number so the rule text can be matched.

    Args:
        raw: One Decipher error string.

    Returns:
        Message body.
    """
    return _PREFIX.sub("", raw.strip())


def _parse(xml: str) -> ET.Element:
    """Parse survey XML and keep comments.

    Args:
        xml: Survey document.

    Returns:
        Document root.

    Raises:
        ET.ParseError: The document is not well-formed XML.
    """
    # Reason: ElementTree drops comments unless the builder is asked to keep them.
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.fromstring(xml, parser)


def _serialize(root: ET.Element, original: str) -> str:
    """Write the survey back out, keeping an XML declaration when one was present.

    Args:
        root: Repaired document.
        original: Document Decipher rejected.

    Returns:
        XML text.
    """
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    if original.lstrip().startswith("<?xml"):
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + body
    return body


def _require_attributes(root: ET.Element, messages: list[str]) -> list[str]:
    """Set a survey attribute when Decipher says the survey requires that value.

    Args:
        root: Document root.
        messages: Error texts.

    Returns:
        Descriptions of attributes that were set.
    """
    if _local(root.tag) != "survey":
        return []
    fixes: list[str] = []
    for message in messages:
        if re.search(r"survey|compat", message, re.IGNORECASE) is None:
            continue
        for match in _REQUIRE_ATTR.finditer(message):
            name, value = match.group(1), match.group(2).strip("'\"")
            if not value or root.get(name) == value:
                continue
            root.set(name, value)
            fixes.append(f'Set {name}="{value}" on the survey.')
    return fixes


def _lift_tags(root: ET.Element, messages: list[str]) -> list[str]:
    """Move a tag Decipher refused out of the parent it named.

    A ``note`` becomes a comment placed just before that parent. Any other tag
    is moved, unchanged, to just before that parent.

    Args:
        root: Document root.
        messages: Error texts.

    Returns:
        Descriptions of tags that were moved.
    """
    fixes: list[str] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        for match in _TAG_INSIDE.finditer(message):
            child = match.group(1).strip().lower()
            parent = match.group(2).strip().lower()
            if not child or not parent or (child, parent) in seen:
                continue
            seen.add((child, parent))
            if _lift(root, child, parent):
                if child == "note":
                    fixes.append(f"Moved {child} text out of {parent} into a comment.")
                else:
                    fixes.append(f"Moved {child} out of {parent}.")
    return fixes


def _lift(root: ET.Element, child_tag: str, parent_tag: str) -> bool:
    """Move matching descendants out of every element of the named parent tag.

    Args:
        root: Document root.
        child_tag: Lowercase tag Decipher refused.
        parent_tag: Lowercase tag that may not contain it.

    Returns:
        True when at least one element was moved.
    """
    parents = _parents(root)
    moved = False
    for element in list(root.iter()):
        if _local(element.tag) != parent_tag:
            continue
        holder = parents.get(element)
        if holder is None:
            continue
        found = [
            node
            for node in list(element.iter())
            if node is not element and _local(node.tag) == child_tag
        ]
        victims = _without_nested(found)
        payloads: list[ET.Element] = []
        for victim in victims:
            owner = parents.get(victim)
            if owner is None:
                continue
            owner.remove(victim)
            payloads.append(victim)
        if not payloads:
            continue
        index = list(holder).index(element)
        for offset, victim in enumerate(payloads):
            placed = _note_comment(element, victim) if child_tag == "note" else victim
            holder.insert(index + offset, placed)
        moved = True
    return moved


def _without_nested(nodes: list[ET.Element]) -> list[ET.Element]:
    """Drop a match that already sits inside another match.

    Args:
        nodes: Matching elements in document order.

    Returns:
        The outermost matches. Moving an ancestor moves its descendants too.
    """
    return [
        node for node in nodes if all(node is other or node not in other.iter() for other in nodes)
    ]


def _note_comment(parent: ET.Element, note: ET.Element) -> ET.Element:
    """Turn a rejected note into a comment that keeps its text.

    Args:
        parent: Element the note was removed from.
        note: Note element.

    Returns:
        Comment element.
    """
    label = parent.get("label") or ""
    prefix = f"{label}: " if label else ""
    return ET.Comment(f" {prefix}{_comment_body(''.join(note.itertext()))} ")


def _drop_attributes(root: ET.Element, messages: list[str]) -> list[str]:
    """Remove an attribute when Decipher names both the attribute and the tag.

    Args:
        root: Document root.
        messages: Error texts.

    Returns:
        Descriptions of attributes that were removed.
    """
    fixes: list[str] = []
    for message in messages:
        for match in _ATTR_FORBIDDEN.finditer(message):
            name = (match.group(1) or match.group(2) or "").strip()
            tag = (match.group(3) or "").strip().lower()
            if not name or tag in _NOT_A_TAG or not tag:
                continue
            if _remove_attribute(root, tag, name):
                fixes.append(f"Removed {name} from {tag}.")
    return fixes


def _drop_styles(root: ET.Element, messages: list[str]) -> list[str]:
    """Remove a question style Decipher could not apply, keeping the plain question.

    Args:
        root: Document root.
        messages: Error texts.

    Returns:
        Descriptions of styles that were removed.
    """
    fixes: list[str] = []
    for message in messages:
        for match in _STYLE.finditer(message):
            style = match.group(1).lower()
            labels: list[str] = []
            for element in root.iter():
                uses = element.get("uses") or ""
                if uses.split(".", 1)[0].lower() != style:
                    continue
                del element.attrib["uses"]
                for name in _STYLE_ATTRS.get(style, set()):
                    element.attrib.pop(name, None)
                labels.append(element.get("label") or _local(element.tag))
            if labels:
                fixes.append(
                    f"Removed the {style} style from {', '.join(labels)}, "
                    "so those questions use Decipher's plain layout."
                )
    return fixes


def _remove_attribute(root: ET.Element, tag: str, name: str) -> bool:
    """Delete one attribute from every element of a tag.

    Args:
        root: Document root.
        tag: Lowercase tag name.
        name: Attribute name.

    Returns:
        True when an attribute was deleted.
    """
    removed = False
    wanted = name.lower()
    for element in root.iter():
        if _local(element.tag) != tag:
            continue
        for key in list(element.attrib):
            if key.rsplit("}", 1)[-1].lower() == wanted:
                del element.attrib[key]
                removed = True
    return removed


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    """Map each node to the element that contains it.

    Args:
        root: Document root.

    Returns:
        Parent map. The root has no entry.
    """
    found: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in list(parent):
            found[child] = parent
    return found


def _local(tag: object) -> str:
    """Return a lowercase tag name without a namespace.

    Args:
        tag: Element tag. Comment nodes do not use a string tag.

    Returns:
        Local name, or an empty string for a comment or processing instruction.
    """
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _unique(items: list[str]) -> list[str]:
    """Drop repeated descriptions and keep the first one.

    Args:
        items: Fix descriptions.

    Returns:
        Descriptions in first-seen order.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
