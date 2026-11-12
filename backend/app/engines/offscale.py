"""Find answer codes that sit off a scale, such as "Don't know" or "Prefer not to say".

Decipher exports and many SPSS files code these as 97, 98, or 99 without
declaring them user-missing. Read as numbers they inflate means, top boxes,
and regressions, so analysis treats them as missing.
"""

import re
from typing import Any

_OFF_SCALE = re.compile(
    r"\b(?:do\s*n[o']?t|dont|did\s*n[o']?t)\s+know\b|\bnot\s+sure\b|\bunsure\b|"
    r"\bcan'?t\s+say\b|\bcannot\s+say\b|\bno\s+opinion\b|\bprefer\s+not\b|"
    r"\brather\s+not\b|\brefused?\b|\bnot\s+applicable\b|^\s*n/?a\s*$|"
    r"\bdo\s*n[o']?t\s+remember\b|\bcan'?t\s+remember\b|\bno\s+answer\b",
    re.I,
)


def is_off_scale_label(label: Any) -> bool:
    """Return whether a value label names a non-substantive answer.

    Args:
        label: Value label text.

    Returns:
        True for "Don't know", "Not sure", "Prefer not to say", "Refused", or "N/A".
    """
    return bool(_OFF_SCALE.search(str(label or "")))


def off_scale_codes(value_labels: dict[Any, Any] | None) -> list[float]:
    """Return the numeric codes whose labels are non-substantive answers.

    Args:
        value_labels: Code to label map from the variable dictionary.

    Returns:
        Codes as floats, sorted.
    """
    found: list[float] = []
    for code, label in (value_labels or {}).items():
        if not is_off_scale_label(label):
            continue
        try:
            found.append(float(code))
        except (TypeError, ValueError):
            continue
    return sorted(set(found))
