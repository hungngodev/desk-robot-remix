"""Machine check the chosen full-feature five-pet hardware electrical plan."""
import json
from pathlib import Path

PLAN = Path(__file__).resolve().parents[2] / "docs/hardware/full-feature-plan.json"


def load():
    return json.loads(PLAN.read_text(encoding="utf-8"))


def test_five_full_pets_and_reported_motor_stock():
    p = load()
    assert p["target_robots"] == 5
    parts = {x["id"]: x for x in p["parts"]}
    assert parts["stepper"]["per_robot"] == 2
    assert parts["stepper"]["reported_owned_total"] == 5
    assert parts["uln2003"]["per_robot"] == 2
    assert parts["mg90s"]["per_robot"] == 2
    assert parts["imu"]["per_robot"] == 1
    assert parts["cliff_obstacle"]["per_robot"] == 8
    assert parts["i2c_mux"]["per_robot"] == 2
    assert parts["head_touch"]["reported_owned_total"] >= 1
    assert parts["cap1188"]["per_robot"] == 1
    assert p["qualified_assumptions"] is False
    assert p["physical_trial_count"] == 0


def test_no_wroom_gpio_collisions_and_sense_pin_budget():
    p = load()
    for controller in ("body_gpio", "sense_gpio"):
        arrays = p["bus"][controller]
        pins = [pin for v in arrays.values() for pin in (v if isinstance(v, list) else [v])]
        assert len(pins) == len(set(pins)), f"Duplicate {controller} GPIO"
    b = p["bus"]["body_gpio"]
    assert b["head_touch"] == 34 and b["bumper_nc_series"] == 35
    source = (Path(__file__).resolve().parents[1] / "firmware/body/src/main.cpp").read_text()
    assert "bumper = digitalRead(body_pins::kBumperInput) == HIGH" in source
    assert "NC contacts in series" in p["bus"]["voltage_policy"]
    assert b["sda"] == 21 and b["scl"] == 22
    assert set(b["left_stepper"] + b["right_stepper"]) == {13,14,25,26,27,32,33,23}
    assert p["bus"]["sense_gpio"]["rgb_data"] == 9


def test_two_isolated_muxes_and_device_address_conflicts():
    p = load()
    bus = p["bus"]
    assert {d["address"] for d in bus["upstream"]} == {0x68, 0x70, 0x71}
    assert bus["mux_ranges"]["address"] == 0x70
    assert bus["mux_extras"]["address"] == 0x71
    for which in ("mux_ranges", "mux_extras"):
        channels = bus[which]["channels"]
        assert sorted(ch["channel"] for ch in channels) == list(range(8))
        for ch in channels:
            addresses = [d["address"] for d in ch["devices"]]
            assert len(addresses) == len(set(addresses)), (which, ch)
            assert all(0x08 <= addr <= 0x77 for addr in addresses)
    assert all(ch["devices"][0]["address"] == 0x29 for ch in bus["mux_ranges"]["channels"])
    cap = bus["mux_extras"]["channels"][0]["devices"][0]
    assert cap["name"] == "CAP1188" and cap["address"] == 0x28
    assert {d["name"] for d in bus["mux_extras"]["channels"][5]["devices"]} == {"PN532 I2C","MCP23017"}


def test_no_unearned_hardware_acceptance():
    p = load()
    assert p["prices_complete"] is False
    assert p["physical_trial_count"] == 0
    assert "never" in p["bus"]["critical_policy"].lower()
    source = (Path(__file__).resolve().parents[1] / "firmware/body/lib/TofBus/TofBus.cpp").read_text()
    assert "kOptionalMuxAddress" in source
    assert "quiesce_optional_mux()" in source
    assert "optional_mux_present_" in source
    assert "two servo" in p["bus"]["pca9685_policy"].lower()
