"""Keep INA226 raw saturation rejection wired into the real WROOM producer.

Source integration contract only. The portable C++ test covers numeric values;
real shunt calibration, direction and charging authority remain hardware gates.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ina226_saturation_guard_controls_actual_monitor_validity():
    header = (ROOT / "code/firmware/body/lib/AccessorySensors/AccessoryReadings.h").read_text()
    producer = (ROOT / "code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp").read_text()
    assert "raw == 0x7fffU || raw == 0x8000U" in header
    assert "g.monitor_valid = ina226_shunt_uv_from_raw(shunt, g.shunt_uv);" in producer
    assert "g.shunt_uv = ina226_shunt_uv(" not in producer
    assert producer.index("g.monitor_valid = ina226_shunt_uv_from_raw") < producer.index(
        "g.monitor_sample_seq = next_nonzero_sensor_sequence"
    )
    assert "g.pack_current_valid = false;" in producer
