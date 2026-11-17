"""Add live bot and fraud tracking to Decipher survey XML."""

import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

_SCRIPT = Path(__file__).resolve().parents[1] / "assets" / "live_quality_tracker.js"
_FIELDS = (
    ("QOS_RESPONDENT", "respondent", "Quality check respondent id"),
    ("QOS_SESSION", "session", "Quality check session id"),
    ("QOS_FLAG", "flag", "Quality check result"),
    ("QOS_SCORE", "score", "Quality check score"),
    ("QOS_RISK", "risk", "Quality check risk level"),
)
FIELD_LABELS = tuple(label for label, _, _ in _FIELDS)
# Reason: tracking ids follow the project name; these characters are safe in the script,
# the XML comment, and the API path once encoded.
_SURVEY_ID = re.compile(r"^[\w .()&',+:-]{1,100}$")
_UNSAFE_ID_CHARS = re.compile(r"[^\w .()&',+:-]")


@lru_cache(maxsize=1)
def _template() -> str:
    """Return the tracker script template.

    Returns:
        Script text with placeholders.
    """
    return _SCRIPT.read_text(encoding="utf-8")


def tracker_script(
    survey_id: str, api_base: str, token: str = "", rules: dict | None = None
) -> str:
    """Fill the tracker script for one survey.

    Args:
        survey_id: Id the bot-detection API groups sessions under.
        api_base: Bot-detection API base URL, ending in /api/v1.
        token: Signed survey token, or empty when tokens are not configured.
        rules: ``{"terminate": bool, "signals": [codes]}`` for the in-survey check.

    Returns:
        The script block.

    Raises:
        ValueError: The survey id or URL could break the script or the Decipher template.
    """
    if not _SURVEY_ID.match(survey_id) or not survey_id.strip() or "--" in survey_id:
        raise ValueError(
            "The tracking survey id may use letters, digits, spaces, and . ( ) & ' , + : _ -"
        )
    base = api_base.rstrip("/")
    if not base.startswith("https://") or any(char in base for char in "\"'\\<>$ "):
        raise ValueError("The bot-detection API must be an https:// URL.")
    if not re.fullmatch(r"[0-9a-f]{0,64}", token):
        raise ValueError("The survey token must be hexadecimal.")
    config = {
        "terminate": bool((rules or {}).get("terminate")),
        "signals": [
            str(code)
            for code in (rules or {}).get("signals") or []
            if re.fullmatch(r"[a-z_]+", str(code))
        ],
    }
    script = (
        _template()
        .replace("__QOS_API__", base)
        .replace('"__QOS_SURVEY__"', json.dumps(survey_id))
        .replace("__QOS_TOKEN__", token)
        .replace("__QOS_RULES__", json.dumps(config))
    )
    check_template_safe(script)
    return script


def check_template_safe(script: str) -> None:
    """Refuse script text that Decipher's style templates would interpret.

    Args:
        script: Script text.

    Raises:
        ValueError: The text has a dollar sign, a line starting with an at sign, or a CDATA end.
    """
    if "$" in script:
        raise ValueError("The tracker script must not contain a dollar sign.")
    if "]]>" in script:
        raise ValueError("The tracker script must not end a CDATA section.")
    if any(line.lstrip().startswith("@") for line in script.splitlines()):
        raise ValueError("The tracker script must not start a line with an at sign.")
    if "`" in script:
        raise ValueError("The tracker script must not use template literals.")


def survey_id_from_name(project_name: str) -> str:
    """Make the tracking survey id from the project name.

    Args:
        project_name: Project name.

    Returns:
        The project name with unsafe characters removed, for example
        ``BrewCo Live Quality Check``. Dashes replace en and em dashes.
    """
    text = project_name.replace("–", "-").replace("—", "-")
    text = _UNSAFE_ID_CHARS.sub(" ", text)
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:100].strip() or "Survey"


def add_tracking(
    xml: str,
    survey_id: str,
    api_base: str,
    token: str = "",
    rules: dict | None = None,
) -> str:
    """Insert the tracker script and a hidden results page into survey XML.

    The script goes in a ``respview.client.js`` style so it runs on every page. The
    hidden page at the end holds text questions the script fills with the
    respondent id, session id, verdict, score, and risk, so they reach the data file.

    With ``rules["terminate"]``, a hidden ``QOS_EARLY`` question goes on page
    ``rules["after_page"]`` and a termination follows that page: respondents whose
    in-survey check found an enabled decisive bot signal end there. With
    ``rules["privacy_text"]``, a short notice opens the first page.

    Args:
        xml: Compiled survey XML.
        survey_id: Tracking survey id.
        api_base: Bot-detection API base URL.
        token: Signed survey token, or empty.
        rules: ``terminate``, ``after_page``, ``signals``, and ``privacy_text``.

    Returns:
        Survey XML with tracking. XML that already has tracking is returned unchanged.

    Raises:
        ValueError: The XML has no survey element, or the result does not parse.
    """
    if "respview.client.js" in xml and "QOS_SESSION" in xml:
        return xml
    rules = rules or {}
    script = tracker_script(survey_id, api_base, token, rules)
    style = (
        f"\n  <!-- Quant OS live quality tracking: survey id {survey_id} -->\n"
        f'  <style name="respview.client.js"><![CDATA[\n{script}]]></style>'
    )
    anchor = xml.find("</samplesources>")
    if anchor == -1:
        opening = re.search(r"<survey\b[^>]*>", xml)
        if opening is None:
            raise ValueError("The survey XML has no survey element.")
        insert_at = opening.end()
    else:
        insert_at = anchor + len("</samplesources>")
    privacy = str(rules.get("privacy_text") or "").strip()
    if privacy:
        style += f'\n  <html label="QOS_privacy" where="survey">{escape(privacy)}</html>'
    xml = xml[:insert_at] + style + xml[insert_at:]
    if rules.get("terminate"):
        xml = _add_early_check(xml, int(rules.get("after_page") or 2))
    page = [
        '  <html label="QOS_finish">Thank you. Please click the button below to submit your answers.</html>'
    ]
    for label, field, title in _FIELDS:
        page.append(
            f'  <text label="{label}" optional="1" size="40">\n'
            f'    <title><span class="qos-bot-field" data-field="{field}"></span>{title} (leave blank)</title>\n'
            "  </text>"
        )
    closing = xml.rfind("</survey>")
    if closing == -1:
        raise ValueError("The survey XML has no closing survey tag.")
    xml = xml[:closing] + "\n".join(page) + "\n" + xml[closing:]
    ET.fromstring(xml.split("?>", 1)[1] if xml.startswith("<?xml") else xml)
    return xml


_EARLY_QUESTION = (
    '  <text label="QOS_EARLY" optional="1" size="10">\n'
    '    <title><span class="qos-bot-field" data-field="early"></span>Quality check (leave blank)</title>\n'
    "  </text>\n"
)
_EARLY_TERM = (
    '\n  <term label="QOS_bot_term" cond="QOS_EARLY.val and QOS_EARLY.val.strip() == \'bot\'">'
    "Automated response detected</term>"
)


def _add_early_check(xml: str, after_page: int) -> str:
    """Put the hidden in-survey check on page ``after_page`` and terminate bots after it.

    Pages end at ``<suspend/>``. A survey with fewer pages gets no in-survey check;
    the final check still runs.

    Args:
        xml: Survey XML with tracking.
        after_page: Page whose submit runs the check (1 = first page).

    Returns:
        Survey XML.
    """
    breaks = list(re.finditer(r"<suspend\s*/>", xml))
    if len(breaks) < after_page:
        return xml
    found = breaks[after_page - 1]
    start, end = found.start(), found.end()
    return xml[:start] + _EARLY_QUESTION + "    " + xml[start:end] + _EARLY_TERM + xml[end:]


def survey_token(survey_id: str, secret: str) -> str:
    """Signed token the bot-detection service checks for this survey id.

    Matches the service: the first 32 hex characters of HMAC-SHA256(secret, survey id).

    Args:
        survey_id: Tracking survey id.
        secret: Shared secret; empty turns tokens off.

    Returns:
        Token, or an empty string when no secret is configured.
    """
    if not secret:
        return ""
    import hashlib
    import hmac

    return hmac.new(secret.encode("utf-8"), survey_id.encode("utf-8"), hashlib.sha256).hexdigest()[
        :32
    ]
