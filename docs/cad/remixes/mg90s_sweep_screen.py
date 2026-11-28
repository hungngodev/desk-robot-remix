"""Conservative MG90S sweep screen in measured assembly coordinates (mm).

Use separately for lift and jaw in each servo's rotation plane (XY).
Transform all obstacle bounds into that same frame. Reach bounds the radial
centerline; margin must cover all transverse offsets, hardware and measurement
uncertainty. Include the full axial span and ToF optical keepouts. This is only
an analytical rejection screen, never a physical qualification or servo limit.
"""
import argparse
import json
from math import ceil, cos, floor, isfinite, radians, sin
from pathlib import Path

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


def screen_assembly_record(record):
    """Screen both operator-supplied servo frames, never certify their provenance."""
    revision = record["assembly_revision"]
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("An aligned assembly revision is required")
    results = {}
    for servo in ("lift", "jaw"):
        frame = record[servo]
        bounds = sweep_bounds(
            frame["pivot_mm"], frame["reach_mm"], frame["start_deg"],
            frame["end_deg"], frame["z_span_mm"], frame["margin_mm"],
        )
        overlaps = overlapping_keepouts(bounds, frame["keepouts_mm"])
        results[servo] = {"bounds_mm": bounds, "potential_overlaps": overlaps}
    return {
        "assembly_revision": revision,
        "input_provenance": "operator_supplied_unverified",
        "screen_scope": "standalone_aabb_rejection_only",
        "physical_qualification": "HOLD",
        "servos": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="Measured aligned assembly JSON")
    args = parser.parse_args()
    try:
        result = screen_assembly_record(json.loads(args.record.read_text(encoding="utf-8")))
    except (OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
        parser.error(f"MG90S assembly screen HOLD: {exc}")
    print(json.dumps(result, indent=2))
    return int(any(servo["potential_overlaps"] for servo in result["servos"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
