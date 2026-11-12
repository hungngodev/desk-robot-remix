"""Cross-layer contracts prevent accidental sensor and harness drift.

These are source assertions, never electrical, acoustic or safety acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from desk_robot.config import Settings, load_settings
from desk_robot.multimodal import TRIGGERS
from desk_robot.pet import (
    _PHYSICAL_INITIATIVE_KINDS, _SOCIAL_EVENT_KINDS,
    _VISUAL_INITIATIVE_MIN_CONFIDENCE,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text())


def test_all_firmware_sensor_reactions_have_a_real_camera_priority_label():
    # Every event produced by physical input and eligible to initiate speech
    # must be representable as a separate authenticated camera context hint.
    assert _PHYSICAL_INITIATIVE_KINDS <= TRIGGERS
    assert _SOCIAL_EVENT_KINDS <= (
        _PHYSICAL_INITIATIVE_KINDS | _VISUAL_INITIATIVE_MIN_CONFIDENCE.keys()
    )
    assert "safety_fault" in TRIGGERS
    assert "safety_fault" not in _SOCIAL_EVENT_KINDS
    assert "battery_low" not in _SOCIAL_EVENT_KINDS


def test_real_robot_pin_allocations_do_not_double_book_same_gpio():
    bus = PLAN["bus"]
    for key in ("body_gpio", "sense_gpio"):
        pins = [
            pin for value in bus[key].values()
            for pin in (value if isinstance(value, list) else [value])
        ]
        assert pins and all(type(pin) is int and 0 <= pin <= 48 for pin in pins)
        assert len(set(pins)) == len(pins), f"Conflicting {key} GPIO allocation"
    assert bus["body_gpio"]["head_touch"] == 34
    assert bus["body_gpio"]["bumper_nc_series"] == 35
    assert bus["body_gpio"]["sda"] == 21
    assert bus["body_gpio"]["scl"] == 22
    assert bus["sense_gpio"]["amp_bclk"] == 4
    # The XIAO Sense SD J3 wire isolation is a physical task, not a pin test.
    assert not PLAN["qualified_assumptions"]


def test_all_eight_tof_lanes_and_every_aux_lane_have_unique_i2c_addresses():
    ranges = PLAN["bus"]["mux_ranges"]
    extras = PLAN["bus"]["mux_extras"]
    assert ranges["address"] == 0x70
    assert extras["address"] == 0x71
    assert {x["channel"] for x in ranges["channels"]} == set(range(8))
    assert {x["channel"] for x in extras["channels"]} == set(range(8))
    assert [x["position"] for x in ranges["channels"][:5]] == [
        "floor_front_left", "floor_front_right", "floor_rear_left",
        "floor_rear_right", "front_obstacle",
    ]
    for group in (ranges, extras):
        for lane in group["channels"]:
            addresses = [device["address"] for device in lane["devices"]]
            assert all(type(a) is int and 0x08 <= a <= 0x77 for a in addresses)
            assert len(addresses) == len(set(addresses)), (
                group["address"], lane["channel"]
            )
    assert {
        (device["name"], device["address"])
        for device in extras["channels"][5]["devices"]
    } == {("PN532 I2C", 0x24), ("MCP23017", 0x20)}
    assert all(lane["devices"][0]["address"] == 0x29
               for lane in ranges["channels"])


def test_plan_source_owners_exist_without_implying_hardware_qualified():
    evidence = PLAN["bus"]["implementation_evidence"]
    for key in (
        "ranges", "raw_expansion", "touch", "pulse", "dock",
        "pet_consumer", "side_consumer", "full_profile", "test_contracts",
    ):
        assert (ROOT / evidence[key]).is_file(), f"Missing {key} owner"
    assert PLAN["target_robots"] == 5
    assert PLAN["physical_trial_count"] == 0
    assert evidence["sensor_hardware_qualified"] is False
    assert evidence["charging_current_electrically_verified"] is False


def test_auto_social_peer_requires_explicit_local_provenance_consent():
    settings = load_settings(ROOT / "code/config/fleet.simulation.toml")
    data = settings.model_dump()
    data["fleet_social_autonomy_enabled"] = True
    data["fleet_text_sharing_enabled"] = False
    with pytest.raises(ValidationError, match="local text sharing consent"):
        Settings.model_validate(data)
    data["fleet_text_sharing_enabled"] = True
    configured = Settings.model_validate(data)
    assert configured.fleet_social_autonomy_enabled
    assert configured.fleet_social_min_interval_seconds >= 30
