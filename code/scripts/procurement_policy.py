"""Frozen selected hardware identities; not physical qualification evidence."""
from __future__ import annotations

from collections.abc import Iterator
from unicodedata import normalize
from urllib.parse import unquote

SELECTED_SENSOR_NAMES = {
    "cliff_obstacle": "VL53L0X GY-530 small carrier candidate ElectroPeak SEN-19-006",
    "imu": "MPU6050 GY521 compatible six axis breakout",
    "ads1115": "ADS1115 4 channel ADC breakout",
    "wroom": "ESP32 WROOM32 development board",
    "xiao_sense": "XIAO ESP32S3 Sense camera + microphone",
}
_REJECTED_SENSOR_IDENTITIES = {
    "cliff_obstacle": ("vl53l4cd", "vl6180x", "tcrt5000", "sen19018"),
    "imu": ("berryimu",),
    "ads1115": ("ads1015",),
    "wroom": ("esp32c3", "c3supermini"),
    "xiao_sense": ("esp32c3", "c3supermini"),
}
_IDENTITY_FIELDS = (
    "vendor", "seller", "manufacturer", "brand", "sku", "seller_sku",
    "candidate_seller_sku", "model", "name", "product_name", "product_url",
    "stock_evidence_url", "resolved_item", "pcb_revision",
    "manufacturer_or_brand", "source_vendor", "source_sku", "source_url",
    "checkout_seller_candidate", "part_name", "part_number", "title",
    "manufacturer_part_number",
)


def _identity_values(candidate: object) -> Iterator[str]:
    if isinstance(candidate, dict):
        for field in _IDENTITY_FIELDS:
            value = candidate.get(field)
            if isinstance(value, str):
                normalized = normalize("NFKC", unquote(value)).casefold()
                yield "".join(char for char in normalized if char.isalnum())


def adafruit_new_hardware(candidate: object, quantity: int) -> bool:
    """Ban new branded hardware, not existing stock or driver references."""
    return quantity > 0 and any("adafruit" in value for value in _identity_values(candidate))


def selected_sensor_identity_matches(role: str, name: object, reviewed: object) -> bool:
    """Reject changed plan identities and explicit conflicting reviewed models."""
    if role not in SELECTED_SENSOR_NAMES:
        return True
    if name != SELECTED_SENSOR_NAMES[role]:
        return False
    return not rejected_hardware_identity(role, reviewed)


def rejected_hardware_identity(role: str, candidate: object) -> bool:
    """Reject explicit incompatible board identities in the selected role."""
    forbidden = _REJECTED_SENSOR_IDENTITIES.get(role, ())
    return any(token in value for value in _identity_values(candidate) for token in forbidden)
