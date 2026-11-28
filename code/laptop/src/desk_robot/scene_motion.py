"""Shared exposure-compensated motion scoring for camera consumers."""
from statistics import median

import numpy as np


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
    if type(a) is not bytes or type(b) is not bytes:
        raise ValueError("Frame fingerprints must be immutable bytes")
    if len(a) != len(b) or len(a) != 64 * 48:
        raise ValueError("Frame fingerprints have incompatible dimensions")
    return _exposure_change_mask(a, b, threshold)


def _exposure_change_mask(a: bytes, b: bytes, threshold: int) -> bytes:
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


def registered_scene_change_mask(a: bytes, b: bytes, *, threshold: int = 16) -> bytes | None:
    """Estimate a bounded global integer translation; score only shared pixels.

    Require distinctive, distributed gradient agreement rather than fitting a
    single moving foreground object. Ambiguous or unsupported shifts return
    None so the caller retains its ordinary exposure-only change mask. This is
    an image registration heuristic, not calibrated camera pose or optical flow.
    """
    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError("Scene change threshold must be an integer in [1, 255]")
    if type(a) is not bytes or type(b) is not bytes:
        raise ValueError("Frame fingerprints must be immutable bytes")
    if len(a) != 64 * 48 or len(b) != 64 * 48:
        raise ValueError("Frame fingerprints have incompatible dimensions")
    before = np.frombuffer(a, dtype=np.uint8).reshape(48, 64).astype(np.int16)
    after = np.frombuffer(b, dtype=np.uint8).reshape(48, 64).astype(np.int16)
    radius = 6
    # Sample the same interior support for every shift. Gradient signs are
    # insensitive to additive exposure and positive gain, unlike raw pixels.
    yy, xx = np.mgrid[radius:48 - radius - 1:3, radius:64 - radius - 1:3]
    y, x = yy.ravel(), xx.ravel()
    dy, dx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    dy, dx = dy.ravel(), dx.ravel()
    by, bx = y[None, :] + dy[:, None], x[None, :] + dx[:, None]
    old = np.concatenate((before[y, x + 1] - before[y, x], before[y + 1, x] - before[y, x]))
    new = np.concatenate((after[by, bx + 1] - after[by, bx],
                          after[by + 1, bx] - after[by, bx]), axis=1)
    textured = np.abs(old) >= 12
    matches = (np.sign(new) == np.sign(old)) & (np.abs(new) >= 6)
    quadrant_scores = []
    for top in (False, True):
        for left in (False, True):
            region = ((y < 24) == top) & ((x < 32) == left)
            active = np.tile(region, 2) & textured
            if np.count_nonzero(active) < 16:
                return None
            quadrant_scores.append(matches[:, active].mean(axis=1))
    scores = np.asarray(quadrant_scores).min(axis=0)
    best = int(np.argmax(scores))
    zero = len(scores) // 2
    # A nonzero winner needs support everywhere, clear improvement over no
    # motion, and separation from alternatives (e.g. repetitive stripes).
    if (best == zero or scores[best] < 0.85 or scores[best] - scores[zero] < 0.15
            or scores[best] - np.partition(scores, -2)[-2] < 0.08):
        return None
    sy, sx = int(dy[best]), int(dx[best])
    y0, y1 = max(0, -sy), min(48, 48 - sy)
    x0, x1 = max(0, -sx), min(64, 64 - sx)
    overlap_a = before[y0:y1, x0:x1].astype(np.uint8).tobytes()
    overlap_b = after[y0 + sy:y1 + sy, x0 + sx:x1 + sx].astype(np.uint8).tobytes()
    residual = _exposure_change_mask(overlap_a, overlap_b, threshold)
    # Keep residuals in baseline coordinates for signed persistence. Newly
    # exposed borders lack corresponding evidence and cannot prove motion.
    result = np.zeros((48, 64), dtype=np.uint8)
    result[y0:y1, x0:x1] = np.frombuffer(residual, dtype=np.uint8).reshape(y1 - y0, x1 - x0)
    return result.tobytes()


def change_fraction(a: bytes, b: bytes, *, threshold: int = 16) -> float:
    """Cheap exposure-compensated motion score, not calibrated optical flow."""
    mask = scene_change_mask(a, b, threshold=threshold)
    return (len(mask) - mask.count(0)) / len(mask)


def consistent_change_mask(previous: bytes | None, current: bytes) -> bool:
    """Require half the smaller nonempty changed region to persist with the same sign."""
    if type(current) is not bytes or max(current, default=0) > 2:
        raise ValueError("Invalid signed change mask")
    if previous is None:
        return False
    if type(previous) is not bytes or max(previous, default=0) > 2:
        raise ValueError("Invalid signed change mask")
    if len(previous) != len(current):
        raise ValueError("Change masks have incompatible dimensions")
    overlap = sum(old != 0 and old == new for old, new in zip(previous, current, strict=True))
    smaller = min(len(previous) - previous.count(0), len(current) - current.count(0))
    return smaller > 0 and 2 * overlap >= smaller
