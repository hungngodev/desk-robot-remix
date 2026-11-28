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
        server.capture("127.0.0.1", "127.0.0.1", port(), 8000, 1, .02, output, consent=True)
    with wave.open(str(output)) as wav:
        assert wav.getnframes() == 0
    output.write_bytes(b"private")
    with pytest.raises(FileExistsError):
        server.capture("127.0.0.1", "127.0.0.1", port(), 8000, 1, .02, output, consent=True)
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
        assert server.capture(
            "127.0.0.1", "127.0.0.1", target, 8000, 1, .1, output, consent=True
        ) == 800
    finally:
        sender.join()
    with wave.open(str(output)) as wav:
        assert wav.readframes(1000) == b"ab" * 800
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 301])
def test_invalid_duration(tmp_path, duration):
    with pytest.raises(ValueError):
        server.capture(
            "127.0.0.1", "127.0.0.1", port(), 8000, 1, duration, tmp_path / "x", consent=True
        )


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
            server.capture(
                "127.0.0.1", "127.0.0.2", target, 8000, 1, .1, output, consent=True
            )
    finally:
        sender.join()
    link = tmp_path / "link.wav"
    link.symlink_to(output)
    with pytest.raises(FileExistsError):
        server.capture("127.0.0.1", "127.0.0.1", port(), 8000, 1, .02, link, consent=True)


@pytest.mark.parametrize("bind, peer", [
    ("0.0.0.0", "127.0.0.1"),
    ("192.168.1.10", "127.0.0.1"),
    ("127.0.0.1", "192.168.1.11"),
    ("127.0.0.1", "0.0.0.0"),
])
def test_non_loopback_rejected_before_socket(tmp_path, monkeypatch, bind, peer):
    def unexpected_socket(*args, **kwargs):
        pytest.fail("socket opened before address validation")

    monkeypatch.setattr(server.socket, "socket", unexpected_socket)
    output = tmp_path / "record.wav"
    with pytest.raises(ValueError, match="loopback"):
        server.capture(bind, peer, 8000, 8000, 1, .1, output, consent=True)
    assert not output.exists()


@pytest.mark.parametrize("kwargs", [{}, {"consent": False}, {"consent": 1}])
def test_consent_required_before_socket(tmp_path, monkeypatch, kwargs):
    def unexpected_socket(*args, **kwargs):
        pytest.fail("socket opened before consent")

    monkeypatch.setattr(server.socket, "socket", unexpected_socket)
    output = tmp_path / "record.wav"
    with pytest.raises(ValueError, match="consent"):
        server.capture("127.0.0.1", "127.0.0.1", 8000, 8000, 1, .1, output, **kwargs)
    assert not output.exists()


@pytest.mark.parametrize(
    "field, value",
    [("port", True), ("port", 8000.0), ("samplerate", 8000.0),
     ("channels", True), ("channels", 1.0), ("duration", True),
     ("duration", "0.1"), ("duration", 1e-6)],
)
def test_capture_rejects_invalid_limits_before_io(tmp_path, monkeypatch, field, value):
    def unexpected_socket(*args, **kwargs):
        pytest.fail("socket opened before numeric validation")

    monkeypatch.setattr(server.socket, "socket", unexpected_socket)
    output = tmp_path / "record.wav"
    args = dict(bind="127.0.0.1", peer="127.0.0.1", port=8000,
                samplerate=8000, channels=1, duration=.1, output=output, consent=True)
    args[field] = value
    with pytest.raises(ValueError, match="invalid capture limits"):
        server.capture(**args)
    assert not output.exists()


def test_socket_released_when_output_creation_fails(tmp_path):
    output = tmp_path / "record.wav"
    output.write_bytes(b"existing")
    target = port()
    with pytest.raises(FileExistsError):
        server.capture("127.0.0.1", "127.0.0.1", target, 8000, 1, .1, output, consent=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", target))
    assert output.read_bytes() == b"existing"


def test_late_datagram_discarded_and_socket_released(tmp_path, monkeypatch):
    output = tmp_path / "late.wav"
    target = port()
    ticks = iter((10.0, 10.0, 10.2))

    class LateReceiver:
        def __enter__(self):
            self.receiver = real_socket(socket.AF_INET, socket.SOCK_DGRAM)
            return self

        def __exit__(self, *args):
            self.receiver.close()

        def bind(self, address):
            self.receiver.bind(address)

        def settimeout(self, timeout):
            self.receiver.settimeout(timeout)

        def recvfrom(self, size):
            return b"ab" * 800, ("127.0.0.1", 12345)

    real_socket = socket.socket
    with monkeypatch.context() as patch:
        patch.setattr(server.time, "monotonic", lambda: next(ticks))
        patch.setattr(server.socket, "socket", lambda *args: LateReceiver())
        with pytest.raises(ValueError, match="no valid PCM"):
            server.capture("127.0.0.1", "127.0.0.1", target, 8000, 1, .1, output, consent=True)
    with wave.open(str(output)) as wav:
        assert wav.getnframes() == 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", target))


def test_competing_bind_and_timeout_release(tmp_path):
    output = tmp_path / "competing.wav"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as active:
        active.bind(("127.0.0.1", 0))
        target = active.getsockname()[1]
        with pytest.raises(OSError):
            server.capture("127.0.0.1", "127.0.0.1", target, 8000, 1, .1, output, consent=True)
        assert not output.exists()
    with pytest.raises(ValueError, match="no valid PCM"):
        server.capture("127.0.0.1", "127.0.0.1", target, 8000, 1, .02, output, consent=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", target))


def test_rejected_datagrams_backoff_without_extending_deadline(tmp_path, monkeypatch):
    ticks = iter((10.0, 10.0, 10.01, 10.02, 10.0995, 10.1))
    sleeps = []
    received = []
    closed = []

    class Receiver:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

        def bind(self, address):
            pass

        def settimeout(self, timeout):
            assert 0 < timeout <= .1

        def recvfrom(self, size):
            assert size == 65535
            received.append(True)
            return b"x", ("127.0.0.1", 12345)

    monkeypatch.setattr(server.socket, "socket", lambda *args: Receiver())
    monkeypatch.setattr(server.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(server.time, "sleep", sleeps.append)
    output = tmp_path / "invalid.wav"
    with pytest.raises(ValueError, match="no valid PCM"):
        server.capture("127.0.0.1", "127.0.0.1", 8000, 8000, 1, .1, output, consent=True)
    assert sleeps == pytest.approx([.001, .0005])
    assert received == [True, True]
    assert closed == [True]
    with wave.open(str(output)) as wav:
        assert wav.getnframes() == 0


def test_repeated_sender_close_releases_receiver(tmp_path):
    target = port()
    for index in range(12):
        output = tmp_path / f"partial-{index}.wav"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            def send_then_close(output=output, sender=sender):
                deadline = time.monotonic() + 1
                while not output.exists() and time.monotonic() < deadline:
                    time.sleep(.001)
                sender.sendto(b"ab" * 8, ("127.0.0.1", target))
                sender.close()

            worker = threading.Thread(target=send_then_close)
            worker.start()
            try:
                assert server.capture(
                    "127.0.0.1", "127.0.0.1", target, 8000, 1, .05, output, consent=True
                ) == 8
            finally:
                worker.join()
        with wave.open(str(output)) as wav:
            assert wav.getnframes() == 8
            assert wav.readframes(9) == b"ab" * 8
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", target))


def test_wave_setup_failure_closes_file_and_receiver(tmp_path, monkeypatch):
    target = port()
    opened = []

    def fail_wave(raw, mode):
        opened.append(raw)
        raise OSError("wave setup failed")

    monkeypatch.setattr(server.wave, "open", fail_wave)
    for index in range(12):
        output = tmp_path / f"failed-{index}.wav"
        with pytest.raises(OSError, match="wave setup failed"):
            server.capture("127.0.0.1", "127.0.0.1", target, 8000, 1, .1, output, consent=True)
        assert opened[-1].closed
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", target))
