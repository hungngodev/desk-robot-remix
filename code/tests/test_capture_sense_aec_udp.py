"""Regression for the opt-in, unverified Xiaozhi MIC/REFERENCE capture."""
import importlib.util
import os
import socket
import stat
import struct
import wave
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/capture_sense_aec_udp.py"
spec = importlib.util.spec_from_file_location("capture_sense_aec_udp", SOURCE)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def test_interleaved_channels_yield_private_aligned_wavs(tmp_path):
    raw = struct.pack("<hhhh", 100, -200, 300, -400)
    mic, ref = capture.split_interleaved(raw)
    assert struct.unpack("<hh", mic) == (100, 300)
    assert struct.unpack("<hh", ref) == (-200, -400)
    folder = tmp_path / "bench"
    capture.write_capture(folder, raw, {"aec_physically_qualified": False})
    assert stat.S_IMODE(folder.stat().st_mode) & 0o077 == 0
    for filename, expected in (("microphone.wav", mic), ("speaker_reference.wav", ref)):
        file = folder / filename
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        with wave.open(str(file), "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            assert wav.readframes(2) == expected
    with pytest.raises(FileExistsError):
        capture.write_capture(folder, raw, {})


def test_malformed_samples_and_public_output_directory_fail_closed(tmp_path):
    for value in (b"", b"x", b"abc", b"abcde"):
        with pytest.raises(ValueError):
            capture.split_interleaved(value)
    folder = tmp_path / "public"
    folder.mkdir()
    os.chmod(folder, 0o755)
    with pytest.raises(ValueError, match="private"):
        capture.write_capture(folder, struct.pack("<hh", 1, 2), {})


class Packets:
    def __init__(self, items):
        self.items = iter(items)

    def recvfrom(self, length):
        assert length == capture.MAX_DATAGRAM + 1
        try:
            return next(self.items)
        except StopIteration as exc:
            raise socket.timeout() from exc


def test_five_seconds_capture_rejects_foreign_and_never_claims_hardware_proof():
    packet = struct.pack("<hh", 123, -456) * (capture.MAX_DATAGRAM // 4)
    count = (5 * 16000 * 4 + len(packet) - 1) // len(packet)
    packets = [(b"no", ("192.168.1.99", 1111))]
    packets += [(packet, ("192.168.1.22", 4001)) for _ in range(count)]
    times = iter(i * .025 for i in range(count))
    raw, info = capture.receive_capture(
        Packets(packets), expected_source_ip="192.168.1.22",
        clock=lambda: next(times),
    )
    assert len(raw) == 5 * 16000 * 4
    assert info["frames"] == 80000
    assert info["packets_accepted"] == count
    assert info["foreign_packets_ignored"] == 1
    assert info["same_codec_read_channel_alignment"] is True
    for key in ("udp_packet_loss_proven_absent", "source_device_authenticated",
                "physical_playback_verified", "aec_physically_qualified",
                "clock_drift_verified"):
        assert info[key] is False


def test_raw_audio_bench_listener_refuses_public_and_wildcard_addresses():
    for name in ("0.0.0.0", "8.8.8.8", "224.0.0.1", "255.255.255.255"):
        with pytest.raises(ValueError):
            capture.lab_ip(name)
    assert str(capture.lab_ip("192.168.7.10")) == "192.168.7.10"
    assert str(capture.lab_ip("127.0.0.1")) == "127.0.0.1"


def test_udp_gaps_partial_frames_and_dead_feed_are_rejected():
    packet = struct.pack("<hh", 123, -456) * 30
    with pytest.raises(RuntimeError, match="gap"):
        capture.receive_capture(
            Packets([(packet, ("10.0.0.5", 99))] * 2),
            expected_source_ip="10.0.0.5",
            clock=iter((0.0, .5)).__next__,
        )
    with pytest.raises(RuntimeError, match="misaligned"):
        capture.receive_capture(
            Packets([(b"abc", ("10.0.0.5", 99))]),
            expected_source_ip="10.0.0.5",
        )
    with pytest.raises(RuntimeError, match="feed stopped"):
        capture.receive_capture(Packets([]), expected_source_ip="10.0.0.5")
    with pytest.raises(ValueError):
        capture.receive_capture(Packets([]), expected_source_ip="invalid")
    with pytest.raises(ValueError):
        capture.receive_capture(Packets([]), expected_source_ip="10.0.0.5", duration_s=100)


def test_audio_source_uses_actual_xiaozhi_stereo_codec_not_synthetic_reference():
    root = SOURCE.parents[1]
    codec = (root / "firmware/head/sense/sense_reference_codec.cc").read_text()
    assert "input_channels_ = 2;" in codec
    assert "dest[2 * i] = microphone_frame_[i];" in codec
    assert "dest[2 * i + 1] = reference_frame_[i];" in codec
    assert "USE_AUDIO_DEBUGGER" in SOURCE.read_text()
