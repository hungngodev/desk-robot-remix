import importlib.util
import socket
import stat
import threading
import time
import wave
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "audio_debug_server", Path(__file__).resolve().parent.parent / "audio_debug_server.py"
)
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_no_pcm_and_no_overwrite(tmp_path):
    output = tmp_path / "record.wav"
    with pytest.raises(ValueError, match="no valid PCM"):
        server.capture("127.0.0.1", "127.0.0.1", port(), 8000, 1, .02, output)
    with wave.open(str(output)) as wav:
        assert wav.getnframes() == 0
    output.write_bytes(b"private")
    with pytest.raises(FileExistsError):
        server.capture("127.0.0.1", "127.0.0.1", port(), 8000, 1, .02, output)
    assert output.read_bytes() == b"private"


def test_alignment_and_bounds_real_udp(tmp_path):
    output = tmp_path / "record.wav"
    target = port()

    def send():
        deadline = time.monotonic() + 1
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(.001)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"x", ("127.0.0.1", target))
            sock.sendto(b"ab" * 2000, ("127.0.0.1", target))

    sender = threading.Thread(target=send)
    sender.start()
    try:
        assert server.capture("127.0.0.1", "127.0.0.1", target, 8000, 1, .1, output) == 800
    finally:
        sender.join()
    with wave.open(str(output)) as wav:
        assert wav.readframes(1000) == b"ab" * 800
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 301])
def test_invalid_duration(tmp_path, duration):
    with pytest.raises(ValueError):
        server.capture("127.0.0.1", "127.0.0.1", port(), 8000, 1, duration, tmp_path / "x")


def test_wrong_peer_and_symlink(tmp_path):
    output = tmp_path / "record.wav"
    target = port()

    def send():
        deadline = time.monotonic() + 1
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(.001)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"ab" * 100, ("127.0.0.1", target))

    sender = threading.Thread(target=send)
    sender.start()
    try:
        with pytest.raises(ValueError, match="no valid PCM"):
            server.capture("127.0.0.1", "127.0.0.2", target, 8000, 1, .1, output)
    finally:
        sender.join()
    link = tmp_path / "link.wav"
    link.symlink_to(output)
    with pytest.raises(FileExistsError):
        server.capture("127.0.0.1", "127.0.0.1", port(), 8000, 1, .02, link)
