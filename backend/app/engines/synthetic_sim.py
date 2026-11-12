"""Walk synthetic respondents through the survey flow until the sample is complete.

Quota cells are assigned in exact counts. Each slot then gets the persona that
fits its quota cells, in proportion to the persona shares, so a slot in the
50-65 age cell is rarely a young persona. Each respondent carries trait values
around the persona's levels. Loadings turn those traits into shifts on related
answers, so answers within one respondent move together.

A respondent who reaches a visible terminate is replaced by a new draw for the
same slot, so terminates affect incidence and not the completed counts.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.engines.decipher_cond import ConditionError, condition_holds
from app.engines.decipher_preview import _apply
from app.engines.synthetic_draw import _weights, draw, match_choice
from app.engines.synthetic_survey import Spec
from app.errors import AppError
from app.schemas.synthetic import Persona, PersonaAnswers, QuestionProfile, QuotaTarget

_ATTEMPTS = 200
_TRAIT_SPREAD = 0.7
_FIT_FLOOR = 0.02
_RAKE_ROUNDS = 8


@dataclass
class Respondent:
    """One completed synthetic interview."""

    persona: str
    values: dict[str, Any] = field(default_factory=dict)
    asked: set[str] = field(default_factory=set)


@dataclass
class Simulation:
    """Completed respondents and what it took to get them."""

    respondents: list[Respondent]
    attempts: int
    terminated: int
    terms: Counter
    quota_cells: list[tuple[QuotaTarget, int]]
    warnings: list[str]


def simulate(
    specs: list[Spec],
    personas: list[Persona],
    quotas: list[QuotaTarget],
    profiles: dict[str, QuestionProfile],
    sample_size: int,
    seed: int,
) -> Simulation:
    """Generate completed interviews.

    Args:
        specs: Survey steps in order.
        personas: Personas with shares. An empty list uses one general persona.
        quotas: Quota cells already checked against the specs.
        profiles: Answer patterns keyed by question label.
        sample_size: Completes wanted.
        seed: Random seed, stored so the file can be regenerated.

    Returns:
        Simulation.

    Raises:
        AppError: Every attempt for one slot ended at a terminate.
    """
    rng = random.Random(seed)
    people = personas or [Persona(name="General", share=1.0)]
    by_question: dict[str, list[QuotaTarget]] = defaultdict(list)
    for target in quotas:
        by_question[target.question].append(target)
    quota_slots: dict[str, list[QuotaTarget | None]] = {}
    cells: list[tuple[QuotaTarget, int]] = []
    for question, targets in by_question.items():
        counts = _counts([target.share for target in targets], sample_size)
        cells.extend(zip(targets, counts, strict=True))
        slots: list[QuotaTarget | None] = []
        for target, count in zip(targets, counts, strict=True):
            slots.extend([target] * count)
        rng.shuffle(slots)
        quota_slots[question] = slots
    by_label = {spec.label: spec for spec in specs if spec.answered}
    forced_slots = [
        {question: slots[slot] for question, slots in quota_slots.items()}
        for slot in range(sample_size)
    ]
    persona_slots = _match_personas(people, forced_slots, profiles, by_label, rng)
    loadings = _loadings(specs, profiles)
    levels = {
        item.name: {level.trait.strip().casefold(): level.level for level in item.traits}
        for item in people
    }
    index_of = {spec.label: index for index, spec in enumerate(specs) if spec.label}
    warned: set[str] = set()
    respondents: list[Respondent] = []
    terms: Counter = Counter()
    attempts = 0
    for slot in range(sample_size):
        persona = persona_slots[slot]
        forced = forced_slots[slot]
        for _ in range(_ATTEMPTS):
            attempts += 1
            traits = {
                trait: level + rng.gauss(0.0, _TRAIT_SPREAD)
                for trait, level in levels.get(persona, {}).items()
            }
            outcome = _interview(
                specs, index_of, persona, forced, profiles, rng, warned, loadings, traits
            )
            if isinstance(outcome, Respondent):
                respondents.append(outcome)
                break
            terms[outcome] += 1
        else:
            common = terms.most_common(1)[0][0] if terms else "a terminate"
            raise AppError(
                f"Synthetic respondents kept ending at {common}, so the sample could not be "
                "completed. Check that screener and the quota targets.",
                "synthetic_blocked",
            )
    return Simulation(
        respondents=respondents,
        attempts=attempts,
        terminated=sum(terms.values()),
        terms=terms,
        quota_cells=cells,
        warnings=sorted(warned),
    )


def _interview(
    specs: list[Spec],
    index_of: dict[str, int],
    persona: str,
    forced: dict[str, QuotaTarget | None],
    profiles: dict[str, QuestionProfile],
    rng: random.Random,
    warned: set[str],
    loadings: dict[str, list[tuple[str, str, float]]] | None = None,
    traits: dict[str, float] | None = None,
) -> Respondent | str:
    """Walk one respondent through the survey.

    Args:
        specs: Survey steps.
        index_of: Step index by label, for gotos.
        persona: Persona name.
        forced: Quota cell per question for this slot.
        profiles: Answer patterns.
        rng: Random source.
        warned: Collected warnings, shared across respondents.
        loadings: Per question, (trait, row label, effect) triples.
        traits: This respondent's trait values.

    Returns:
        The completed respondent, or the label of the terminate that ended the interview.
    """
    facts: dict[str, Any] = {}
    person = Respondent(persona=persona)
    jumps: set[int] = set()
    index = 0
    while index < len(specs):
        spec = specs[index]
        shown = _shown(spec, facts, warned)
        if spec.kind == "goto" and shown:
            if index in jumps or spec.target not in index_of:
                warned.add(
                    f"Goto {spec.label or spec.target} was skipped because its target loops or is missing."
                )
                index += 1
                continue
            jumps.add(index)
            index = index_of[spec.target]
            continue
        if spec.kind == "term" and shown:
            return spec.label or "a terminate"
        if spec.kind == "loop" and shown:
            warned.add(f"{spec.label} is a loop with no questions inside, so it has no data.")
        if spec.answered and shown:
            profile = _persona_profile(profiles.get(spec.label), persona)
            shifts = _shifts((loadings or {}).get(spec.label, []), traits or {})
            drawn = draw(spec, profile, forced.get(spec.label), rng, shifts)
            person.values.update(drawn.values)
            person.asked.add(spec.label)
            _apply(facts, spec.label, drawn.answer)
        index += 1
    return person


def _shifts(items: list[tuple[str, str, float]], traits: dict[str, float]) -> dict[str, float]:
    """Add up trait effects per row label for one respondent."""
    found: dict[str, float] = {}
    for trait, label, effect in items:
        if trait in traits:
            found[label] = found.get(label, 0.0) + effect * traits[trait]
    return found


def _loadings(
    specs: list[Spec], profiles: dict[str, QuestionProfile]
) -> dict[str, list[tuple[str, str, float]]]:
    """Resolve each loading's target to a row label once, before the interviews.

    Args:
        specs: Survey steps.
        profiles: Answer patterns with loadings.

    Returns:
        Question label to (trait, row label, effect). A number uses an empty label.
        Targets that name no row are dropped.
    """
    found: dict[str, list[tuple[str, str, float]]] = {}
    for spec in specs:
        profile = profiles.get(spec.label)
        if not spec.answered or profile is None:
            continue
        items: list[tuple[str, str, float]] = []
        for loading in profile.loadings:
            trait = loading.trait.strip().casefold()
            effect = max(-2.0, min(2.0, float(loading.effect)))
            if spec.kind == "number":
                items.append((trait, "", effect))
                continue
            row = match_choice(spec.rows, loading.target)
            if row is not None:
                items.append((trait, row.label, effect))
        if items:
            found[spec.label] = items
    return found


def _match_personas(
    people: list[Persona],
    forced_slots: list[dict[str, QuotaTarget | None]],
    profiles: dict[str, QuestionProfile],
    by_label: dict[str, Spec],
    rng: random.Random,
) -> list[str]:
    """Give each slot a persona that fits its quota cells, keeping the persona shares.

    Each persona's chance for a slot is its share times how likely its own answers
    land in the slot's cells. The shares are then raked so the expected counts
    match the plan before each slot is drawn.

    Args:
        people: Personas.
        forced_slots: Quota cells per slot.
        profiles: Answer patterns, used to judge fit.
        by_label: Answered specs by label.
        rng: Random source.

    Returns:
        Persona name per slot.
    """
    names = [item.name for item in people]
    total = sum(max(item.share, 0.0) for item in people) or 1.0
    shares = [max(item.share, 0.0) / total for item in people]
    if not any(any(cell is not None for cell in forced.values()) for forced in forced_slots):
        return _slots(list(zip(names, shares, strict=True)), len(forced_slots), rng)
    fits = [
        [
            math.prod(
                _fit(name, cell, profiles, by_label) for cell in forced.values() if cell is not None
            )
            for name in names
        ]
        for forced in forced_slots
    ]
    scale = [1.0] * len(people)
    for _ in range(_RAKE_ROUNDS):
        expected = [0.0] * len(people)
        for row in fits:
            weights = [scale[i] * shares[i] * row[i] for i in range(len(people))]
            mass = sum(weights) or 1.0
            for i, weight in enumerate(weights):
                expected[i] += weight / mass
        for i in range(len(people)):
            wanted = shares[i] * len(fits)
            if expected[i] > 0 and wanted > 0:
                scale[i] *= wanted / expected[i]
    return [
        rng.choices(names, weights=[scale[i] * shares[i] * row[i] for i in range(len(people))])[0]
        for row in fits
    ]


def _fit(
    persona: str, cell: QuotaTarget, profiles: dict[str, QuestionProfile], by_label: dict[str, Spec]
) -> float:
    """Return how likely a persona's own answers fall in one quota cell.

    Args:
        persona: Persona name.
        cell: Quota cell.
        profiles: Answer patterns.
        by_label: Answered specs.

    Returns:
        A probability with a small floor, or 1 when the persona has no pattern for it.
    """
    spec = by_label.get(cell.question)
    answers = _persona_profile(profiles.get(cell.question), persona)
    if spec is None or answers is None:
        return 1.0
    if spec.kind == "single" and cell.code is not None:
        weights = _weights(spec.rows, answers.weights)
        choice = match_choice(spec.rows, cell.code)
        if choice is None or not sum(weights):
            return 1.0
        return max(weights[spec.rows.index(choice)] / sum(weights), _FIT_FLOOR)
    if spec.kind == "number" and answers.minimum is not None and answers.maximum is not None:
        low, high = float(answers.minimum), float(answers.maximum)
        if high <= low:
            return 1.0
        mode = min(
            max(float(answers.typical if answers.typical is not None else (low + high) / 2), low),
            high,
        )
        lower = cell.lower if cell.lower is not None else low
        upper = cell.upper if cell.upper is not None else high
        mass = _triangular_cdf(upper, low, high, mode) - _triangular_cdf(lower, low, high, mode)
        return max(mass, _FIT_FLOOR)
    return 1.0


def _triangular_cdf(x: float, low: float, high: float, mode: float) -> float:
    """CDF of the triangular distribution used for numbers."""
    if x <= low:
        return 0.0
    if x >= high:
        return 1.0
    if x <= mode:
        return (x - low) ** 2 / ((high - low) * (mode - low)) if mode > low else 0.0
    return 1 - (high - x) ** 2 / ((high - low) * (high - mode)) if high > mode else 1.0


def _shown(spec: Spec, facts: dict[str, Any], warned: set[str]) -> bool:
    """Evaluate a step's condition. A condition the evaluator cannot read counts as shown."""
    if not spec.cond:
        return True
    try:
        return condition_holds(spec.cond, facts)
    except ConditionError:
        warned.add(
            f"{spec.label}: the condition {spec.cond} could not be read, so everyone was shown it."
        )
        return True


def _persona_profile(profile: QuestionProfile | None, persona: str) -> PersonaAnswers | None:
    """Return this persona's answers, or the first persona's when the model skipped it."""
    if profile is None or not profile.personas:
        return None
    for item in profile.personas:
        if item.persona.strip().casefold() == persona.strip().casefold():
            return item
    return profile.personas[0]


def check_quotas(
    specs: list[Spec], quotas: list[QuotaTarget]
) -> tuple[list[QuotaTarget], list[str]]:
    """Keep quota cells that name a real question and answer, with shares that add to 1.

    Args:
        specs: Survey steps.
        quotas: Proposed cells.

    Returns:
        Usable cells and a warning for each one that was dropped.
    """
    by_label = {spec.label: spec for spec in specs if spec.answered}
    kept: list[QuotaTarget] = []
    warnings: list[str] = []
    for target in quotas:
        spec = by_label.get(target.question)
        name = target.label or target.code or f"{_num(target.lower)}-{_num(target.upper)}"
        if spec is None or target.share <= 0:
            warnings.append(f"Quota {target.question} {name} was dropped: no such question.")
            continue
        if spec.kind in {"single", "multi"} and target.code is not None:
            choice = match_choice(spec.rows, target.code)
            if choice is None:
                warnings.append(f"Quota {target.question} {name} was dropped: no such answer.")
                continue
            kept.append(
                target.model_copy(
                    update={"code": choice.code, "label": target.label or choice.text}
                )
            )
            continue
        if spec.kind == "number" and (target.lower is not None or target.upper is not None):
            kept.append(target.model_copy(update={"label": target.label or name}))
            continue
        warnings.append(
            f"Quota {target.question} {name} was dropped: it does not fit that question."
        )
    totals: dict[str, float] = defaultdict(float)
    for target in kept:
        totals[target.question] += target.share
    return [
        target.model_copy(update={"share": target.share / totals[target.question]})
        for target in kept
    ], warnings


def _slots(shares: list[tuple[str, float]], size: int, rng: random.Random) -> list[str]:
    """Assign names to slots in exact counts, then shuffle."""
    counts = _counts([share for _, share in shares], size)
    slots: list[str] = []
    for (name, _), count in zip(shares, counts, strict=True):
        slots.extend([name] * count)
    rng.shuffle(slots)
    return slots


def _counts(shares: list[float], size: int) -> list[int]:
    """Turn shares into whole counts that add up to size, by largest remainder.

    Args:
        shares: Non-negative shares.
        size: Total.

    Returns:
        Counts.
    """
    total = sum(max(share, 0.0) for share in shares) or 1.0
    exact = [size * max(share, 0.0) / total for share in shares]
    counts = [int(value) for value in exact]
    order = sorted(range(len(exact)), key=lambda i: exact[i] - counts[i], reverse=True)
    for index in order[: size - sum(counts)]:
        counts[index] += 1
    return counts


def _num(value: float | None) -> str:
    """Format a bound without a trailing .0."""
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)
