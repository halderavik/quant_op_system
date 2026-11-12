"""Add a Prolific sample source to a programmed Decipher survey."""

import xml.etree.ElementTree as ET

_COMPLETE = "https://app.prolific.com/submissions/complete?cc={code}"


def add_prolific_source(xml: str, codes: dict[str, str]) -> str:
    """Redirect qualified, terminated, and quota-full exits to Prolific.

    Args:
        xml: Programmed survey document.
        codes: Completion codes keyed by qualified, terminated, and overquota.

    Returns:
        Survey XML with a Prolific sample source on list 1. The open-link source stays.
    """
    root = ET.fromstring(xml)
    sources = root.find("samplesources")
    if sources is None:
        sources = ET.Element("samplesources", {"default": "0"})
        root.insert(0, sources)
    for child in list(sources):
        if child.tag == "samplesource" and child.get("list") == "1":
            sources.remove(child)
    source = ET.SubElement(sources, "samplesource", {"list": "1"})
    _text(source, "title", "Prolific")
    _text(
        source,
        "invalid",
        "You are missing information in the URL. Please verify the URL with the original invite.",
    )
    _text(source, "completed", "It seems you have already completed this survey.")
    for name in ("pid", "prolific_study", "prolific_session"):
        attrs = {"name": name}
        if name == "pid":
            attrs["unique"] = "1"
        ET.SubElement(source, "var", attrs)
    for condition in ("qualified", "terminated", "overquota"):
        ET.SubElement(
            source,
            "exit",
            {"cond": condition, "url": _COMPLETE.format(code=codes[condition])},
        )
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def entry_url(survey_url: str) -> str:
    """Build the Prolific external study URL for a Decipher survey.

    Args:
        survey_url: Public Decipher survey address.

    Returns:
        URL that carries the Prolific participant, study, and session placeholders.
    """
    separator = "&" if "?" in survey_url else "?"
    return (
        f"{survey_url}{separator}list=1"
        "&pid={{%PROLIFIC_PID%}}"
        "&prolific_study={{%STUDY_ID%}}"
        "&prolific_session={{%SESSION_ID%}}"
    )


def _text(parent: ET.Element, tag: str, value: str) -> None:
    """Append a text element.

    Args:
        parent: Parent element.
        tag: Element name.
        value: Text.
    """
    node = ET.SubElement(parent, tag)
    node.text = value
