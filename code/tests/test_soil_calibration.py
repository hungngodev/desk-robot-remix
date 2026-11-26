"""Measured plant probe calibration, never synthetic sensor truth."""

import pytest

from desk_robot.soil_calibration import SoilCalibration


def test_measured_wet_dry_mapping():
    common = SoilCalibration(dry_adc=3200, wet_adc=1300)
    assert common.percentage(3200) == 0
    assert common.percentage(1300) == 100
    assert common.percentage(2250) == 50
    assert common.percentage(4094) == 0
    assert common.percentage(1) == 100


@pytest.mark.parametrize("dry,wet", [
    (0, 3200), (4000, 4095), (2075, 2000), (True, 3000),
    (2.0, 2000), ("1200", 2800), (2000, 2000), (4095, 1300), (3200, 0),
    (1099, 1000),
])
def test_fake_missing_or_noise_level_calibration_rejected(dry, wet):
    with pytest.raises(ValueError):
        SoilCalibration(dry_adc=dry, wet_adc=wet)


@pytest.mark.parametrize("dry,wet", [(1100, 3100), (1, 4094), (1000, 1100)])
def test_inverted_sen0193_calibration_rejected(dry, wet):
    with pytest.raises(ValueError, match="dry ADC must exceed wet ADC"):
        SoilCalibration(dry, wet)


@pytest.mark.parametrize("raw", [0, 4095, 5000, -1, 2.5, True])
def test_invalid_raw_probe_reading_never_becomes_moisture(raw):
    with pytest.raises(ValueError):
        SoilCalibration(3200, 1300).percentage(raw)


def test_exact_half_percent_rounds_to_even():
    calibration = SoilCalibration(1120, 1000)
    assert calibration.percentage(1051) == 58


@pytest.mark.parametrize("dry,wet", [(4094, 1), (1100, 1000), (3200, 1300)])
def test_full_adc_domain_matches_exact_clamped_ratio(dry, wet):
    from fractions import Fraction

    calibration = SoilCalibration(dry, wet)
    for raw in range(1, 4095):
        exact = Fraction(100 * (raw - dry), wet - dry)
        assert calibration.percentage(raw) == round(max(0, min(100, exact)))
