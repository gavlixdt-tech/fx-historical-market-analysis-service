"""Retrospective change-point detection (binary segmentation)."""

from __future__ import annotations


def _cost(series: list[float], start: int, end: int) -> float:
    # Sum of squared deviations from the segment mean.
    segment = series[start:end]
    if not segment:
        return 0.0
    mean = sum(segment) / len(segment)
    return sum((x - mean) ** 2 for x in segment)


def binary_segmentation(
    series: list[float],
    *,
    min_segment_length: int = 10,
    max_change_points: int = 10,
    penalty: float = 1.0,
) -> list[int]:
    """Return sorted change-point indices (start index of new segment).

    Retrospective only: the full series is required.
    """
    n = len(series)
    if n < 2 * min_segment_length:
        return []
    change_points: list[int] = []
    segments: list[tuple[int, int]] = [(0, n)]

    for _ in range(max_change_points):
        best_reduction = 0.0
        best_split: int | None = None
        best_segment: tuple[int, int] | None = None
        for seg in segments:
            s, e = seg
            if e - s < 2 * min_segment_length:
                continue
            base_cost = _cost(series, s, e)
            for split in range(s + min_segment_length, e - min_segment_length + 1):
                reduction = base_cost - _cost(series, s, split) - _cost(series, split, e)
                if reduction > best_reduction:
                    best_reduction = reduction
                    best_split = split
                    best_segment = seg
        if best_split is None or best_reduction <= penalty:
            break
        if best_segment is None:
            break
        segments.remove(best_segment)
        s, e = best_segment
        segments.append((s, best_split))
        segments.append((best_split, e))
        change_points.append(best_split)
        change_points.sort()
    return sorted(set(change_points))


def detect_change_points_combined(
    returns: list[float],
    *,
    min_segment_length: int = 10,
    max_change_points: int = 10,
    penalty: float = 1.0,
) -> list[int]:
    """Detect changes in mean (returns) and dispersion (abs returns)."""
    mean_cps = binary_segmentation(
        returns,
        min_segment_length=min_segment_length,
        max_change_points=max_change_points,
        penalty=penalty,
    )
    abs_returns = [abs(r) for r in returns]
    vol_cps = binary_segmentation(
        abs_returns,
        min_segment_length=min_segment_length,
        max_change_points=max_change_points,
        penalty=penalty,
    )
    return sorted(set(mean_cps + vol_cps))
