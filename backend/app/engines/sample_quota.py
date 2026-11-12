"""Planned quota cells and the completion reward for a priced sample."""

import math

from app.schemas.sample_purchase import AudienceFilter, QuotaCell


def planned_cells(filters: list[AudienceFilter], sample_size: int) -> list[QuotaCell]:
    """Spread the sample across weighted filters.

    Args:
        filters: Audience filters.
        sample_size: Completed places.

    Returns:
        Planned cells. Unweighted filters stay eligibility rules and are not cells.
    """
    dimensions = [item for item in (_dimension(row) for row in filters) if item]
    if not dimensions:
        return [QuotaCell(labels=["All eligible"], places=sample_size)]
    if len(dimensions) == 1:
        return _places_from_shares(dimensions[0], sample_size)
    first, second = dimensions[0], dimensions[1]
    shares = [(left[0] + right[0], left[1] * right[1]) for left in first for right in second]
    return _places_from_shares(shares, sample_size)


def reward_for_minutes(per_hour: int, minimum_per_hour: int, minutes: int) -> tuple[int, bool]:
    """Convert an hourly rate into a completion reward.

    Args:
        per_hour: Recommended hourly amount in cents or pence.
        minimum_per_hour: Floor hourly amount.
        minutes: Estimated minutes.

    Returns:
        Reward, and whether it was raised to the minimum.
    """
    recommended = max(1, int(round(per_hour * minutes / 60)))
    floor = max(1, int(math.ceil(minimum_per_hour * minutes / 60)))
    if recommended < floor:
        return floor, True
    return recommended, False


def screenout_amount(reward_cents: int, minimum_per_hour: int) -> int:
    """Return a screen-out reward that is below the completion reward.

    Args:
        reward_cents: Completion reward.
        minimum_per_hour: Hourly floor, used as a one-minute guide.

    Returns:
        Screen-out amount, or 0 when the completion reward cannot sit above it.
    """
    if reward_cents <= 1:
        return 0
    one_minute = max(1, int(math.ceil(minimum_per_hour / 60)))
    return min(reward_cents - 1, one_minute)


def _dimension(item: AudienceFilter) -> list[tuple[list[str], float]]:
    """Return weighted labels for one filter.

    Args:
        item: Audience filter.

    Returns:
        Label lists and raw weights. Empty when the filter is not a quota.
    """
    if item.age_bands:
        return [([f"{band.lower}–{band.upper}"], band.weighting) for band in item.age_bands]
    if item.weightings:
        return [
            ([item.choice_labels.get(choice_id, choice_id)], weight)
            for choice_id, weight in item.weightings.items()
        ]
    return []


def _places_from_shares(shares: list[tuple[list[str], float]], sample_size: int) -> list[QuotaCell]:
    """Allocate integer places from relative weights.

    Args:
        shares: Labels and weights.
        sample_size: Completed places.

    Returns:
        Cells. The last cell absorbs the rounding remainder.
    """
    total = sum(weight for _labels, weight in shares)
    if total <= 0:
        return []
    raw = [sample_size * weight / total for _labels, weight in shares]
    places = [int(math.floor(value)) for value in raw]
    leftover = sample_size - sum(places)
    order = sorted(range(len(raw)), key=lambda index: raw[index] - places[index], reverse=True)
    for index in order[:leftover]:
        places[index] += 1
    return [
        QuotaCell(labels=labels, places=count)
        for (labels, _weight), count in zip(shares, places, strict=True)
    ]
