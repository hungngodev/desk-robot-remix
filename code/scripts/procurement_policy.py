"""Frozen selected hardware identities; not physical qualification evidence."""
from __future__ import annotations

from collections.abc import Iterator

SELECTED_SENSOR_NAMES = {
    "cliff_obstacle": "VL53L0X GY-530 small carrier candidate ElectroPeak SEN-19-006",
    "imu": "MPU6050 GY521 compatible six axis breakout",
}
_REJECTED_SENSOR_IDENTITIES = {
    "cliff_obstacle": ("vl53l4cd", "vl6180x", "tcrt5000", "sen19018"),
    "imu": ("berryimu",),
}
_IDENTITY_FIELDS = (
    "vendor", "seller", "manufacturer", "brand", "sku", "model", "name",
    "product_name", "product_url", "stock_evidence_url", "resolved_item", "pcb_revision",
)


def _identity_values(candidate: object) -> Iterator[str]:
    if isinstance(candidate, dict):
        for field in _IDENTITY_FIELDS:
            value = candidate.get(field)
            if isinstance(value, str):
                yield value.casefold()


def adafruit_new_hardware(candidate: object, quantity: int) -> bool:
    """Ban new branded hardware, not existing stock or driver references."""
    return quantity > 0 and any("adafruit" in value for value in _identity_values(candidate))


def selected_sensor_identity_matches(role: str, name: object, reviewed: object) -> bool:
    """Reject changed plan identities and explicit conflicting reviewed models."""
    if role not in SELECTED_SENSOR_NAMES:
        return True
    if name != SELECTED_SENSOR_NAMES[role]:
        return False
    forbidden = _REJECTED_SENSOR_IDENTITIES[role]
    return not any(
        token in "".join(char for char in value if char.isalnum())
        for value in _identity_values(reviewed)
        for token in forbidden
    )
