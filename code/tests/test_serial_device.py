"""Reject non-device and indirect serial paths before hardware admission."""

import stat
from types import SimpleNamespace

import pytest
from desk_robot import serial_device


@pytest.mark.parametrize("port", [
    "/dev/cu.usbmodem123", "/dev/tty.usbserial-123", "/dev/ttyUSB0", "/dev/ttyACM1",
])
def test_direct_serial_names(port):
    assert serial_device.is_local_serial_path(port)


@pytest.mark.parametrize("port", [
    None, 1, "", "ttyUSB0", "/dev/null", "/dev/pts/0", "/dev/../tmp/ttyUSB0",
    "/dev//ttyUSB0", "/dev/serial/by-id/usb-device", "/dev/cu.test\n", "/dev/cu.",
    "/dev/cu." + "x" * 256,
])
def test_invalid_serial_names_never_stat(monkeypatch, port):
    monkeypatch.setattr(serial_device, "os", SimpleNamespace(lstat=lambda _: pytest.fail("stat")))
    assert not serial_device.is_local_serial_path(port)
    with pytest.raises(ValueError, match="direct"):
        serial_device.require_local_serial_device(port)


@pytest.mark.parametrize("mode", [stat.S_IFREG, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFLNK])
def test_serial_name_does_not_authorize_non_character_node(monkeypatch, mode):
    monkeypatch.setattr(serial_device, "os", SimpleNamespace(
        lstat=lambda _: SimpleNamespace(st_mode=mode),
    ))
    with pytest.raises(ValueError, match="character device"):
        serial_device.require_local_serial_device("/dev/cu.test")


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError, OSError])
def test_stat_failure_fails_closed(monkeypatch, error_type):
    error = error_type("sensitive device detail")

    def missing(_):
        raise error

    monkeypatch.setattr(serial_device, "os", SimpleNamespace(lstat=missing))
    with pytest.raises(ValueError, match="^Local USB serial device unavailable$") as caught:
        serial_device.require_local_serial_device("/dev/cu.test")
    assert caught.value.__cause__ is error


def test_character_node_passes_preflight(monkeypatch):
    monkeypatch.setattr(
        serial_device, "os", SimpleNamespace(lstat=lambda _: SimpleNamespace(st_mode=stat.S_IFCHR)),
    )
    serial_device.require_local_serial_device("/dev/cu.test")
