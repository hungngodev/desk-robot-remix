"""Measured plant probe calibration, never synthetic sensor truth."""
import pytest
from desk_robot.soil_calibration import SoilCalibration


def test_measured_wet_dry_mapping_in_both_sensor_polarities():
    common = SoilCalibration(dry_adc=3200, wet_adc=1300)
    assert common.percentage(3200) == 0
    assert common.percentage(1300) == 100
    assert common.percentage(2250) == 50
    assert common.percentage(4094) == 0
    assert common.percentage(1) == 100
    reverse = SoilCalibration(dry_adc=1100, wet_adc=3100)
    assert reverse.percentage(1100) == 0
    assert reverse.percentage(3100) == 100
    assert reverse.percentage(2100) == 50


@pytest.mark.parametrize("dry,wet", [
    (0, 3200), (4000, 4095), (2000, 2075), (True, 3000),
    (2.0, 2000), ("1200", 2800), (2000, 2000),
])
def test_fake_missing_or_noise_level_calibration_rejected(dry, wet):
    with pytest.raises(ValueError):
        SoilCalibration(dry_adc=dry, wet_adc=wet)


@pytest.mark.parametrize("raw", [0, 4095, 5000, -1, 2.5, True])
def test_invalid_raw_probe_reading_never_becomes_moisture(raw):
    with pytest.raises(ValueError):
        SoilCalibration(3200, 1300).percentage(raw)
