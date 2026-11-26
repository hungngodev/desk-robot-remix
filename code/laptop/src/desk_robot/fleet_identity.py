"""Comparison keys for fleet hardware identities, not wire routing IDs."""

import re


def device_identity_key(device_id: str) -> str:
    """Compare conventional MAC spellings without rewriting opaque device IDs."""
    key = device_id.strip().casefold()
    if re.fullmatch(r"[0-9a-f]{12}|(?:[0-9a-f]{2}:){5}[0-9a-f]{2}|"
                    r"(?:[0-9a-f]{2}-){5}[0-9a-f]{2}", key):
        return key.replace(":", "").replace("-", "")
    return key
