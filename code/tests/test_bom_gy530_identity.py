"""Keep the historical GY-530 alternative separate from the exact pilot carrier."""

import configparser
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _validate_gy530_identity(plan: dict, bom: dict) -> None:
    selected = next(part for part in plan["parts"] if part["id"] == "cliff_obstacle")
    assert "VL53L0X" in selected["name"] and "GY-530" in selected["name"]
    assert "SEN-19-006" in selected["name"]
    assert not any(chip in selected["name"].upper() for chip in ("VL53L4CD", "TCRT5000"))
    rows = [
        item for item in bom["items"]
        if item.get("candidate_seller_sku") == "SEN-19-006"
        or "VL53L" in item["item"]
        or "GY-530" in item["item"]
        or "TCRT5000" in item["item"].upper()
    ]
    assert len(rows) == 3
    role_quantities = {}
    for role in ("downward", "forward", "side and rear"):
        matched = [row for row in rows if role in row["item"]]
        assert len(matched) == 1, role
        role_quantities[role] = matched[0]["quantity"]
    assert role_quantities == {
        "downward": 4,
        "forward": 1,
        "side and rear": 3,
    }
    assert sum(role_quantities.values()) == selected["per_robot"] == 8
    for row in rows:
        assert "VL53L0X GY-530" in row["item"]
        assert not any(chip in row["item"].upper() for chip in ("VL53L4CD", "TCRT5000"))
        assert row["candidate_seller_sku"] == "SEN-19-006"
        assert row["url"] == (
            "https://electropeak.com/gy-530-vl53l0x-laser-range-finder"
        )
        assert row["unit_usd"] is None
        assert row["price_status"] == "sample_quote_only"
        assert row["reference_unit_usd"] == 1.44
        assert "SEN-19-018" in row["fit"]
    alt = bom["unselected_gy530_carrier_reference"]
    assert alt["seller_sku"] == "SEN-19-018"
    assert alt["reference_unit_usd"] == 1.75
    assert alt["url"].endswith("laser-ranging-sensor-module-double-hole")
    assert alt["intended_status"] == "historical_alternative_not_selected_for_first_unit"
    assert bom["qualification_checks"]["sensor_mount_surface_latency_and_stops_qualified"] is False


def test_historical_budget_carrier_matches_first_unit_sample_identity():
    plan = json.loads(
        (ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8")
    )
    bom = json.loads(
        (ROOT / "docs/hardware/bom.json").read_text(encoding="utf-8")
    )
    _validate_gy530_identity(plan, bom)


def test_gy530_identity_rejects_vl53l4cd_label_and_swapped_role_counts():
    plan = json.loads(
        (ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8")
    )
    bom = json.loads(
        (ROOT / "docs/hardware/bom.json").read_text(encoding="utf-8")
    )

    contradictory = json.loads(json.dumps(bom))
    down_row = next(
        item for item in contradictory["items"]
        if item.get("candidate_seller_sku") == "SEN-19-006" and "downward" in item["item"]
    )
    down_row["item"] = down_row["item"].replace("VL53L0X GY-530", "VL53L4CD")
    with pytest.raises(AssertionError):
        _validate_gy530_identity(plan, contradictory)

    swapped = json.loads(json.dumps(bom))
    for item in swapped["items"]:
        if item.get("candidate_seller_sku") == "SEN-19-006":
            if "downward" in item["item"]:
                item["quantity"] = 1
            elif "forward" in item["item"]:
                item["quantity"] = 4
    with pytest.raises(AssertionError):
        _validate_gy530_identity(plan, swapped)


RANGE_POSITIONS = (
    "floor_front_left", "floor_front_right", "floor_rear_left", "floor_rear_right",
    "front_obstacle", "left_obstacle", "right_obstacle", "rear_obstacle",
)
SOURCE_MARKERS = {
    "docs/cad/remixes/one_robot_adapter_kit.scad": (
        "Selected pilot GY-530 (ElectroPeak SEN-19-006)", "tof_pcb_w=10.5;", "tof_pcb_h=13.3;",
    ),
    "docs/cad/FUSION_MEASUREMENT_SHEET.md": (
        "GY-530 VL53L0X carrier SEN-19-006", "10.5 by 13.3 mm",
    ),
    "code/firmware/body/lib/TofBus/TofBus.h": (
        "#include <VL53L0X.h>", "VL53L0X devices_[kRangeCount]{};",
        "kMuxAddress = 0x70;", "kOptionalMuxAddress = 0x71;", "kSensorAddress = 0x29;",
        "kFloorAndFrontCount = 5;", "kRangeCount = 5 + (DESK_ROBOT_EXTRA_RANGERS ? 3 : 0);",
    ),
    "code/firmware/body/lib/CliffGuard/CliffGuard.h": (
        "kFloorSensorCount = 4;", "kCliffSensorCount = 5;",
    ),
    "docs/hardware/wiring.md": (
        "TCA9548A RANGE mux 0x70", "TCA9548A ACCESSORY mux 0x71",
        "CH0 front-left floor VL53L0X 0x29", "CH1 front-right floor VL53L0X 0x29",
        "CH2 rear-left floor VL53L0X 0x29", "CH3 rear-right floor VL53L0X 0x29",
        "CH4 front obstacle VL53L0X 0x29", "CH5 left-side VL53L0X 0x29, read-only",
        "CH6 right-side VL53L0X 0x29, read-only", "CH7 rear obstacle VL53L0X 0x29, read-only",
    ),
}


def _validate_range_plan(plan: dict) -> None:
    contract = plan["range_breakout_power_contract"]
    assert contract["selected_chip"] == "VL53L0X"
    assert contract["generic_module_family"] == "GY-530"
    assert contract["modules_per_robot"] == 8
    assert contract["mux_address_7bit"] == 0x70
    bus = plan["bus"]
    assert bus["mux_ranges"]["address"] == 0x70
    assert bus["mux_extras"]["address"] == 0x71
    lanes = bus["mux_ranges"]["channels"]
    assert len(lanes) == 8
    assert {lane["channel"] for lane in lanes} == set(range(8))
    for lane in lanes:
        channel = lane["channel"]
        assert lane["position"] == RANGE_POSITIONS[channel]
        assert lane["devices"] == [{"name": "VL53L0X", "address": 0x29}]
        assert ("read_only" in lane["firmware"]) == (channel >= 5)


def _validate_source_markers(path: str, source: str) -> None:
    # Historical rejection prose is allowed; only the selected declarations matter.
    for marker in SOURCE_MARKERS[path]:
        assert marker in source, f"{path}: missing selected identity: {marker}"
    if path.endswith("TofBus.h"):
        assert not any(chip in source.upper() for chip in ("VL53L4CD", "TCRT5000"))


def test_range_plan_matches_eight_gy530_lanes():
    plan = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8"))
    _validate_range_plan(plan)


@pytest.mark.parametrize("path", SOURCE_MARKERS)
def test_selected_ranging_identity_across_source(path):
    _validate_source_markers(path, (ROOT / path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("chip", ["VL53L4CD", "TCRT5000"])
def test_rejects_alternate_chip_in_plan_and_bom(chip):
    plan = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8"))
    bom = json.loads((ROOT / "docs/hardware/bom.json").read_text(encoding="utf-8"))
    selected = next(part for part in plan["parts"] if part["id"] == "cliff_obstacle")
    original = selected["name"]
    selected["name"] += f" or {chip}"
    with pytest.raises(AssertionError):
        _validate_gy530_identity(plan, bom)
    selected["name"] = original
    bom["items"].append({"item": f"{chip} substitute cliff sensor", "quantity": 1})
    with pytest.raises(AssertionError):
        _validate_gy530_identity(plan, bom)
    plan["bus"]["mux_ranges"]["channels"][7]["devices"][0]["name"] = chip
    with pytest.raises(AssertionError):
        _validate_range_plan(plan)


@pytest.mark.parametrize("path", SOURCE_MARKERS)
def test_source_contract_rejects_missing_selected_declaration(path):
    source = (ROOT / path).read_text(encoding="utf-8")
    for marker in SOURCE_MARKERS[path]:
        assert marker in source
        with pytest.raises(AssertionError, match="missing selected identity"):
            _validate_source_markers(path, source.replace(marker, "REMOVED"))


def _validate_full_profiles(source: str) -> None:
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(source)
    for profile in ("esp32_full", "esp32_dc_full"):
        section = config[f"env:{profile}"]
        assert "-DDESK_ROBOT_EXTRA_RANGERS=1" in section["build_flags"].split()
        deps = section["lib_deps"].lower()
        assert "github.com/pololu/vl53l0x-arduino.git#" in deps
        assert "vl53l4cd" not in deps and "tcrt5000" not in deps


def test_full_firmware_profiles_keep_eight_vl53l0x():
    source = (ROOT / "code/firmware/body/platformio.ini").read_text(encoding="utf-8")
    _validate_full_profiles(source)
    for old, new in (
        ("-DDESK_ROBOT_EXTRA_RANGERS=1", "-DDESK_ROBOT_EXTRA_RANGERS=0"),
        ("vl53l0x-arduino", "vl53l4cd-arduino"),
        ("vl53l0x-arduino", "tcrt5000-arduino"),
    ):
        with pytest.raises(AssertionError):
            _validate_full_profiles(source.replace(old, new, 1))
