"""Selected sensor and new-purchase policy boundaries."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from procurement_policy import (  # noqa: E402
    SELECTED_SENSOR_NAMES,
    adafruit_new_hardware,
    selected_sensor_identity_matches,
)


@pytest.mark.parametrize("role, replacement", [
    ("cliff_obstacle", "VL53L0X or VL53L4CD"),
    ("cliff_obstacle", "VL53L0X or VL6180X"),
    ("cliff_obstacle", "VL53L0X GY-530 alternate PCB"),
    ("imu", "MPU6050 or BerryIMU"),
    ("imu", {"name": "MPU6050"}),
    ("ads1115", "ADS1015 4 channel ADC breakout"),
    ("ads1115", "ADS1115 or ADS1015 4 channel ADC breakout"),
])
def test_changed_selected_plan_identity_is_held(role, replacement):
    assert not selected_sensor_identity_matches(role, replacement, {})
    assert selected_sensor_identity_matches(role, SELECTED_SENSOR_NAMES[role], {})


@pytest.mark.parametrize("role, field, replacement", [
    ("cliff_obstacle", "model", "VL53L0X / VL53L4CD"),
    ("cliff_obstacle", "sku", "VL6180X"),
    ("cliff_obstacle", "product_name", "SEN-19-018"),
    ("cliff_obstacle", "model", "TCRT5000"),
    ("imu", "manufacturer", "BerryIMU"),
    ("imu", "model", "Berry-IMU v3"),
    ("ads1115", "model", "ADS1015"),
    ("ads1115", "sku", "ADS-1015"),
    ("ads1115", "product_url", "https://example.com/ADS%31%30%31%35"),
])
def test_conflicting_reviewed_sensor_identity_is_held(role, field, replacement):
    assert not selected_sensor_identity_matches(
        role, SELECTED_SENSOR_NAMES[role], {field: replacement}
    )


@pytest.mark.parametrize("field", [
    "seller", "manufacturer", "brand", "model", "name", "stock_evidence_url",
    "vendor", "sku", "seller_sku", "candidate_seller_sku", "product_name",
    "product_url", "resolved_item", "pcb_revision",
])
def test_new_adafruit_identity_is_held_but_owned_is_allowed(field):
    candidate = {field: "Adafruit Industries"}
    assert adafruit_new_hardware(candidate, 1)
    assert not adafruit_new_hardware(candidate, 0)


def test_historical_notes_and_unrelated_roles_are_not_substitutions():
    historical = {"notes": "Adafruit driver; BerryIMU owned spare; VL53L4CD rejected"}
    assert not adafruit_new_hardware(historical, 1)
    assert selected_sensor_identity_matches(
        "imu", SELECTED_SENSOR_NAMES["imu"], historical
    )
    assert selected_sensor_identity_matches("head_touch", "AT42QT1010", historical)


def test_ads1115_generic_candidate_is_not_a_frozen_supplier():
    assert selected_sensor_identity_matches(
        "ads1115", "ADS1115 4 channel ADC breakout",
        {"sku": "COM-05-045", "model": "ADS1115", "notes": "ADS1015 rejected"},
    )
