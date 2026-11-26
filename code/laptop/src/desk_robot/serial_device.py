"""Local USB serial admission shared by configuration and hardware entrypoints."""

import os
import re
import stat

_DEVICE_PATH = re.compile(r"/dev/(?:cu\.[A-Za-z0-9._-]+|tty\.[A-Za-z0-9._-]+|tty(?:USB|ACM)[0-9]+)")


def is_local_serial_path(port: object) -> bool:
    """Accept only direct macOS or Linux serial device names, not aliases."""
    return isinstance(port, str) and len(port) <= 255 and _DEVICE_PATH.fullmatch(port) is not None


def require_local_serial_device(port: str) -> None:
    """Check the actual node immediately before pySerial opens it."""
    if not is_local_serial_path(port):
        raise ValueError("Explicit direct /dev/ USB serial port required")
    try:
        mode = os.lstat(port).st_mode
    except OSError as exc:
        raise ValueError("Local USB serial device unavailable") from exc
    if not stat.S_ISCHR(mode):
        raise ValueError("Local USB serial port must be a character device, not a link")
