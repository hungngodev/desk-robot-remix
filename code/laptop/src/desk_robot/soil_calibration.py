"""Relative plant moisture only from user-measured ADC calibration endpoints.

For the selected SEN0193 probe, dry ADC must exceed wet ADC. This maps
one probe's measured references to a local 0..100 scale.
The actual board and soil still require a physical calibration procedure.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SoilCalibration:
    dry_adc: int
    wet_adc: int

    def __post_init__(self) -> None:
        for value in (self.dry_adc, self.wet_adc):
            if type(value) is not int or not 1 <= value <= 4094:
                raise ValueError("Soil calibration requires 12-bit measured ADC integers")
        if abs(self.dry_adc - self.wet_adc) < 100:
            raise ValueError("Soil wet and dry measured ADC values are too close")
        if self.dry_adc < self.wet_adc:
            raise ValueError("SEN0193 dry ADC must exceed wet ADC")

    def percentage(self, raw_adc: int) -> int:
        if type(raw_adc) is not int or not 1 <= raw_adc <= 4094:
            raise ValueError("Cannot calibrate an invalid soil ADC reading")
        percent = 100 * (raw_adc - self.dry_adc) / (self.wet_adc - self.dry_adc)
        return round(max(0.0, min(100.0, percent)))
