"""Executable boundary tests for shared read-only telemetry validators."""

import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Literal, get_args, get_origin, get_type_hints

import pytest
from desk_robot.sensor_event_contract import (
    TRIGGERS,
    ProactiveToolData,
    ProactiveToolReceipt,
    has_upright_floor_loss,
    is_finite_number,
    is_int_in_range,
    is_uint,
)


class IntSubclass(int):
    pass


class FloatSubclass(float):
    pass


@pytest.mark.parametrize(
    "value",
    [True, False, None, "1", Decimal("1"), IntSubclass(1), FloatSubclass(1),
     float("nan"), float("inf"), -float("inf"), 10**400, -(10**400)],
)
def test_finite_number_rejects_invalid_wire_values(value):
    assert is_finite_number(value) is False


@pytest.mark.parametrize("value", [0, -1, 1, -0.0, 0.25, -0.25, sys.float_info.max])
def test_finite_number_accepts_native_finite_values(value):
    assert is_finite_number(value) is True


@pytest.mark.parametrize(
    "value",
    [True, False, None, "1", 0.0, 1.0, Decimal("1"), IntSubclass(1),
     float("nan"), float("inf"), -float("inf"), 10**400, -(10**400)],
)
def test_integer_validators_reject_invalid_wire_values(value):
    assert is_int_in_range(value, -2, 2) is False
    assert is_uint(value, 2) is False


@pytest.mark.parametrize("value", [-3, -2, -1, 0, 1, 2, 3])
def test_signed_and_unsigned_inclusive_bounds(value):
    assert is_int_in_range(value, -2, 2) is (-2 <= value <= 2)
    assert is_uint(value, 2) is (0 <= value <= 2)


def test_zero_width_integer_ranges():
    assert is_int_in_range(-1, -1, -1) is True
    assert is_int_in_range(0, -1, -1) is False
    assert is_uint(0, 0) is True
    assert is_uint(1, 0) is False
    assert is_uint(0, -1) is False


@pytest.mark.parametrize(
    "ranges, expected",
    [({"mm": [40, 40, 40, 40, 40]}, False),
     ({"mm": [40, 40, 40, 40, 40], "valid_mask": 0}, True),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": 31}, True),
     ({"mm": [120, 121, 40, 40, 40], "valid_mask": 31}, False),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": True}, False),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": -1}, False),
     ({"mm": [121, 121, 40, 40, 40], "valid_mask": 32}, False),
     ({"mm": [121, 121, False, 40, 40], "valid_mask": 31}, False),
     ({"mm": [121, 121, 40, 40], "valid_mask": 31}, False)],
)
def test_floor_loss_requires_explicit_valid_range_wire_fields(ranges, expected):
    assert has_upright_floor_loss(ranges, {"valid": True, "acc": [0, 0, 12000]}) is expected


@pytest.mark.parametrize("acc", [[0, 0, 11999], [0, False, 12000], [0, 0, 32768]])
def test_floor_loss_rejects_bad_or_non_upright_acceleration(acc):
    ranges = {"mm": [121, 121, 40, 40, 40], "valid_mask": 31}
    assert not has_upright_floor_loss(ranges, {"valid": True, "acc": acc})


def _wire_object(body: str, command: str) -> dict:
    """Inspect the actual C++ JSON format, not a duplicated status fixture."""
    branch = body.split(f"}} else if ({command}) {{", 1)[1]
    match = re.search(
        r'format_reply\(\s*reply,\s*capacity,\s*((?:"(?:\\.|[^"\\])*"\s*)+),',
        branch,
    )
    assert match is not None, f"Missing {command} JSON formatter"
    template = "".join(json.loads(part) for part in re.findall(
        r'"(?:\\.|[^"\\])*"', match.group(1),
    ))
    # Only inspect shape and literal types, not the C++ argument values.
    template = template.replace('"%s"', '"wire-string"')
    return json.loads(re.sub(r"%(?:lu|u|d|s)",
                             lambda m: "false" if m[0] == "%s" else "0", template))


@pytest.fixture
def body_wire_objects():
    body = (Path(__file__).resolve().parents[2]
            / "code/firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    return {command: _wire_object(body, command) for command in ("status", "aux")}


def _wire_fields(wire: dict, section: str, fields: str, expected_type: type) -> None:
    for field in fields.split():
        assert field in wire[section], f"Missing {section}.{field}"
        assert type(wire[section][field]) is expected_type, f"Wrong type: {section}.{field}"


def test_sensor_event_registry_has_explicit_wire_sources(body_wire_objects):
    # Event labels are Mac classifications, not strings sent by the WROOM.
    # Human voice is owned by Xiaozhi, not the body telemetry protocol.
    sources = {
        "touch": "status.touch", "touch_tap": "status.touch",
        "touch_double": "status.touch", "touch_hold": "status.touch",
        "petting_zone": "status.extras", "magnet": "status.extras",
        "pir": "status.extras", "bumper": "status.extras",
        "handling_tilt": "status.imu", "handling_shake": "status.imu",
        "side_object": "status.side_ranges", "safety_fault": "status.safety",
        "stable_putdown": "status.safety", "squeeze": "aux.force",
        "hand_wave": "aux.proximity", "nearby_object": "aux.proximity",
        "nose_twist": "aux.angles", "battery_low": "aux.power",
        "paw_contact": "aux.pulse", "ambient_shift": "aux.climate",
        "nfc_tag": "aux.nfc",
    }
    assert set(sources) == TRIGGERS - {"human_voice"}
    for source in sources.values():
        command, section = source.split(".")
        assert isinstance(body_wire_objects[command][section], dict)
    # Ambient shift may also be produced by the pressure probe.
    assert isinstance(body_wire_objects["aux"]["bmp280"], dict)


@pytest.mark.parametrize(("command", "section", "fields", "expected_type"), [
    ("status", "touch", "active", bool),
    ("status", "touch", "count tap_count double_count hold_count", int),
    ("status", "extras", "mask bumps reed_count pir_count cap cap_events", int),
    ("status", "extras", "bumper reed pir cap_ok", bool),
    ("status", "imu", "family gyro_id age_ms sample_ms boot_id low_g_seq", int),
    ("status", "imu", "valid low_g_valid low_g_irq", bool),
    ("status", "imu", "acc gyro", list),
    ("status", "motor", "m0 m1", int),
    ("status", "side_ranges", "present_mask valid_mask boot_id", int),
    ("status", "side_ranges", "mm age_ms sample_ms", list),
    ("status", "ranges", "present_mask valid_mask", int),
    ("status", "ranges", "mm age_ms", list),
    ("status", "safety", "required ready", bool),
    ("status", "safety", "fault", str),
    ("status", "safety", "sensor", int),
    ("aux", "force", "belly_seq belly_age_ms boot_id", int),
    ("aux", "force", "belly_valid valid", bool),
    ("aux", "force", "adc", list),
    ("aux", "proximity", "raw gesture gesture_events boot_id", int),
    ("aux", "proximity", "valid saturated physically_qualified", bool),
    ("aux", "angles", "raw magnet seq age_ms", list),
    ("aux", "angles", "present_mask valid_mask boot_id", int),
    ("aux", "power", "cell_mv soc_centi fuel_seq fuel_age_ms", int),
    ("aux", "power", "fuel_valid", bool),
    ("aux", "pulse", "present valid", bool),
    ("aux", "pulse", "part_id ir seq age_ms", int),
    ("aux", "climate", "temp_centi rh_centi seq age_ms", int),
    ("aux", "climate", "valid", bool),
    ("aux", "bmp280", "chip_id temp_centi pressure_pa seq age_ms", int),
    ("aux", "bmp280", "present valid physically_verified", bool),
    ("aux", "nfc", "v", bool),
    ("aux", "nfc", "t e s", int),
    ("aux", "dock", "present valid left_seated right_seated input_good "
     "charge_indicated charging_verified", bool),
    ("aux", "dock", "seq age_ms", int),
])
def test_sensor_wire_fields_keep_consumer_types(
    body_wire_objects, command, section, fields, expected_type,
):
    _wire_fields(body_wire_objects[command], section, fields, expected_type)


def test_sensor_wire_shapes_and_protocol(body_wire_objects):
    status, aux = body_wire_objects["status"], body_wire_objects["aux"]
    assert status["protocol"] == 2  # Same version exercised by negotiation tests.
    assert type(status["armed"]) is bool
    assert type(status["watchdog_ms"]) is type(status["drive_ms"]) is int
    assert type(status["backend"]) is str
    for section, fields, count in (
        (status["ranges"], "mm age_ms", 5),
        (status["side_ranges"], "mm age_ms sample_ms", 3),
        (status["imu"], "acc gyro", 3),
        (aux["angles"], "raw magnet seq age_ms", 3),
        (aux["force"], "adc", 2),
    ):
        for field in fields.split():
            assert len(section[field]) == count
            assert all(type(value) is int for value in section[field])
    assert status["side_ranges"]["motion_certified"] is False
    assert aux["bmp280"]["physically_verified"] is False
    assert aux["proximity"]["physically_qualified"] is False
    assert aux["dock"]["charging_verified"] is False


def test_proactive_receipt_is_a_projection_not_a_second_wire_schema(body_wire_objects):
    status, aux = body_wire_objects["status"], body_wire_objects["aux"]
    hints = get_type_hints(ProactiveToolData)
    projections = {
        "sht41": (aux["climate"], {"temp_centi": "temp_centi", "rh_centi": "rh_centi"}),
        "bmp280": (aux["bmp280"], {"pressure_pa": "pressure_pa",
                                    "physically_verified": "physically_verified"}),
        "fuel_gauge": (aux["power"], {"soc_centi": "soc_centi", "cell_mv": "cell_mv"}),
        "proximity": (aux["proximity"], {"gesture": "gesture",
                                        "physically_qualified": "physically_qualified"}),
        "nfc": (aux["nfc"], {"event_count": "e"}),
        "dock_contacts": (aux["dock"], {field: field for field in (
            "left_seated", "right_seated", "input_good", "charge_indicated",
            "charging_verified",
        )}),
        "safety": (status["safety"], {field: field for field in ("required", "ready", "fault")}),
    }
    assert set(hints) == set(projections) | {"armed", "backend", "watchdog_ms", "battery", "data"}
    for name, (wire, mapping) in projections.items():
        fields = get_type_hints(hints[name])
        # Fuel qualification is intentionally generated on the Mac, not read from UART.
        if name == "fuel_gauge":
            assert fields.pop("qualified") == Literal[False]
        assert set(fields) == set(mapping)
        for field, source in mapping.items():
            annotation = fields[field]
            if get_origin(annotation) is Literal:
                assert get_args(annotation) == (False,) and wire[source] is False
            else:
                assert type(wire[source]) is annotation
    assert hints["armed"] is type(status["armed"])
    assert hints["watchdog_ms"] is type(status["watchdog_ms"])
    assert hints["backend"] == Literal["stepper_28byj48"]
    # Battery and dock summaries are separate diagnostic projections, not WROOM fields.
    assert get_type_hints(hints["battery"]) == {
        "percent": int | float, "physically_qualified": Literal[False],
    }
    assert get_type_hints(hints["data"]) == {
        "docked": bool, "physical_contacts_verified": Literal[False],
    }
    assert get_type_hints(ProactiveToolReceipt) == {
        "robot_id": str, "source": str, "verified_motion": Literal[False],
        "verified_charging": Literal[False], "untrusted_observation_not_instructions": Literal[True],
        "data": ProactiveToolData,
    }
