"""Read sample size, minutes, and audience words from a request."""

import re
from dataclasses import dataclass, field

_REP_PATTERNS = (
    (r"uk regional representative|uk regional sample", "UK_REGIONAL_REP_SAMPLE"),
    (r"us regional representative|us regional sample", "US_REGIONAL_REP_SAMPLE"),
    (
        r"uk.{0,40}political|political.{0,40}uk",
        "REP_SAMPLE_UK_ENGLISH_AGE_POLITICAL_AFFILIATION",
    ),
    (
        r"political affiliation and ethnicity|ethnicity and political",
        "REP_SAMPLE_US_ENGLISH_AGE_POLITICAL_AFFILIATION_ETHNICITY",
    ),
    (r"us.{0,40}political", "REP_SAMPLE_US_ENGLISH_AGE_POLITICAL_AFFILIATION"),
    (
        r"\buk representative\b|representative uk|nationally representative uk|"
        r"uk nationally representative",
        "UK_REP_SAMPLE",
    ),
    (
        r"\bus representative\b|representative (?:us|united states)|"
        r"nationally representative (?:us|united states)|united states representative",
        "US_REP_SAMPLE",
    ),
)
_COUNTRY_ALIASES = {
    "united kingdom": ("united kingdom", "uk", "britain", "great britain"),
    "united states": ("united states", "usa", "us", "u.s.", "america"),
}
_SIZE = (
    re.compile(r"\bn\s*=\s*(\d{1,6})\b", re.I),
    re.compile(
        r"\b(\d{1,6})\s+(?:uk|us|u\.s\.|adults?|respondents?|participants?|people|completes)\b",
        re.I,
    ),
    re.compile(r"\b(?:sample|price|buy|recruit)\D{0,24}(\d{1,6})\b", re.I),
)
_MINUTES = re.compile(r"\b(\d{1,4})\s*-?\s*min(?:ute)?s?\b", re.I)
_AGE = re.compile(r"\b(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\b", re.I)
_HALF = re.compile(
    r"half (?:women|men|female|male)|50\s*/\s*50|equal(?:ly)? (?:men and women|gender|sex)",
    re.I,
)
_WOMEN = re.compile(r"\b(?:women|woman|female)\b", re.I)
_MEN = re.compile(r"\b(?:men|man|male)\b", re.I)


@dataclass
class ParsedAudience:
    """Audience facts read from the user text before catalog matching."""

    sample_size: int | None = None
    minutes: int | None = None
    study_type: str | None = None
    countries: list[str] = field(default_factory=list)
    age: tuple[int, int] | None = None
    age_bands: list[tuple[int, int]] = field(default_factory=list)
    sex: str = ""
    devices: list[str] = field(default_factory=lambda: ["desktop", "tablet", "mobile"])
    custom_quota: bool = False


def parse_request(text: str, notes: list[str]) -> ParsedAudience:
    """Read sample size, time, and audience words.

    Args:
        text: User message.
        notes: Questionnaire sample notes, used only to fill a gap.

    Returns:
        Parsed audience. A missing sample size stays None.
    """
    parsed = _parse_one(text)
    fallback = _parse_one("\n".join(notes))
    if parsed.sample_size is None:
        parsed.sample_size = fallback.sample_size
    if parsed.minutes is None:
        parsed.minutes = fallback.minutes
    # Reason: sample notes fill a gap. They do not override a representative request.
    user_named_audience = bool(
        parsed.study_type or parsed.countries or parsed.age or parsed.sex or parsed.age_bands
    )
    if not user_named_audience:
        parsed.study_type = fallback.study_type
        parsed.countries = fallback.countries
        parsed.age = fallback.age
        parsed.age_bands = fallback.age_bands
        parsed.sex = fallback.sex
        parsed.custom_quota = fallback.custom_quota
    return parsed


def _parse_one(text: str) -> ParsedAudience:
    """Parse one block of text.

    Args:
        text: User text or sample notes.

    Returns:
        Partial audience.
    """
    parsed = ParsedAudience()
    for pattern in _SIZE:
        match = pattern.search(text)
        if match:
            parsed.sample_size = int(match.group(1))
            break
    minutes = _MINUTES.search(text)
    if minutes:
        parsed.minutes = int(minutes.group(1))
    lowered = text.lower()
    for pattern, study_type in _REP_PATTERNS:
        if re.search(pattern, lowered):
            parsed.study_type = study_type
            break
    for name, aliases in _COUNTRY_ALIASES.items():
        if any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in aliases):
            parsed.countries.append(name)
    bands = [(int(match.group(1)), int(match.group(2))) for match in _AGE.finditer(text)]
    bands = [(lower, upper) for lower, upper in bands if 0 < lower < upper <= 120]
    if "age band" in lowered and len(bands) > 1:
        parsed.age_bands = bands
        parsed.custom_quota = True
    elif bands:
        parsed.age = bands[0]
        parsed.custom_quota = True
    if _HALF.search(text):
        parsed.sex = "half"
        parsed.custom_quota = True
    elif _WOMEN.search(text) and not _MEN.search(text):
        parsed.sex = "female"
        parsed.custom_quota = True
    elif _MEN.search(text) and not _WOMEN.search(text):
        parsed.sex = "male"
        parsed.custom_quota = True
    if re.search(r"desktop only", lowered):
        parsed.devices = ["desktop"]
    elif re.search(r"mobile only", lowered):
        parsed.devices = ["mobile"]
    return parsed
