"""Read the validation errors Forsta Decipher returns."""


def error_messages(body: dict) -> list[str]:
    """Collect the validation messages Decipher returned.

    Args:
        body: JSON object, possibly containing ``extra``.

    Returns:
        Message strings. A ``$error`` string is included when ``extra`` is empty.
    """
    extra = body.get("extra")
    messages: list[str] = []
    if isinstance(extra, list):
        for item in extra:
            if isinstance(item, dict):
                text = _extra_message(item)
                if text:
                    messages.append(text)
    if messages:
        return messages
    raw = body.get("$error")
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def error_detail(body: dict) -> str:
    """Describe parse and survey errors from a Decipher error body.

    Args:
        body: JSON object, possibly containing ``extra``.

    Returns:
        A short sentence, or an empty string.
    """
    extra = body.get("extra")
    lines: list[str] = []
    if isinstance(extra, list):
        for item in extra:
            if isinstance(item, dict):
                lines.append(_extra_line(item))
    if lines:
        return " ".join(lines)
    raw = body.get("$error")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ""


def scrub(message: str, key: str) -> str:
    """Remove the API key if a response copied it into the message.

    Args:
        message: Text that may be shown to the user.
        key: API key.

    Returns:
        Message with the key replaced.
    """
    if key and key in message:
        return message.replace(key, "[REDACTED]")
    return message


def _extra_message(item: dict) -> str:
    """Return the text of one Decipher validation error.

    Args:
        item: Error object. ``type`` is ``parse`` or ``survey``.

    Returns:
        Message text without the type prefix, or an empty string.
    """
    for field in ("message", "error", "text", "detail", "description"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extra_line(item: dict) -> str:
    """Format one Decipher validation error.

    Args:
        item: Error object. ``type`` is ``parse`` or ``survey``.

    Returns:
        One readable line.
    """
    kind = str(item.get("type") or "error")
    text = _extra_message(item)
    if text:
        return f"{kind}: {text}"
    return kind
