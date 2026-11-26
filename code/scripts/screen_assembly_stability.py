"""Static mass and support-footprint screen for the COMPLETE first desk pet.

All source inputs are independently measured by a builder, never inferred
from a concept render. A pass is a necessary static paper screen only. This
does not verify center of gravity, moving tracks, dynamic braking, table
edges, gripper torque, docking, charger isolation or physical tip safety.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROLES = frozenset({
    "body_and_tracks", "power_stack", "head_and_sense",
    "lift_and_gripper", "sensors_and_wiring", "payload",
})
# The first-unit Sense head is fixed to the chassis. Only its articulated
# gripper and carried payload may change relative center between poses.
# Head pan/tilt is an unqualified expansion, not motion on this build.
# Extra unnamed components are stationary unless a new measured mechanism
# is explicitly qualified; do not shift them to inflate the paper margin.
ARTICULATED_COM_ROLES = frozenset({"lift_and_gripper", "payload"})
REQUIRED_POSES = frozenset({
    "stowed_empty", "key_grasp_extended",
    "candy_grasp_lifted", "docked_stopped",
})
COORDINATE_FRAME = "body_x_forward_y_left_z_up"
UNIT_SYSTEM = "mm_g"


def _finite(value: object, limit: float) -> bool:
    # Reject bool and huge int before calling math.isfinite.
    return type(value) in (float, int) and -limit <= value <= limit and (
        math.isfinite(value)
    )


def _point(value: object, *, dimension: int) -> tuple[float, ...]:
    if (not isinstance(value, (list, tuple))
            or len(value) != dimension
            or not all(_finite(v, 1000) for v in value)):
        raise ValueError("Measured support and center points need finite millimeters")
    return tuple(float(v) for v in value)


def _cross(o: tuple, a: tuple, b: tuple) -> float:
    return ((a[0]-o[0]) * (b[1]-o[1])
            - (a[1]-o[1]) * (b[0]-o[0]))


def support_hull(contacts: object) -> list[tuple[float, float]]:
    if not isinstance(contacts, list) or not 3 <= len(contacts) <= 32:
        raise ValueError("Every real load-bearing track or caster contact is needed")
    points = [_point(p, dimension=2) for p in contacts]
    if len(set(points)) != len(points):
        raise ValueError("Duplicate support contact must not imply a wider base")
    ordered = sorted(points)
    lower = []
    for p in ordered:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(ordered):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        raise ValueError("Collinear supports cannot create a stability footprint")
    return hull


def minimum_signed_edge_margin(point: tuple, hull: list[tuple]) -> float:
    distances = []
    for a, b in zip(hull, hull[1:] + hull[:1], strict=True):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= 0:
            raise ValueError("Invalid support polygon edge")
        distances.append(_cross(a, b, point) / length)
    return min(distances)


def blank_template() -> dict:
    """Never invent mass, track contacts or a lifted payload position."""
    return {
        "units": UNIT_SYSTEM,
        "coordinate_frame": COORDINATE_FRAME,
        "required_static_edge_margin_mm": None,
        "max_roll_deg": None,
        "max_pitch_deg": None,
        "poses": [{
            "name": pose,
            "support_contacts_mm": [],
            "components": [{
                "id": role, "mass_g": None,
                "com_mm": [None, None, None],
            } for role in sorted(ROLES)],
        } for pose in sorted(REQUIRED_POSES)],
    }


def _require_positive_height(mass: float, center: tuple[float, ...]) -> None:
    if mass > 0 and center[2] <= 0:
        raise ValueError("Positive-mass component center must be above the support plane")


def screen(measurement: object) -> dict:
    if not isinstance(measurement, dict) or set(measurement) != {
        "units", "coordinate_frame",
        "required_static_edge_margin_mm", "max_roll_deg",
        "max_pitch_deg", "poses",
    }:
        raise ValueError("Full mass and footprint measurement record is required")
    if (measurement["units"] != UNIT_SYSTEM
            or measurement["coordinate_frame"] != COORDINATE_FRAME):
        raise ValueError("Wrong chassis coordinate frame or mass/distance units")
    margin = measurement["required_static_edge_margin_mm"]
    roll = measurement["max_roll_deg"]
    pitch = measurement["max_pitch_deg"]
    if (not _finite(margin, 1000) or not 2 <= margin <= 100
            or not _finite(roll, 25) or not 0 <= roll <= 25
            or not _finite(pitch, 25) or not 0 <= pitch <= 25):
        raise ValueError("Measured roll, pitch and static margin required")
    cases = measurement["poses"]
    if not isinstance(cases, list) or not 4 <= len(cases) <= 40:
        raise ValueError("All stowed, key, candy and docked poses required")
    names = [case.get("name") for case in cases if isinstance(case, dict)]
    if (len(names) != len(cases)
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)
            or not REQUIRED_POSES.issubset(names)):
        raise ValueError("Missing, unnamed or duplicated load pose")
    results = []
    baseline_components: dict[str, float] | None = None
    baseline_fixed_centers: dict[str, tuple[float, float, float]] = {}
    baseline_roles: set[str] = set()
    baseline_pose_name: str = ""
    for case in cases:
        if set(case) != {"name", "components", "support_contacts_mm"}:
            raise ValueError("Each load pose needs measured components and support contacts")
        # Dock guides, tracks and casters can carry load in different poses.
        # A shared union polygon can falsely certify a pose that lacks a
        # contact. Independently validate the real load-bearing set.
        hull = support_hull(case["support_contacts_mm"])
        components = case["components"]
        if not isinstance(components, list) or not 6 <= len(components) <= 60:
            raise ValueError("Full assembly mass roles are required")
        masses = {}
        for part in components:
            if not isinstance(part, dict) or set(part) != {
                "id", "mass_g", "com_mm",
            }:
                raise ValueError("Every role needs a measured mass and center")
            role = part["id"]
            if not isinstance(role, str) or not role or role in masses:
                raise ValueError("Duplicate or unnamed component mass")
            mass = part["mass_g"]
            if not _finite(mass, 100_000) or mass < 0:
                raise ValueError("Component mass must be a measured finite gram value")
            if role != "payload" and mass <= 0:
                raise ValueError("Mandatory robot component cannot disappear")
            center = _point(part["com_mm"], dimension=3)
            _require_positive_height(mass, center)
            masses[role] = (float(mass), center)
        if not ROLES.issubset(masses):
            raise ValueError("Missing body, power, head, gripper, sensors or payload")

        # Fixed assembly roles and their measured masses must remain consistent
        # across all poses for the same physical robot. Only the articulated
        # center-of-mass coordinates may move, and only payload mass may vary.
        if baseline_components is None:
            baseline_components = {
                r: m for r, (m, _) in masses.items() if r != "payload"
            }
            baseline_fixed_centers = {
                r: center for r, (_, center) in masses.items()
                if r not in ARTICULATED_COM_ROLES
            }
            baseline_roles = set(masses.keys())
            baseline_pose_name = case["name"]
        else:
            if set(masses.keys()) != baseline_roles:
                raise ValueError(
                    f"Assembly roles in pose '{case['name']}' do not match baseline roles "
                    f"from '{baseline_pose_name}'"
                )
            for role, base_mass in baseline_components.items():
                if not math.isclose(masses[role][0], base_mass, rel_tol=1e-7, abs_tol=0.0):
                    raise ValueError(
                        f"Fixed assembly role '{role}' mass changed between poses "
                        f"({base_mass}g in '{baseline_pose_name}' vs {masses[role][0]}g in '{case['name']}'); "
                        "stability screen requires consistent assembly mass evidence"
                    )
            for role, first_center in baseline_fixed_centers.items():
                center = masses[role][1]
                if any(not math.isclose(a, b, rel_tol=0, abs_tol=0.001)
                       for a, b in zip(center, first_center, strict=True)):
                    raise ValueError(
                        f"Fixed assembly role '{role}' center changed between poses "
                        f"('{baseline_pose_name}' to '{case['name']}'); "
                        "stationary components cannot shift to improve paper stability"
                    )

        payload_mass = masses["payload"][0]
        if case["name"] == "stowed_empty" and payload_mass != 0:
            raise ValueError("Empty stowed pose must have zero payload")
        if case["name"] in {"key_grasp_extended", "candy_grasp_lifted"} and (
            payload_mass <= 0
        ):
            raise ValueError("Loaded grasp poses need actual key and candy mass")
        total = sum(m for m, _ in masses.values())
        # Scale before multiplying to avoid underflow in tiny positive masses
        # falsely moving the center toward the origin.
        scale = max(m for m, _ in masses.values())
        weights = [(m / scale, xyz) for m, xyz in masses.values()]
        weight_total = math.fsum(w for w, _ in weights)
        com = tuple(
            math.fsum(w * xyz[axis] for w, xyz in weights) / weight_total
            for axis in range(3)
        )
        # For Ry(pitch) Rx(roll), gravity-line projection contributes
        # dx = z*tan(pitch)/cos(roll), dy = z*tan(roll).
        # Reversing the rotation order transfers the 1/cos coupling to dy.
        # A rectangle bounding BOTH conventions, all angle signs and every
        # angle within the configured maxima is deliberately conservative.
        # An affine signed edge distance reaches its minimum over that box
        # at a corner. Independent tan terms alone underbound simultaneous
        # tilt and can falsely certify tall loads.
        x_reach = (
            abs(com[2]) * math.tan(math.radians(pitch))
            / math.cos(math.radians(roll))
        )
        y_reach = (
            abs(com[2]) * math.tan(math.radians(roll))
            / math.cos(math.radians(pitch))
        )
        worst_margin = min(
            minimum_signed_edge_margin(
                (com[0] + x_sign * x_reach, com[1] + y_sign * y_reach),
                hull,
            )
            for x_sign in (-1, 1) for y_sign in (-1, 1)
        )
        results.append({
            "name": case["name"],
            "support_hull_mm": [list(p) for p in hull],
            "mass_total_g": round(total, 3),
            "source_center_of_mass_mm": [round(x, 3) for x in com],
            "worst_tilt_static_margin_mm": round(worst_margin, 3),
            "necessary_static_margin_on_paper": worst_margin >= margin,
        })
    return {
        "required_pose_names": sorted(REQUIRED_POSES),
        "required_static_edge_margin_mm": margin,
        "poses": results,
        "necessary_stability_on_paper": all(
            p["necessary_static_margin_on_paper"] for p in results
        ),
        "actual_mass_and_support_locations_physically_verified": False,
        "loaded_dynamic_turn_and_braking_stability_verified": False,
        "cliff_stop_and_motor_authorized": False,
        "assembly_print_or_purchase_approved": False,
    }


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("Duplicate assembly stability measurement key")
        out[key] = value
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--measurements", type=Path)
    group.add_argument("--template", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.template:
        artifact = json.dumps(blank_template(), indent=2) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as file:
                file.write(artifact)
        else:
            print(artifact, end="")
        return
    if args.output is not None:
        parser.error("--output is allowed only with --template")
    record = json.loads(
        args.measurements.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError("Nonfinite mass or geometry token: " + token)
        ),
    )
    print(json.dumps(screen(record), indent=2))


if __name__ == "__main__":
    main()
