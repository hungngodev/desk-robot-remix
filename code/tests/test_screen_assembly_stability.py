"""Measured assembled center of mass is necessary for safe gripping and docking."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/screen_assembly_stability.py"


def load():
    spec = importlib.util.spec_from_file_location("screen_stability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete():
    module = load()
    data = module.blank_template()
    data["required_static_edge_margin_mm"] = 10
    data["max_roll_deg"] = 8
    data["max_pitch_deg"] = 8
    defaults = {
        "body_and_tracks": (350, [0, 0, 15]),
        "power_stack": (150, [-10, 0, 25]),
        "head_and_sense": (100, [0, 0, 65]),
        "lift_and_gripper": (90, [16, 0, 20]),
        "sensors_and_wiring": (60, [0, 0, 28]),
        "payload": (0, [0, 0, 15]),
    }
    for pose in data["poses"]:
        pose["support_contacts_mm"] = [
            [-40, -45], [40, -45], [40, 45], [-40, 45],
        ]
        for component in pose["components"]:
            mass, xyz = defaults[component["id"]]
            if component["id"] == "payload":
                if pose["name"] == "key_grasp_extended":
                    mass, xyz = 10, [35, 0, 20]
                if pose["name"] == "candy_grasp_lifted":
                    mass, xyz = 20, [30, 0, 70]
            component["mass_g"] = mass
            component["com_mm"] = xyz
    return data


def test_four_real_required_pose_roles_are_screened_but_unqualified():
    tool = load()
    result = tool.screen(complete())
    assert result["necessary_stability_on_paper"]
    assert len(result["poses"]) == 4
    assert all(len(p["support_hull_mm"]) == 4 for p in result["poses"])
    assert all(p["worst_tilt_static_margin_mm"] >= 10
               for p in result["poses"])
    assert result["actual_mass_and_support_locations_physically_verified"] is False
    assert result["loaded_dynamic_turn_and_braking_stability_verified"] is False
    assert result["cliff_stop_and_motor_authorized"] is False
    assert result["assembly_print_or_purchase_approved"] is False


def test_external_heavy_protected_battery_requires_real_stability_redesign():
    data = complete()
    for pose in data["poses"]:
        battery = next(p for p in pose["components"]
                       if p["id"] == "power_stack")
        battery.update(mass_g=1400, com_mm=[80, 0, 45])
    result = load().screen(data)
    assert not result["necessary_stability_on_paper"]
    assert all(not x["necessary_static_margin_on_paper"]
               for x in result["poses"])
    assert not result["assembly_print_or_purchase_approved"]


def test_large_raised_gripper_payload_can_fail_while_empty_pose_passes():
    data = complete()
    lifted = next(p for p in data["poses"]
                  if p["name"] == "candy_grasp_lifted")
    mass = next(p for p in lifted["components"] if p["id"] == "payload")
    mass.update(mass_g=900, com_mm=[120, 0, 90])
    report = load().screen(data)
    results = {row["name"]: row for row in report["poses"]}
    assert results["stowed_empty"]["necessary_static_margin_on_paper"]
    assert not results["candy_grasp_lifted"]["necessary_static_margin_on_paper"]


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(max_roll_deg=26),
    lambda d: d.update(max_pitch_deg=float("nan")),
    lambda d: d.update(required_static_edge_margin_mm=True),
    lambda d: d["poses"][0].update(support_contacts_mm=[[0, 0], [1, 1], [2, 2]]),
    lambda d: d["poses"][0].update(support_contacts_mm=[[0, 0], [0, 0], [3, 4]]),
    lambda d: d["poses"][0].update(support_contacts_mm=[[0, 0], [1e308, 0], [0, 1e308]]),
    lambda d: d["poses"][0].pop("support_contacts_mm"),
    lambda d: d["poses"].pop(),
    lambda d: d["poses"][0]["components"].pop(),
    lambda d: d["poses"][0]["components"][0].update(mass_g=True),
    lambda d: d["poses"][0]["components"][0].update(mass_g=10**1000),
    lambda d: d["poses"][0]["components"][0].update(com_mm=[0, 0, float("inf")]),
    lambda d: d.update(units="inch_lbs"),
    lambda d: d.update(coordinate_frame="world_z_down"),
])
def test_invalid_support_mass_or_missing_behaviors_never_pass(mutation):
    record = complete()
    mutation(record)
    with pytest.raises(ValueError):
        load().screen(record)



def test_pose_specific_supports_never_borrow_docked_footprint():
    """Equal mass and COM still need their own wheel/dock contact polygon."""
    data = complete()
    stowed = next(p for p in data["poses"] if p["name"] == "stowed_empty")
    assert any(p["name"] == "docked_stopped" for p in data["poses"])
    stowed["support_contacts_mm"] = [
        [-8, -45], [8, -45], [8, 45], [-8, 45],
    ]
    # Docked keeps the measured wide contact polygon. With identical
    # payload-free mass/COM, stowed must lose the required 10 mm reserve.
    report = load().screen(data)
    cases = {pose["name"]: pose for pose in report["poses"]}
    assert cases["stowed_empty"]["source_center_of_mass_mm"] == (
        cases["docked_stopped"]["source_center_of_mass_mm"]
    )
    assert cases["stowed_empty"]["worst_tilt_static_margin_mm"] < (
        cases["docked_stopped"]["worst_tilt_static_margin_mm"]
    )
    assert not cases["stowed_empty"]["necessary_static_margin_on_paper"]
    assert cases["docked_stopped"]["necessary_static_margin_on_paper"]
    assert not report["necessary_stability_on_paper"]
    assert report["assembly_print_or_purchase_approved"] is False



def test_simultaneous_pitch_and_roll_uses_coupled_conservative_tilt_bound():
    """Tall centered COM must fail the real two-axis 25 degree static reserve."""
    data = complete()
    data["max_roll_deg"] = 25
    data["max_pitch_deg"] = 25
    data["required_static_edge_margin_mm"] = 10
    for pose in data["poses"]:
        pose["support_contacts_mm"] = [
            [-50, -50], [50, -50], [50, 50], [-50, 50],
        ]
        for part in pose["components"]:
            part["com_mm"] = [0, 0, 80]
    coupled = load().screen(data)
    assert not coupled["necessary_stability_on_paper"]
    assert all(pose["worst_tilt_static_margin_mm"] < 10
               for pose in coupled["poses"])
    # With roll zero, there is no 1/cos coupling; the prior one-axis
    # result (50 - 80*tan(25 deg) > 10 mm) must still pass.
    data["max_roll_deg"] = 0
    single_axis = load().screen(data)
    assert single_axis["necessary_stability_on_paper"]
    assert all(pose["worst_tilt_static_margin_mm"] > 10
               for pose in single_axis["poses"])
    # Measured horizontal COM offset must worsen the closest edge reserve.
    for pose in data["poses"]:
        for part in pose["components"]:
            part["com_mm"] = [5, 0, 80]
    offset = load().screen(data)
    assert all(
        later["worst_tilt_static_margin_mm"]
        < earlier["worst_tilt_static_margin_mm"]
        for earlier, later in zip(single_axis["poses"], offset["poses"], strict=True)
    )
    assert offset["assembly_print_or_purchase_approved"] is False


def test_blank_source_template_is_not_a_qualified_measurement():
    tool = load()
    template = tool.blank_template()
    assert "support_contacts_mm" not in template
    assert len(template["poses"]) == 4
    assert all(pose["support_contacts_mm"] == [] for pose in template["poses"])
    assert all(part["mass_g"] is None
               for case in template["poses"]
               for part in case["components"])
    with pytest.raises(ValueError):
        tool.screen(template)


def test_hull_margin_is_signed_and_does_not_qualify_outside_contact():
    tool = load()
    hull = tool.support_hull([
        [-10, -10], [-10, 10], [10, 10], [10, -10],
    ])
    assert tool.minimum_signed_edge_margin((0, 0), hull) == pytest.approx(10)
    assert tool.minimum_signed_edge_margin((12, 0), hull) < 0


def test_cross_pose_fixed_component_mass_mismatch_fails_closed():
    tool = load()
    data = complete()
    # Misweight power_stack in key_grasp_extended (1g vs 150g in other poses)
    key_pose = next(p for p in data["poses"] if p["name"] == "key_grasp_extended")
    battery = next(c for c in key_pose["components"] if c["id"] == "power_stack")
    battery["mass_g"] = 1

    with pytest.raises(ValueError, match="Fixed assembly role 'power_stack' mass changed between poses"):
        tool.screen(data)


def test_cross_pose_assembly_role_substitution_fails_closed():
    tool = load()
    data = complete()
    key_pose = next(p for p in data["poses"] if p["name"] == "key_grasp_extended")
    # Add an extra component role to key_grasp_extended not present in baseline
    key_pose["components"].append({"id": "extra_ballast", "mass_g": 50, "com_mm": [0, 0, 10]})

    with pytest.raises(ValueError, match="Assembly roles in pose 'key_grasp_extended' do not match baseline roles"):
        tool.screen(data)

@pytest.mark.parametrize("role, shifted_center", [
    ("body_and_tracks", [35, 0, 15]),
    ("power_stack", [35, 0, 25]),
    ("sensors_and_wiring", [35, 0, 28]),
    ("extra_ballast", [35, 0, 10]),
])
def test_fixed_component_center_cannot_teleport_between_poses(
    role, shifted_center,
):
    tool = load()
    data = complete()
    if role == "extra_ballast":
        for pose in data["poses"]:
            pose["components"].append({
                "id": role, "mass_g": 40, "com_mm": [0, 0, 10],
            })
    pose = next(p for p in data["poses"] if p["name"] == "key_grasp_extended")
    component = next(c for c in pose["components"] if c["id"] == role)
    component["com_mm"] = shifted_center
    with pytest.raises(
        ValueError, match=f"Fixed assembly role '{role}' center changed",
    ):
        tool.screen(data)


def test_articulated_head_gripper_and_payload_keep_pose_specific_centers():
    data = complete()
    lifted = next(p for p in data["poses"] if p["name"] == "candy_grasp_lifted")
    centers = {
        "head_and_sense": [3, 0, 68],
        "lift_and_gripper": [26, 0, 30],
        "payload": [30, 0, 70],
    }
    for part in lifted["components"]:
        if part["id"] in centers:
            part["com_mm"] = centers[part["id"]]
    report = load().screen(data)
    assert report["necessary_stability_on_paper"]
    assert report["assembly_print_or_purchase_approved"] is False
