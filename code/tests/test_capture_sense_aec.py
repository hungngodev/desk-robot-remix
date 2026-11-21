"""Regression for authenticated one-shot Sense codec PCM capture, not playback."""
import importlib.util
import io
import json
import stat
import struct
import urllib.error
import urllib.request
import urllib.response
import wave
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/capture_sense_aec.py"
SPEC = importlib.util.spec_from_file_location("capture_sense_aec", SOURCE)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class Response(io.BytesIO):
    def __init__(self, value, status=200, headers=None):
        if isinstance(value, dict):
            value = json.dumps(value).encode()
        super().__init__(value)
        self.status = status
        self.headers = headers or {}


class HeadHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method(),
                           request.get_header("Authorization"), timeout))
        if not self.responses:
            raise AssertionError("Unexpected additional head capture call")
        return self.responses.pop(0)


def fake_read(*, raw=None, boot=7, robot="robot-01", raw_boot=None,
              frames=64000, ready=True):
    if raw is None:
        raw = struct.pack("<hh", 123, -456) * capture.FRAMES
    header = {
        "Content-Type": "application/octet-stream",
        "X-Desk-Audio-Robot-Id": robot,
        "X-Desk-Audio-Boot": str(boot if raw_boot is None else raw_boot),
        "X-Desk-Audio-Frames": "64000",
        "X-Desk-Audio-First-Us": "1000000",
        "X-Desk-Audio-Last-Us": "5000000",
    }
    return HeadHTTP([
        Response({
            "robot_id": robot, "boot": boot,
            "reference_integrity_failed": False,
            "speaker_playback_verified": False,
            "aec_physically_qualified": False,
        }),
        Response({"ok": True, "robot_id": robot}, status=202),
        Response({
            "robot_id": robot, "boot": boot, "active": not ready,
            "ready": ready, "failed": False, "frames": frames,
            "physical_aec_qualified": False,
        }),
        Response(raw, headers=header),
    ])


def test_authenticated_head_pcm_delivers_one_bounded_private_wav_pair(tmp_path):
    http = fake_read()
    raw, report = capture.capture_head(
        http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
        clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
    )
    assert len(raw) == capture.BYTES == 256000
    assert [path.split("/")[-1] for path, *_ in http.calls] == [
        "audio.reference", "audio.capture.start",
        "audio.capture.status", "audio.capture.raw",
    ]
    assert [method for _, method, *_ in http.calls] == [
        "GET", "POST", "GET", "GET",
    ]
    assert all(header == "Bearer " + "x" * 32 for _, _, header, _ in http.calls)
    assert report["frames"] == 64000 and report["boot"] == 7
    for value in ("physical_speaker_playback_verified",
                  "aec_physically_qualified",
                  "source_device_physically_authenticated"):
        assert report[value] is False
    folder = tmp_path / "private"
    capture.save_wavs(folder, raw, report)
    assert stat.S_IMODE(folder.stat().st_mode) & 0o077 == 0
    mic, ref = capture.split_pcm(raw)
    for filename, channel in (("microphone.wav", mic), ("speaker_reference.wav", ref)):
        file = folder / filename
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        with wave.open(str(file), "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
                16000, 1, 2,
            )
            assert wav.getnframes() == 64000
            assert wav.readframes(64000) == channel
    with pytest.raises(FileExistsError):
        capture.save_wavs(folder, raw, report)


@pytest.mark.parametrize("address", [
    "http://0.0.0.0:8081", "http://8.8.8.8:8081",
    "http://192.168.1.2:1234", "https://192.168.1.2:8081",
    "http://user:secret@192.168.1.2:8081",
    "http://192.168.1.2:8081/path",
])
def test_auth_capture_never_sends_device_token_to_unsafe_address(address):
    with pytest.raises(ValueError):
        capture.head_address(address)


def test_authenticated_capture_rejects_reboot_wrong_robot_and_short_payload():
    for changed in (
        fake_read(raw_boot=8),
        fake_read(robot="robot-02"),
        fake_read(raw=b"short"),
        fake_read(frames=6),
    ):
        with pytest.raises((ValueError, RuntimeError)):
            capture.capture_head(
                changed, "http://192.168.1.23:8081", "robot-01", "x" * 32,
                clock=iter([0.0, .1]).__next__, pause=lambda _: None,
            )


def test_consent_audio_capture_compiled_off_by_default():
    root = SOURCE.parents[1]
    head = (root / "firmware/head/sense/sense_reference_codec.h").read_text()
    bridge = (root / "firmware/head/overlay/robot_bridge.cc").read_text()
    assert "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED" in head
    for route in (
        "/api/audio.capture.start", "/api/audio.capture.status",
        "/api/audio.capture.raw",
    ):
        assert route in bridge
    assert 'if (!Authorize(req))' in bridge
    assert 'ReleaseBenchPcmCapture(pcm.interleaved)' in bridge


def test_private_capture_opener_does_not_follow_redirect_with_bearer():
    """A compromised LAN robot must not redirect its bearer to a second host."""
    seen = []

    class RedirectingHead(urllib.request.HTTPHandler):
        def http_open(self, request):
            seen.append((request.full_url, request.get_header("Authorization")))
            return urllib.response.addinfourl(
                io.BytesIO(b""),
                {"Location": "https://example.invalid/steal-bearer"},
                request.full_url, code=302,
            )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), capture.NoRedirect(), RedirectingHead(),
    )
    origin = "http://192.168.1.23:8081/api/audio.reference"
    request = urllib.request.Request(
        origin, headers={"Authorization": "Bearer " + "x" * 32},
    )
    with pytest.raises(urllib.error.HTTPError, match="Sense capture redirect refused"):
        opener.open(request, timeout=1)
    assert seen == [(origin, "Bearer " + "x" * 32)]


def test_capture_main_installs_no_redirect_handler():
    """The guarded opener must be used by the real user facing CLI."""
    source = SOURCE.read_text()
    assert "urllib.request.ProxyHandler({}), NoRedirect()" in source
