"""Draw one synthetic answer from a persona's answer profile.

The model supplies relative weights. This module enforces the survey's rules:
one code for a single select, exclusive rows, minimum selections, unique ranks,
a 100-point total, and numeric ranges.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.engines.synthetic_survey import Choice, Spec
from app.schemas.preview import PreviewAnswer
from app.schemas.synthetic import PersonaAnswers, QuotaTarget, Weight

_FALLBACK_TEXT = "Synthetic open-end answer"
_DATE_START = date(2025, 1, 1)
_END_SHARE = 0.05
_SHIFT_LIMIT = 4.0
_SCALE_TOP = 90


@dataclass
class Drawn:
    """Stored values and the answer the condition evaluator reads."""

    values: dict[str, Any] = field(default_factory=dict)
    answer: PreviewAnswer = field(default_factory=PreviewAnswer)


def draw(
    spec: Spec,
    profile: PersonaAnswers | None,
    forced: QuotaTarget | None,
    rng: random.Random,
    shifts: dict[str, float] | None = None,
) -> Drawn:
    """Answer one question.

    Args:
        spec: Answered question.
        profile: This persona's pattern for the question, or None for uniform answers.
        forced: Quota cell the respondent must land in, when this question carries a quota.
        rng: Seeded random source.
        shifts: This respondent's trait pull, keyed by row label (or "" for a number).
            It tilts the persona's weights, so answers that share a trait move together.

    Returns:
        Values keyed by SPSS name, and the answer used for later conditions.
    """
    pull = shifts or {}
    if spec.kind == "single":
        return _single(spec, profile, forced, rng, pull)
    if spec.kind == "multi":
        return _multi(spec, profile, forced, rng, pull)
    if spec.kind == "grid":
        return _grid(spec, profile, rng, pull)
    if spec.kind == "rank":
        return _rank(spec, profile, rng, pull)
    if spec.kind == "allocation":
        return _allocation(spec, profile, rng, pull)
    if spec.kind == "number":
        return _number(spec, profile, forced, rng, pull)
    if spec.kind == "date":
        day = _DATE_START + timedelta(days=rng.randrange(365))
        text = day.isoformat()
        return Drawn({spec.names[0]: text}, PreviewAnswer(value=text))
    text = _verbatim(profile, rng)
    return Drawn({spec.names[0]: text}, PreviewAnswer(value=text))


def code_value(code: str) -> int | float | str:
    """Store a numeric code as a number.

    Args:
        code: Code text.

    Returns:
        Int or float when the code is numeric, otherwise the text.
    """
    try:
        number = float(code)
    except ValueError:
        return code
    return int(number) if number.is_integer() else number


def match_choice(choices: list[Choice], key: str) -> Choice | None:
    """Find a choice by code, label, or text.

    Args:
        choices: Rows or columns.
        key: What the model or a quota named.

    Returns:
        The choice, or None.
    """
    wanted = key.strip().casefold()
    for attribute in ("code", "label", "text"):
        for choice in choices:
            if getattr(choice, attribute).strip().casefold() == wanted:
                return choice
    return None


def _weights(
    choices: list[Choice], weights: list[Weight], ending: set[str] | None = None
) -> list[float]:
    """Line weights up with choices. Uniform when the model gave none that match.

    Args:
        choices: Rows or columns.
        weights: Model weights.
        ending: Row labels that lead to a terminate. Without model weights they
            get a small share, so a uniform run still completes.

    Returns:
        One non-negative weight per choice.
    """
    lined = [0.0] * len(choices)
    for weight in weights:
        choice = match_choice(choices, weight.code)
        if choice is not None:
            lined[choices.index(choice)] = max(0.0, float(weight.weight))
    if sum(lined) <= 0:
        return [_END_SHARE if choice.label in (ending or set()) else 1.0 for choice in choices]
    return lined


def _tilt(choices: list[Choice], weights: list[float], pull: dict[str, float]) -> list[float]:
    """Scale each weight by exp(pull), so a high trait favors the codes it loads on.

    Args:
        choices: Rows.
        weights: Persona weights.
        pull: Shift per row label.

    Returns:
        Tilted weights.
    """
    return [
        weight * math.exp(_clamp(pull.get(choice.label, 0.0)))
        for choice, weight in zip(choices, weights, strict=True)
    ]


def _clamp(value: float) -> float:
    """Keep one shift inside a range that tilts without wiping out other answers."""
    return max(-_SHIFT_LIMIT, min(_SHIFT_LIMIT, value))


def _scale_positions(cols: list[Choice]) -> list[float | None]:
    """Place scale columns from -1 (lowest code) to 1 (highest code).

    Codes of 90 and above, such as don't know, and text codes are not on the scale.

    Args:
        cols: Grid columns.

    Returns:
        Position per column, or None for a column that is not on the scale.
    """
    numbers = [code_value(col.code) for col in cols]
    scale = sorted({n for n in numbers if not isinstance(n, str) and n < _SCALE_TOP})
    if len(scale) < 2:
        return [None] * len(cols)
    low, high = scale[0], scale[-1]
    return [
        (2 * (n - low) / (high - low) - 1) if not isinstance(n, str) and n in scale else None
        for n in numbers
    ]


def _pick(choices: list[Choice], weights: list[float], rng: random.Random) -> Choice:
    """Pick one choice by weight.

    Args:
        choices: Candidates.
        weights: Weights.
        rng: Random source.

    Returns:
        One choice.
    """
    if sum(weights) <= 0:
        return rng.choice(choices)
    return rng.choices(choices, weights=weights, k=1)[0]


def _single(
    spec: Spec,
    profile: PersonaAnswers | None,
    forced: QuotaTarget | None,
    rng: random.Random,
    pull: dict[str, float],
) -> Drawn:
    """Answer a single select."""
    chosen = match_choice(spec.rows, forced.code or "") if forced and forced.code else None
    if chosen is None:
        weights = _weights(spec.rows, profile.weights if profile else [], spec.ending)
        weights = _tilt(spec.rows, weights, pull)
        chosen = _pick(spec.rows, weights, rng)
    drawn = Drawn({spec.names[0]: code_value(chosen.code)}, PreviewAnswer(rows=[chosen.label]))
    _open_text(spec, [chosen], profile, rng, drawn)
    return drawn


def _multi(
    spec: Spec,
    profile: PersonaAnswers | None,
    forced: QuotaTarget | None,
    rng: random.Random,
    pull: dict[str, float],
) -> Drawn:
    """Answer a multi-select. Each row weight is read as a selection probability."""
    raw = _weights(spec.rows, profile.weights if profile else [])
    top = max(raw) if raw else 1.0
    chances = [value / top if top > 1 else value for value in raw]
    if not profile or not profile.weights:
        chances = [0.35] * len(spec.rows)
    chances = [
        _shift_chance(chance, pull.get(row.label, 0.0))
        for row, chance in zip(spec.rows, chances, strict=True)
    ]
    exclusive = [index for index, row in enumerate(spec.rows) if row.exclusive]
    picked: list[int] = []
    want = match_choice(spec.rows, forced.code or "") if forced and forced.code else None
    if want is not None and want.exclusive:
        picked = [spec.rows.index(want)]
    else:
        none_chance = max((chances[index] for index in exclusive), default=0.0)
        if exclusive and want is None and rng.random() < none_chance * 0.5:
            picked = [rng.choices(exclusive, weights=[chances[i] + 1e-6 for i in exclusive])[0]]
        else:
            picked = [
                index
                for index, chance in enumerate(chances)
                if index not in exclusive and rng.random() < chance
            ]
            if want is not None and spec.rows.index(want) not in picked:
                picked.append(spec.rows.index(want))
            minimum = max(spec.atleast or 0, 1 if spec.required else 0)
            pool = [i for i in range(len(spec.rows)) if i not in exclusive and i not in picked]
            while len(picked) < minimum and pool:
                extra = rng.choices(pool, weights=[raw[i] + 1e-6 for i in pool])[0]
                picked.append(extra)
                pool.remove(extra)
    picked.sort()
    values = {name: int(index in picked) for index, name in enumerate(spec.names)}
    rows = [spec.rows[index] for index in picked]
    drawn = Drawn(values, PreviewAnswer(rows=[row.label for row in rows]))
    _open_text(spec, rows, profile, rng, drawn)
    return drawn


def _shift_chance(chance: float, shift: float) -> float:
    """Move a probability on the logit scale."""
    if not shift:
        return chance
    bounded = min(max(chance, 0.001), 0.999)
    logit = math.log(bounded / (1 - bounded)) + _clamp(shift)
    return 1 / (1 + math.exp(-logit))


def _grid(
    spec: Spec, profile: PersonaAnswers | None, rng: random.Random, pull: dict[str, float]
) -> Drawn:
    """Answer every grid row with one column. A row's pull moves it up or down the scale."""
    positions = _scale_positions(spec.cols)
    by_row = {}
    for item in profile.grid if profile else []:
        row = match_choice(spec.rows, item.row)
        if row is not None:
            by_row[row.label] = item.weights
    shared = profile.weights if profile else []
    values: dict[str, Any] = {}
    cells: dict[str, str] = {}
    for index, row in enumerate(spec.rows):
        weights = _weights(spec.cols, by_row.get(row.label) or shared)
        shift = _clamp(pull.get(row.label, 0.0))
        if shift:
            weights = [
                weight * math.exp(shift * position) if position is not None else weight
                for weight, position in zip(weights, positions, strict=True)
            ]
        column = _pick(spec.cols, weights, rng)
        values[spec.names[index]] = code_value(column.code)
        cells[row.label] = column.label
    return Drawn(values, PreviewAnswer(cells=cells))


def _rank(
    spec: Spec, profile: PersonaAnswers | None, rng: random.Random, pull: dict[str, float]
) -> Drawn:
    """Rank items by drawing without replacement, most appealing first."""
    weights = _tilt(spec.rows, _weights(spec.rows, profile.weights if profile else []), pull)
    positions = min(spec.positions or len(spec.rows), len(spec.rows))
    order: list[int] = []
    pool = list(range(len(spec.rows)))
    for _ in range(positions):
        index = rng.choices(pool, weights=[weights[i] + 1e-6 for i in pool])[0]
        order.append(index)
        pool.remove(index)
    values: dict[str, Any] = {name: None for name in spec.names}
    row_values: dict[str, str] = {}
    for rank, index in enumerate(order, start=1):
        values[spec.names[index]] = rank
        row_values[spec.rows[index].label] = str(rank)
    return Drawn(values, PreviewAnswer(row_values=row_values))


def _allocation(
    spec: Spec, profile: PersonaAnswers | None, rng: random.Random, pull: dict[str, float]
) -> Drawn:
    """Split 100 points across rows in proportion to random draws around the weights."""
    weights = _tilt(spec.rows, _weights(spec.rows, profile.weights if profile else []), pull)
    total = sum(weights) or 1.0
    draws = [rng.gammavariate(1.0 + 8.0 * weight / total, 1.0) for weight in weights]
    scale = sum(draws) or 1.0
    shares = [100 * value / scale for value in draws]
    points = [int(share) for share in shares]
    order = sorted(range(len(shares)), key=lambda i: shares[i] - points[i], reverse=True)
    for index in order[: 100 - sum(points)]:
        points[index] += 1
    values = {name: points[index] for index, name in enumerate(spec.names)}
    row_values = {row.label: str(points[index]) for index, row in enumerate(spec.rows)}
    return Drawn(values, PreviewAnswer(row_values=row_values))


def _number(
    spec: Spec,
    profile: PersonaAnswers | None,
    forced: QuotaTarget | None,
    rng: random.Random,
    pull: dict[str, float],
) -> Drawn:
    """Draw a number from a triangular distribution inside every known bound."""
    lower = _first(profile.minimum if profile else None, spec.lower, 0.0)
    upper = _first(profile.maximum if profile else None, spec.upper, 10.0)
    if spec.lower is not None:
        lower = max(lower, spec.lower)
    if spec.upper is not None:
        upper = min(upper, spec.upper)
    if forced is not None:
        lower = forced.lower if forced.lower is not None else lower
        upper = forced.upper if forced.upper is not None else upper
    if upper < lower:
        lower, upper = upper, lower
    typical = profile.typical if profile and profile.typical is not None else None
    mode = typical if typical is not None else (lower + upper) / 2
    # Reason: one unit of trait moves the most likely value by a quarter of the range.
    mode = min(max(mode + _clamp(pull.get("", 0.0)) * (upper - lower) / 4, lower), upper)
    whole = all(float(bound).is_integer() for bound in (lower, upper))
    value: int | float = rng.triangular(lower, upper, mode)
    if whole:
        value = min(max(round(value), int(lower)), int(upper))
    else:
        value = round(value, 2)
    return Drawn({spec.names[0]: value}, PreviewAnswer(value=str(value)))


def _first(*values: float | None) -> float:
    """Return the first value that is set."""
    for value in values:
        if value is not None:
            return float(value)
    return 0.0


def _verbatim(profile: PersonaAnswers | None, rng: random.Random) -> str:
    """Pick one of the persona's example verbatims."""
    pool = [text.strip() for text in (profile.verbatims if profile else []) if text.strip()]
    return rng.choice(pool) if pool else _FALLBACK_TEXT


def _open_text(
    spec: Spec,
    rows: list[Choice],
    profile: PersonaAnswers | None,
    rng: random.Random,
    drawn: Drawn,
) -> None:
    """Fill the specify box for any chosen row that has one."""
    for row in rows:
        name = spec.open_names.get(row.label)
        if name:
            text = _verbatim(profile, rng) if profile and profile.verbatims else row.text
            drawn.values[name] = text
            drawn.answer.open_text[row.label] = text
