"""Fleet identity comparison keys, never aliases for wire routing IDs."""

import re

from .private_files import is_private_robot_id


def valid_unique_robot_ids(robot_ids: object) -> bool:
    """Require portable IDs with no collisions on case-insensitive storage."""
    return (
        isinstance(robot_ids, (list, tuple))
        and bool(robot_ids)
        and all(is_private_robot_id(robot_id) for robot_id in robot_ids)
        and len({robot_id.casefold() for robot_id in robot_ids}) == len(robot_ids)
    )


def device_identity_key(device_id: str) -> str:
    """Compare hardware IDs for collisions; retain literal IDs for routing."""
    key = device_id.strip().casefold()
    if re.fullmatch(r"[0-9a-f]{12}|(?:[0-9a-f]{2}:){5}[0-9a-f]{2}|"
                    r"(?:[0-9a-f]{2}-){5}[0-9a-f]{2}", key):
        return key.replace(":", "").replace("-", "")
    return key
