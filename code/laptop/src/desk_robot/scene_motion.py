"""Shared exposure-compensated motion scoring for camera consumers."""
from statistics import median


def _lighting_transform(a: bytes, b: bytes) -> tuple[float, float, bool]:
    count = len(a)
    sum_a, sum_b = sum(a), sum(b)
    sum_aa = sum(x * x for x in a)
    sum_bb = sum(y * y for y in b)
    sum_ab = sum(x * y for x, y in zip(a, b, strict=True))
    variance_a = count * sum_aa - sum_a * sum_a
    variance_b = count * sum_bb - sum_b * sum_b
    covariance = count * sum_ab - sum_a * sum_b
    gain = 1.0
    fitted = False
    if (variance_a > count * count * 30
            and variance_b > count * count * 30
            and covariance > 0
            and covariance * covariance >= 0.90 * variance_a * variance_b):
        candidate_gain = covariance / variance_a
        if 0.55 <= candidate_gain <= 2.5:
            gain = candidate_gain
            fitted = True
    if not fitted:
        # A local occlusion must not shift the inferred brightness of every
        # unchanged pixel. The median additive residual is robust to a
        # minority of changed pixels when an affine fit is unreliable.
        return gain, median(y - x for x, y in zip(a, b, strict=True)), fitted
    return gain, (sum_b - gain * sum_a) / count, fitted


def _scene_change_mask(a: bytes, b: bytes, gain: float, offset: float,
                       threshold: int, *, clamp: bool = False) -> bytes:
    """Encode significant residual direction: 0 unchanged, 1 brighter, 2 darker."""
    residuals = (
        y - (min(255, max(0, gain * x + offset)) if clamp else gain * x + offset)
        for x, y in zip(a, b, strict=True)
    )
    return bytes(1 if delta >= threshold else 2 if delta <= -threshold else 0
                 for delta in residuals)


def scene_change_mask(a: bytes, b: bytes, *, threshold: int = 16) -> bytes:
    """Ignore broad lighting shifts while retaining signed localized changes."""
    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError("Scene change threshold must be an integer in [1, 255]")
    if len(a) != len(b) or len(a) != 64 * 48:
        raise ValueError("Frame fingerprints have incompatible dimensions")
    count = len(a)
    gain, offset, _ = _lighting_transform(a, b)
    changed = _scene_change_mask(a, b, gain, offset, threshold)
    if changed.count(0) == count or not any(
        (y <= 8 or y >= 247) and x != y for x, y in zip(a, b, strict=True)
    ):
        return changed
    # Newly clipped highlights/shadows bias an ordinary affine fit. Refit
    # only when at least half the corresponding samples remain measurable.
    # Score ALL pixels, including saturated ones, against the clamped model;
    # never blanket-mask clipping (a real dark object can cover a bright pixel).
    pairs = [
        (x, y) for x, y in zip(a, b, strict=True)
        if 8 < x < 247 and 8 < y < 247
    ]
    if len(pairs) < count // 2:
        return changed
    valid_a, valid_b = map(bytes, zip(*pairs, strict=True))
    gain, offset, fitted = _lighting_transform(valid_a, valid_b)
    if not fitted:
        return changed
    clipped = _scene_change_mask(a, b, gain, offset, threshold, clamp=True)
    return clipped if clipped.count(0) > changed.count(0) else changed


def change_fraction(a: bytes, b: bytes, *, threshold: int = 16) -> float:
    """Cheap exposure-compensated motion score, not calibrated optical flow."""
    mask = scene_change_mask(a, b, threshold=threshold)
    return (len(mask) - mask.count(0)) / len(mask)


def consistent_change_mask(previous: bytes | None, current: bytes) -> bool:
    """Require half the smaller nonempty changed region to persist with the same sign."""
    if previous is None:
        return False
    overlap = sum(old != 0 and old == new for old, new in zip(previous, current, strict=True))
    smaller = min(len(previous) - previous.count(0), len(current) - current.count(0))
    return smaller > 0 and 2 * overlap >= smaller
