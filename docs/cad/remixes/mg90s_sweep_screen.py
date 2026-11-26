"""Conservative MG90S sweep screen in measured assembly coordinates (mm).

Use separately for lift and jaw in each servo's rotation plane (XY).
Transform all obstacle bounds into that same frame. Reach bounds the radial
centerline; margin must cover all transverse offsets, hardware and measurement
uncertainty. Include the full axial span and ToF optical keepouts. This is only
an analytical rejection screen, never a physical qualification or servo limit.
"""
from math import ceil, cos, floor, isfinite, radians, sin

REQUIRED_KEEPOUTS = frozenset({f"tof_{lane}" for lane in range(8)} | {"battery_cover"})


def sweep_bounds(pivot, reach, start_deg, end_deg, z_span, margin):
    """Enclose the continuous radial segment sweep, including both endpoints."""
    x, y = pivot
    low_z, high_z = z_span
    values = (x, y, reach, start_deg, end_deg, low_z, high_z, margin)
    if not all(isfinite(v) for v in values):
        raise ValueError("Sweep dimensions must be finite")
    if not (reach > 0 and margin > 0 and low_z < high_z
            and -360 <= start_deg <= end_deg <= 360 and end_deg - start_deg <= 360):
        raise ValueError("Invalid measured sweep or clearance margin")
    angles = [start_deg, end_deg]
    angles.extend(90 * i for i in range(ceil(start_deg / 90), floor(end_deg / 90) + 1))
    xs = [x, *(x + reach * cos(radians(a)) for a in angles)]
    ys = [y, *(y + reach * sin(radians(a)) for a in angles)]
    return ((min(xs) - margin, min(ys) - margin, low_z - margin),
            (max(xs) + margin, max(ys) + margin, high_z + margin))


def overlapping_keepouts(sweep, keepouts):
    """Return every potential interference; touching also fails the screen."""
    if not REQUIRED_KEEPOUTS <= keepouts.keys():
        raise ValueError("All eight ToF keepouts and the battery cover are required")
    for lower, upper in [sweep, *keepouts.values()]:
        if (len(lower) != 3 or len(upper) != 3
                or not all(isfinite(v) for v in (*lower, *upper))
                or not all(a < b for a, b in zip(lower, upper, strict=True))):
            raise ValueError("Invalid assembly bounding box")
    low, high = sweep
    return tuple(sorted(name for name, (a, b) in keepouts.items()
                        if all(lo <= hi2 and lo2 <= hi for lo, hi, lo2, hi2
                               in zip(low, high, a, b, strict=True))))
