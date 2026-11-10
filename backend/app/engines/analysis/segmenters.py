"""Distance and segment assignment used by the analysis procedures."""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, AgglomerativeClustering, SpectralClustering
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from app.errors import AppError

_MAX_ROWS = 4000


def gower_distance(data: pd.DataFrame, categorical: set[str]) -> np.ndarray:
    """Return pairwise Gower distances.

    Args:
        data: Complete numeric frame.
        categorical: Columns compared by mismatch. Other columns use their range.

    Returns:
        Square distance matrix with a zero diagonal.

    Raises:
        AppError: The frame has no columns, or more rows than a full matrix allows.
    """
    values = data.to_numpy(dtype=float)
    row_count, column_count = values.shape
    if column_count == 0:
        raise AppError("Gower distance needs at least one column.", "bad_plan")
    if row_count > _MAX_ROWS:
        raise AppError(
            "PAM with Gower distance needs 4000 or fewer complete rows. No result was published.",
            "small_sample",
        )
    distance = np.zeros((row_count, row_count), dtype=float)
    for index, name in enumerate(data.columns):
        column = values[:, index]
        span = float(np.nanmax(column) - np.nanmin(column))
        if name in categorical or span == 0.0:
            distance += (column[:, None] != column[None, :]).astype(float)
        else:
            distance += np.abs(column[:, None] - column[None, :]) / span
    distance /= column_count
    np.fill_diagonal(distance, 0.0)
    return distance


def pam(
    data: pd.DataFrame, k: int, seed: int, categorical: set[str]
) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    """PAM on a Gower distance matrix.

    Args:
        data: Complete features.
        k: Segment count.
        seed: Random seed.
        categorical: Nominal columns.

    Returns:
        Labels, metrics, and warnings.
    """
    distance = gower_distance(data, categorical)
    rng = np.random.default_rng(seed)
    medoids = [int(rng.integers(0, len(data)))]
    for _ in range(1, k):
        nearest = distance[:, medoids].min(axis=1)
        weights = nearest**2
        total = float(weights.sum())
        if total <= 0:
            medoids.append(int(rng.integers(0, len(data))))
        else:
            medoids.append(int(rng.choice(len(data), p=weights / total)))
    chosen = np.array(medoids, dtype=int)
    labels = np.argmin(distance[:, chosen], axis=1)
    for _ in range(25):
        updated = chosen.copy()
        for cluster in range(k):
            members = np.flatnonzero(labels == cluster)
            if len(members) == 0:
                continue
            block = distance[np.ix_(members, members)]
            updated[cluster] = members[int(np.argmin(block.sum(axis=1)))]
        refreshed = np.argmin(distance[:, updated], axis=1)
        stable = np.array_equal(chosen, updated) and np.array_equal(labels, refreshed)
        chosen = updated
        labels = refreshed
        if stable:
            break
    return (
        labels.astype(int),
        {
            "silhouette": _precomputed(distance, labels),
            "within_distance": _within(distance, labels),
        },
        ["PAM used Gower distance. Segment labels depend on the seed."],
    )


def hierarchical(
    data: pd.DataFrame, method: str, k: int, categorical: set[str]
) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    """Agglomerative clustering, on Gower distance when the name says so.

    Args:
        data: Complete features.
        method: Normalized method name.
        k: Segment count.
        categorical: Nominal columns.

    Returns:
        Labels, metrics, and warnings.
    """
    if "gower" in method:
        distance = gower_distance(data, categorical)
        labels = AgglomerativeClustering(
            n_clusters=k, metric="precomputed", linkage="average"
        ).fit_predict(distance)
        warning = "Hierarchical clustering used average linkage on Gower distance."
        if "ward" in method:
            warning = "Ward linkage needs Euclidean distance, so average linkage on Gower distance was used."
        return labels.astype(int), {"silhouette": _precomputed(distance, labels)}, [warning]
    linkage = "average" if "average" in method else "complete" if "complete" in method else "ward"
    scaled = StandardScaler().fit_transform(data)
    labels = AgglomerativeClustering(n_clusters=k, linkage=linkage).fit_predict(scaled)
    return (
        labels.astype(int),
        {"silhouette": _euclidean(scaled, labels)},
        [f"Hierarchical clustering used {linkage} linkage on standardized features."],
    )


def dbscan(data: pd.DataFrame, seed: int) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    """DBSCAN on standardized features.

    Args:
        data: Complete features.
        seed: Unused. DBSCAN as used here has no seed.

    Returns:
        Labels. Noise is ``-1``.

    Raises:
        AppError: Every row is noise.
    """
    del seed
    scaled = StandardScaler().fit_transform(data)
    min_samples = min(len(data) - 1, max(5, int(len(data) * 0.02)))
    labels = DBSCAN(eps=0.8, min_samples=min_samples).fit_predict(scaled)
    if set(labels.tolist()) <= {-1}:
        raise AppError(
            "DBSCAN marked every respondent as noise. No segments were published.",
            "small_sample",
        )
    return (
        labels.astype(int),
        {"silhouette": _euclidean(scaled, labels)},
        ["DBSCAN used standardized features, eps 0.8, and left noise labeled -1."],
    )


def mixture(data: pd.DataFrame, k: int, seed: int) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    """Gaussian mixture on standardized features.

    Args:
        data: Complete features.
        k: Component count.
        seed: Random seed.

    Returns:
        Labels, metrics, and warnings.
    """
    scaled = StandardScaler().fit_transform(data)
    labels = GaussianMixture(n_components=k, random_state=seed, n_init=5).fit_predict(scaled)
    return (
        labels.astype(int),
        {"silhouette": _euclidean(scaled, labels)},
        ["Gaussian mixture used standardized features."],
    )


def spectral(data: pd.DataFrame, k: int, seed: int) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    """Spectral clustering on standardized features.

    Args:
        data: Complete features.
        k: Segment count.
        seed: Random seed.

    Returns:
        Labels, metrics, and warnings.
    """
    scaled = StandardScaler().fit_transform(data)
    neighbors = min(10, len(data) - 1)
    labels = SpectralClustering(
        n_clusters=k,
        random_state=seed,
        affinity="nearest_neighbors",
        n_neighbors=neighbors,
        assign_labels="kmeans",
    ).fit_predict(scaled)
    return (
        labels.astype(int),
        {"silhouette": _euclidean(scaled, labels)},
        ["Spectral clustering used nearest-neighbor affinity on standardized features."],
    )


def _precomputed(distance: np.ndarray, labels: np.ndarray) -> float | None:
    """Return a precomputed silhouette, or None when it is undefined.

    Args:
        distance: Square distance matrix.
        labels: Segment labels.

    Returns:
        Silhouette, or None.
    """
    if len(set(labels.tolist())) < 2:
        return None
    try:
        return float(silhouette_score(distance, labels, metric="precomputed"))
    except ValueError:
        return None


def _euclidean(scaled: np.ndarray, labels: np.ndarray) -> float | None:
    """Return a Euclidean silhouette, or None when it is undefined.

    Args:
        scaled: Feature matrix.
        labels: Segment labels.

    Returns:
        Silhouette, or None.
    """
    if len(set(labels.tolist())) < 2:
        return None
    try:
        return float(silhouette_score(scaled, labels))
    except ValueError:
        return None


def _within(distance: np.ndarray, labels: np.ndarray) -> float:
    """Return the total within-segment Gower distance.

    Args:
        distance: Square distance matrix.
        labels: Segment labels.

    Returns:
        Sum of distances from each row to the other rows in its segment.
    """
    total = 0.0
    for cluster in set(labels.tolist()):
        members = np.flatnonzero(labels == cluster)
        if len(members) > 1:
            total += float(distance[np.ix_(members, members)].sum()) / 2.0
    return total
