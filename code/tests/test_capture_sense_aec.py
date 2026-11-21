"""Regression for authenticated one-shot Sense codec PCM capture, not playback."""
import email.message
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
              frames=64000, ready=True, delay_ms=0, mic_muted=False,
              last_us=5000000, privacy_epoch=3, final_epoch=None,
              start_generation="1", status_generation="1", raw_generation="1",
              final_generation=None, final_muted=False, final_boot=None,
              initial_mic=100, final_mic=64100,
              initial_speaker=200, final_speaker=8400,
              speaker_in_window=True):
    if raw is None:
        raw = struct.pack("<hh", 123, -456) * capture.FRAMES
    header = {
        "Content-Type": "application/octet-stream",
        "X-Desk-Audio-Robot-Id": robot,
        "X-Desk-Audio-Boot": str(boot if raw_boot is None else raw_boot),
        "X-Desk-Audio-Frames": "64000",
        "X-Desk-Audio-Generation": raw_generation,
        "X-Desk-Audio-First-Us": "1000000",
        "X-Desk-Audio-Last-Us": str(last_us),
    }
    return HeadHTTP([
        Response({
            "robot_id": robot, "boot": boot,
            "reference_integrity_failed": False,
            "aec_delay_config_ms": delay_ms,
            "microphone_privacy_muted": mic_muted,
            "microphone_privacy_epoch": privacy_epoch,
            "microphone_frames_read": initial_mic,
            "speaker_frames_accepted": initial_speaker,
            "speaker_playback_verified": False,
            "aec_physically_qualified": False,
        }),
        Response({
            "ok": True, "robot_id": robot, "boot": boot,
            "capture_generation": start_generation,
        }, status=202),
        Response({
            "robot_id": robot, "boot": boot, "active": not ready,
            "ready": ready, "failed": False, "frames": frames,
            "speaker_activity_in_window": speaker_in_window,
            "physical_aec_qualified": False,
            "capture_generation": status_generation,
        }),
        Response(raw, headers=header),
        Response({
            "robot_id": robot,
            "boot": boot if final_boot is None else final_boot,
            "microphone_privacy_epoch": (
                privacy_epoch if final_epoch is None else final_epoch
            ),
            "microphone_privacy_muted": final_muted,
            "capture_generation": (
                start_generation if final_generation is None else final_generation
            ),
            "microphone_frames_read": final_mic,
            "speaker_frames_accepted": final_speaker,
            "reference_integrity_failed": False,
        }),
    ])


@pytest.mark.parametrize("changed", [
    {"final_speaker": 200},  # No accepted I2S frames during recording.
    {"final_mic": 64099},    # Nominal WAV length is not device read evidence.
    {"final_mic": 99},       # Counter regression/reboot during the trial.
    {"final_speaker": 199},
    {"initial_mic": 0xffffffff},
    {"initial_speaker": 0xffffffff},
])
def test_private_aec_capture_requires_live_audio_activity(changed):
    http = fake_read(**changed)
    with pytest.raises((RuntimeError, ValueError), match="activity|saturated"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )
    if "initial_mic" in changed or "initial_speaker" in changed:
        # Refuse saturated counters before starting a private recording.
        assert [call[0].split("/")[-1] for call in http.calls] == [
            "audio.reference",
        ]
    else:
        # A started and rejected calibration must not leave a private
        # microphone buffer waiting for its independent expiry timer.
        assert [call[0].split("/")[-1] for call in http.calls] == [
            "audio.reference", "audio.capture.start",
            "audio.capture.status", "audio.capture.raw",
            "audio.reference", "audio.capture.abort",
        ]


def test_sense_status_latches_speaker_activity_inside_pcm_window():
    """Source contract: status uses the completion edge, not a live counter."""
    root = SOURCE.parents[1] / "firmware/head"
    codec = (root / "sense/sense_reference_codec.cc").read_text()
    header = (root / "sense/sense_reference_codec.h").read_text()
    bridge = (root / "overlay/robot_bridge.cc").read_text()
    assert "bench_speaker_at_start_ = speaker_frames_accepted_;" in codec
    assert "const bool already_ready = bench_window_.ready();" in codec
    assert "if (!already_ready && bench_window_.ready())" in codec
    assert "speaker_frames_accepted_ > bench_speaker_at_start_" in codec
    assert "bench_window_.ready() && bench_speaker_activity_in_window_" in codec
    assert "bool speaker_activity_in_window;" in header
    assert '"speaker_activity_in_window"' in bridge
    assert "progress.speaker_activity_in_window" in bridge


def test_postcapture_i2s_output_cannot_qualify_silent_recording():
    """A late speaker write may advance lifetime counters, not the capture."""
    http = fake_read(speaker_in_window=False, final_speaker=8400)
    with pytest.raises(RuntimeError, match="in-window speaker activity"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )
    assert [call[0].split("/")[-1] for call in http.calls] == [
        "audio.reference", "audio.capture.start", "audio.capture.status",
        "audio.capture.abort",
    ]


def test_authenticated_head_pcm_delivers_one_bounded_private_wav_pair(tmp_path):
    http = fake_read()
    raw, report = capture.capture_head(
        http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
        clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
    )
    assert len(raw) == capture.BYTES == 256000
    assert [path.split("/")[-1] for path, *_ in http.calls] == [
        "audio.reference", "audio.capture.start",
        "audio.capture.status", "audio.capture.raw", "audio.reference",
    ]
    assert [method for _, method, *_ in http.calls] == [
        "GET", "POST", "GET", "GET", "GET",
    ]
    assert all(header == "Bearer " + "x" * 32 for _, _, header, _ in http.calls)
    assert report["frames"] == 64000 and report["boot"] == 7
    assert report["capture_generation"] == 1
    assert report["microphone_frames_read_delta"] == 64000
    assert report["speaker_frames_accepted_delta"] == 8200
    assert report["speaker_activity_not_acoustic_playback"] is True
    assert report["speaker_activity_in_window"] is True
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


@pytest.mark.parametrize("changes", [
    {"final_epoch": 4},
    {"final_muted": True},
    {"final_boot": 8},
])
def test_capture_rejects_boot_privacy_switch_during_download(changes):
    """The final HTTP privacy receipt must fence raw WAV persistence."""
    http = fake_read(**changes)
    with pytest.raises(RuntimeError, match="privacy or boot changed"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )
    # The post-download privacy receipt runs before error cleanup aborts
    # this exact private capture generation.
    assert http.calls[-2][0].endswith("/api/audio.reference")
    assert http.calls[-1][0].endswith("/api/audio.capture.abort")


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


@pytest.mark.parametrize("delay_ms", [None, 90, 250, True, "0"])
def test_capture_requires_actual_zero_delay_on_authenticated_firmware(delay_ms):
    http = fake_read(delay_ms=delay_ms)
    with pytest.raises(ValueError, match="AEC delay 0 ms"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
        )
    # Refuse before starting any microphone recording.
    assert [request[0].split("/")[-1] for request in http.calls] == [
        "audio.reference",
    ]


@pytest.mark.parametrize("final_generation", ["2", "0", "invalid"])
def test_completed_pcm_rejects_generation_reset_after_raw_transfer(final_generation):
    """A post-transfer speaker reset invalidates A2 samples before WAV save."""
    http = fake_read(final_generation=final_generation)
    with pytest.raises((RuntimeError, ValueError), match="generation"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )
    assert http.calls[-2][0].endswith("/api/audio.reference")
    assert http.calls[-1][0].endswith("/api/audio.capture.abort")


def test_capture_refuses_device_microphone_mute_before_start():
    http = fake_read(mic_muted=True)
    with pytest.raises(ValueError, match="not eligible"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
        )
    assert len(http.calls) == 1


@pytest.mark.parametrize("last_us", [4800000, 5081000, 5500000])
def test_full_pcm_payload_still_requires_continuous_device_sample_timestamps(last_us):
    # Four seconds of bytes alone are not evidence of four seconds of audio.
    http = fake_read(last_us=last_us)
    with pytest.raises(RuntimeError, match="capture timestamps inconsistent"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )
    assert [req[0].split("/")[-1] for req in http.calls] == [
        "audio.reference", "audio.capture.start",
        "audio.capture.status", "audio.capture.raw",
        "audio.capture.abort",
    ]


@pytest.mark.parametrize("override", [
    {"start_generation": "0"},
    {"start_generation": "bad"},
    {"status_generation": "2"},
    {"raw_generation": "2"},
])
def test_capture_rejects_stale_or_invalid_generation(override):
    http = fake_read(**override)
    with pytest.raises((RuntimeError, ValueError), match="generation|inconsistent"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )


def test_partial_pcm_failure_aborts_its_generation():
    """No orphaned private mic buffer after an invalid raw body."""
    http = fake_read(raw=b"short", start_generation="17",
                     status_generation="17", raw_generation="17")
    original = http.open
    aborted = []

    def open_request(request, timeout):
        if request.full_url.endswith("/api/audio.capture.abort"):
            aborted.append((
                request.get_method(),
                request.get_header("X-desk-audio-generation"),
                timeout,
            ))
            return Response({
                "ok": True, "robot_id": "robot-01",
                "reply": "Private bench PCM capture aborted",
            })
        return original(request, timeout)

    http.open = open_request
    with pytest.raises(ValueError, match="Incomplete or oversized"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )
    assert aborted == [("POST", "17", 2.0)]


def test_operator_keyboard_interrupt_aborts_same_private_capture():
    """Physical head cleanup still gets a chance on Ctrl+C, not on GC."""
    http = fake_read(start_generation="42")
    original = http.open
    aborted = []

    def open_request(request, timeout):
        if request.full_url.endswith("/api/audio.capture.status"):
            raise KeyboardInterrupt
        if request.full_url.endswith("/api/audio.capture.abort"):
            aborted.append(request.get_header("X-desk-audio-generation"))
            return Response({
                "ok": True, "robot_id": "robot-01",
                "reply": "Private bench PCM capture aborted",
            })
        return original(request, timeout)

    http.open = open_request
    with pytest.raises(KeyboardInterrupt):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )
    assert aborted == ["42"]


@pytest.mark.parametrize("response", [
    {"ok": True, "robot_id": "robot-02", "reply": "Private bench PCM capture aborted"},
    {"ok": True, "reply": "Private bench PCM capture aborted"},
])
def test_abort_ack_cannot_claim_another_pet_or_missing_identity(response):
    """A foreign head ACK cannot prove this robot's private buffer wiped."""
    class AbortHTTP:
        def open(self, request, timeout):
            assert request.full_url.endswith("/api/audio.capture.abort")
            assert request.get_header("X-desk-audio-generation") == "42"
            return Response(response)

    with pytest.raises(RuntimeError, match="identity unconfirmed"):
        capture._abort_capture(
            AbortHTTP(), "http://192.168.1.23:8081",
            "x" * 32, "robot-01", 42,
        )


def test_disk_write_privacy_recheck_removes_private_wavs(tmp_path):
    """A BOOT mute during disk serialization must retract all output files."""
    raw = struct.pack("<hh", 12, -10) * capture.FRAMES
    output = tmp_path / "trial"
    watched = []

    def revoked_after_write():
        watched.append(sorted(path.name for path in output.iterdir()))
        raise RuntimeError("Sense microphone privacy changed before WAV publication")

    with pytest.raises(RuntimeError, match="privacy changed"):
        capture.save_wavs(
            output, raw, {"robot_id": "robot-01"},
            verify_before_publish=revoked_after_write,
        )
    assert watched == [["capture.json", "microphone.wav", "speaker_reference.wav"]]
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("state", [
    {"robot_id": "robot-02", "boot": 7,
     "microphone_privacy_epoch": 3, "capture_generation": "4",
     "microphone_privacy_muted": False, "reference_integrity_failed": False},
    {"robot_id": "robot-01", "boot": 7,
     "microphone_privacy_epoch": 4, "capture_generation": "4",
     "microphone_privacy_muted": False, "reference_integrity_failed": False},
    {"robot_id": "robot-01", "boot": 7,
     "microphone_privacy_epoch": 3, "capture_generation": "4",
     "microphone_privacy_muted": True, "reference_integrity_failed": False},
])
def test_postwrite_head_receipt_rejects_foreign_or_revoked_privacy(state):
    class Head:
        def open(self, request, timeout):
            assert request.full_url.endswith("/api/audio.reference")
            return Response(state)

    with pytest.raises(RuntimeError, match="privacy changed"):
        capture.verify_postwrite_privacy(
            Head(), "http://192.168.1.23:8081", "x" * 32,
            {"robot_id": "robot-01", "boot": 7,
             "microphone_privacy_epoch": 3, "capture_generation": 4},
        )


def test_voice_acceptance_research_no_longer_prescribes_90ms_capture():
    """The builder must not substitute a historical unmeasured lag as fact."""
    note = (
        SOURCE.parents[2] / "docs/research/2026-11-10-natural-voice-acceptance.md"
    ).read_text()
    assert "code/scripts/capture_sense_aec.py" in note
    assert "CONFIG_DESK_ROBOT_AEC_DELAY_MS=0" in note
    assert "docs/guides/sense-aec-port.md" in note
    assert "provisional 90ms" not in note
    assert "physical acceptance" in note


def test_audio_capture_abort_is_guarded_and_generation_scoped_in_sense_firmware():
    bridge = (SOURCE.parents[1] / "firmware/head/overlay/robot_bridge.cc").read_text()
    assert '"/api/audio.capture.abort", HTTP_POST' in bridge
    assert 'strcmp(req->uri, "/api/audio.capture.abort") == 0' in bridge
    assert '"X-Desk-Audio-Generation", supplied' in bridge
    assert 'strcmp(expected, supplied) != 0' in bridge
    assert 'codec->AbortBenchPcmCapture();' in bridge
    assert 'config.max_uri_handlers = 14;' in bridge


def test_audio_builder_guide_points_to_live_capture_without_claiming_qualification():
    """A first-unit builder must not follow the superseded no-capture advice."""
    guide = (SOURCE.parents[2] / "docs/guides/audio-barge-in.md").read_text()
    assert "code/scripts/capture_sense_aec.py" in guide
    assert "code/firmware/head/sense/sense_reference_codec.cc" in guide
    assert "still-open physical PCM capture path" not in guide
    assert "actual paired-sample adapter remains to implement" not in guide
    assert "no 20-trial physical acceptance is claimed" in guide


@pytest.mark.parametrize("mic_silent,ref_silent", [
    (True, False), (False, True), (True, True),
])
def test_mac_rejects_silent_pcm_even_when_head_counters_claim_activity(
    mic_silent, ref_silent,
):
    raw = struct.pack(
        "<hh", 0 if mic_silent else 123, 0 if ref_silent else -456,
    ) * capture.FRAMES
    http = fake_read(raw=raw)
    with pytest.raises(ValueError, match="all-zero microphone or reference"):
        capture.capture_head(
            http, "http://192.168.1.23:8081", "robot-01", "x" * 32,
            clock=iter([0.0, 0.1]).__next__, pause=lambda _: None,
        )


def test_consent_audio_capture_compiled_off_by_default():
    root = SOURCE.parents[1]
    head = (root / "firmware/head/sense/sense_reference_codec.h").read_text()
    bridge = (root / "firmware/head/overlay/robot_bridge.cc").read_text()
    assert "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED" in head
    assert "static_assert(kDelaySamples == 0" in head
    assert '"aec_delay_config_ms"' in bridge
    assert "CONFIG_DESK_ROBOT_AEC_DELAY_MS" in bridge
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
            headers = email.message.Message()
            headers["Location"] = "https://example.invalid/steal-bearer"
            response = urllib.response.addinfourl(
                io.BytesIO(b""), headers, request.full_url, code=302,
            )
            response.msg = "Found"
            return response

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

def test_private_aec_capture_rejects_directory_symlink_swap_during_wav_write(
    tmp_path, monkeypatch,
):
    """An attacker cannot redirect raw microphone PCM after preflight.

    The file descriptor anchors all writes and cleanup to the original
    private directory, even when its pathname is replaced with a symlink.
    """
    private = tmp_path / "private"
    outside = tmp_path / "public"
    retired = tmp_path / "retired"
    private.mkdir(mode=0o700)
    outside.mkdir(mode=0o755)
    original_create = capture._create_private
    swapped = False

    def replace_private_path(path, *, directory_fd=None):
        nonlocal swapped
        if not swapped:
            assert directory_fd is not None
            private.rename(retired)
            private.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_create(path, directory_fd=directory_fd)

    monkeypatch.setattr(capture, "_create_private", replace_private_path)
    with pytest.raises(ValueError, match="directory changed during write"):
        capture.save_wavs(
            private, bytes(capture.BYTES), {"robot_id": "robot-01"},
        )
    assert swapped
    assert list(outside.iterdir()) == []
    assert list(retired.iterdir()) == []


def test_private_aec_capture_rejects_another_private_inode_after_preflight(
    tmp_path, monkeypatch,
):
    """A replacement 0700 directory is not the originally authorized output."""
    private = tmp_path / "private"
    moved = tmp_path / "moved"
    private.mkdir(mode=0o700)
    original_preflight = capture.preflight_private_destination

    def replace_after_preflight(directory):
        identity = original_preflight(directory)
        private.rename(moved)
        private.mkdir(mode=0o700)
        return identity

    monkeypatch.setattr(
        capture, "preflight_private_destination", replace_after_preflight,
    )
    with pytest.raises(ValueError, match="directory changed during write"):
        capture.save_wavs(
            private, bytes(capture.BYTES), {"robot_id": "robot-01"},
        )
    assert list(private.iterdir()) == []
    assert list(moved.iterdir()) == []


def test_private_aec_capture_rechecks_directory_approved_before_head_transfer(tmp_path):
    """A path retargeted during the four-second recording cannot receive PCM."""
    private = tmp_path / "private"
    moved = tmp_path / "moved"
    approved = capture.preflight_private_destination(private)
    private.rename(moved)
    private.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="directory changed during write"):
        capture.save_wavs(
            private, bytes(capture.BYTES), {"robot_id": "robot-01"},
            expected_directory_identity=approved,
        )
    assert list(private.iterdir()) == []
    assert list(moved.iterdir()) == []


def test_destination_preflight_rejects_existing_audio_and_public_directory(tmp_path):
    private = tmp_path / "private"
    capture.preflight_private_destination(private)
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    (private / "microphone.wav").write_bytes(b"existing private audio")
    with pytest.raises(FileExistsError):
        capture.preflight_private_destination(private)
    assert (private / "microphone.wav").read_bytes() == b"existing private audio"

    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(ValueError, match="private mode"):
        capture.preflight_private_destination(public)


def test_cli_refuses_unwritable_destination_before_audio_capture(
    tmp_path, monkeypatch,
):
    import sys

    folder = tmp_path / "recordings"
    folder.mkdir(mode=0o700)
    (folder / "speaker_reference.wav").write_bytes(b"previous sample")
    monkeypatch.setenv("DESK_CAPTURE_TOKEN", "x" * 32)
    monkeypatch.setattr(sys, "argv", [
        "capture_sense_aec.py", "--head-url", "http://192.168.1.23:8081",
        "--robot-id", "robot-01", "--token-env", "DESK_CAPTURE_TOKEN",
        "--output-dir", str(folder), "--i-consent-to-private-raw-audio",
    ])

    def forbidden_capture(*args, **kwargs):
        raise AssertionError("Never start a microphone capture for unusable output")
    monkeypatch.setattr(capture, "capture_head", forbidden_capture)
    with pytest.raises(FileExistsError):
        capture.main()
    assert (folder / "speaker_reference.wav").read_bytes() == b"previous sample"
