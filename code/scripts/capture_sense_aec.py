"""Private one-shot MIC/REFERENCE capture from the selected Sense Xiaozhi codec.

Reuse ONLY the existing authenticated XIAO bridge and PCM read callback.
The firmware bench endpoint is explicitly disabled in production and requires
CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED with AEC delay set to zero.
This is a software calibration input, never audible speaker proof.
"""
from __future__ import annotations

import argparse
import array
import ipaddress
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

RATE = 16_000
FRAMES = 4 * RATE
BYTES = FRAMES * 2 * 2
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(item) for item in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a head HTTP redirect with an authenticated device bearer."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            request.full_url, code, "Sense capture redirect refused",
            headers, fp,
        )


def head_address(url: str) -> str:
    """Never send a private device bearer or raw mic data to a public/proxy URL."""
    if not isinstance(url, str) or len(url) > 120:
        raise ValueError("Invalid Sense head URL")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "http" or parsed.username is not None
            or parsed.password is not None or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or parsed.port != 8081):
        raise ValueError("Expected exact private http://HEAD_IP:8081 URL")
    address = ipaddress.IPv4Address(parsed.hostname or "")
    if not any(address in subnet for subnet in PRIVATE_NETWORKS):
        raise ValueError("Sense bridge must use a specific private IPv4 address")
    return f"http://{address}:8081"


def split_pcm(raw: bytes) -> tuple[bytes, bytes]:
    if type(raw) is not bytes or len(raw) != BYTES:
        raise ValueError("Incomplete 4-second Sense MIC/REFERENCE capture")
    values = array.array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    mic = array.array("h", values[0::2])
    ref = array.array("h", values[1::2])
    if sys.byteorder != "little":
        mic.byteswap()
        ref.byteswap()
    return mic.tobytes(), ref.tobytes()


def _number(value, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Malformed Sense {name}")
    return value


def _json_response(opener, url: str, token: str, *, method: str = "GET") -> dict:
    request = urllib.request.Request(
        url, method=method, data=b"" if method == "POST" else None,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    with opener.open(request, timeout=2.0) as response:
        if response.status not in (200, 202):
            raise ValueError("Sense capture request not accepted")
        raw = response.read(8193)
    if len(raw) > 8192:
        raise ValueError("Oversized Sense capture status")
    data = json.loads(raw)
    if type(data) is not dict:
        raise ValueError("Malformed Sense capture status")
    return data


def capture_head(opener, head_url: str, robot_id: str, token: str, *,
                 clock=time.monotonic, pause=time.sleep) -> tuple[bytes, dict]:
    """One authenticated capture. No retries of an uncertain START request."""
    if not isinstance(robot_id, str) or re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", robot_id) is None:
        raise ValueError("Invalid expected Sense robot ID")
    if not isinstance(token, str) or len(token) < 24 or len(token) > 120:
        raise ValueError("Invalid private device token")
    base = head_address(head_url)
    pre = _json_response(opener, base + "/api/audio.reference", token)
    if (pre.get("robot_id") != robot_id
            or pre.get("reference_integrity_failed") is not False
            or pre.get("microphone_privacy_muted") is not False
            or pre.get("speaker_playback_verified") is not False
            or pre.get("aec_physically_qualified") is not False):
        raise ValueError("Sense reference stream not eligible for trial")
    boot = _number(pre.get("boot"), 0, 0xffffffff, "boot ID")
    privacy_epoch = _number(
        pre.get("microphone_privacy_epoch"), 0, 0xffffffff,
        "microphone privacy epoch",
    )
    # Count only actual successful PDM reads and accepted I2S frames.
    # These are activity witnesses, never acoustic speaker playback proof.
    initial_mic_frames = _number(
        pre.get("microphone_frames_read"), 0, 0xffffffff,
        "initial microphone frame count",
    )
    initial_speaker_frames = _number(
        pre.get("speaker_frames_accepted"), 0, 0xffffffff,
        "initial speaker frame count",
    )
    if (initial_mic_frames > 0xffffffff - FRAMES
            or initial_speaker_frames == 0xffffffff):
        raise ValueError("Sense activity counters saturated before trial")
    # A genuine bench build statically enforces zero delay. Verify the live
    # flashed head too; older/misconfigured diagnostics must not masquerade as
    # an absolute speaker-to-microphone acoustic measurement.
    if type(pre.get("aec_delay_config_ms")) is not int or pre["aec_delay_config_ms"] != 0:
        raise ValueError("Sense calibration requires verified firmware AEC delay 0 ms")
    started = _json_response(
        opener, base + "/api/audio.capture.start", token, method="POST",
    )
    if (started.get("ok") is not True or started.get("robot_id") != robot_id
            or started.get("boot") != boot):
        # The current Envelope returns robot_id for the authenticated head.
        # Do not retry: the first START may already own the private buffer.
        raise RuntimeError("Sense PCM START identity unconfirmed")
    generation = _generation(started.get("capture_generation"))
    try:
        end_by = clock() + 8.0
        previous = 0
        while clock() < end_by:
            data = _json_response(opener, base + "/api/audio.capture.status", token)
            count = _number(data.get("frames"), 0, FRAMES, "frame count")
            if (data.get("robot_id") != robot_id
                    or _number(data.get("boot"), 0, 0xffffffff, "boot ID") != boot
                    or _generation(data.get("capture_generation")) != generation
                    or type(data.get("active")) is not bool
                    or type(data.get("ready")) is not bool
                    or type(data.get("failed")) is not bool
                    or type(data.get("speaker_activity_in_window")) is not bool
                    or data.get("physical_aec_qualified") is not False
                    or count < previous):
                raise RuntimeError("Sense PCM status changed identity or generation")
            if data["failed"]:
                raise RuntimeError("Sense reference sample gap invalidated trial")
            if data["ready"]:
                if count != FRAMES or data["active"]:
                    raise RuntimeError("Sense ready state has wrong PCM length")
                if not data["speaker_activity_in_window"]:
                    raise RuntimeError("Sense capture lacks in-window speaker activity")
                break
            if not data["active"] or count == FRAMES:
                raise RuntimeError("Sense PCM capture ended without complete result")
            previous = count
            pause(0.1)
        else:
            raise RuntimeError("Timed out waiting for complete Sense PCM")
        request = urllib.request.Request(
            base + "/api/audio.capture.raw",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/octet-stream"},
        )
        with opener.open(request, timeout=6.0) as response:
            if (response.status != 200
                    or response.headers.get("Content-Type") != "application/octet-stream"
                    or response.headers.get("X-Desk-Audio-Robot-Id") != robot_id):
                raise ValueError("Wrong raw PCM content type or robot identity")
            reported_boot = _number_header(response, "X-Desk-Audio-Boot", 0, 0xffffffff)
            reported_generation = _number_header(
                response, "X-Desk-Audio-Generation", 1, 2**64 - 1,
            )
            frames = _number_header(response, "X-Desk-Audio-Frames", FRAMES, FRAMES)
            first = _number_header(response, "X-Desk-Audio-First-Us", 1, 2**63 - 1)
            last = _number_header(response, "X-Desk-Audio-Last-Us", 1, 2**63 - 1)
            # A correctly counted PCM window with a large clock gap still
            # corrupts absolute acoustic lag. Match the Sense window's bounded
            # 80 ms accumulated timing tolerance, including older bench builds.
            if (reported_boot != boot or reported_generation != generation
                    or not 3_920_000 <= last - first <= 4_080_000):
                raise RuntimeError("Sense PCM boot or capture timestamps inconsistent")
            raw = response.read(BYTES + 1)
        if len(raw) != BYTES:
            raise ValueError("Incomplete or oversized authenticated Sense PCM body")
        # Protect against an older or misconfigured bench image: driver
        # activity counters do not establish a usable nonzero PCM signal.
        microphone_pcm, reference_pcm = split_pcm(raw)
        if not any(microphone_pcm) or not any(reference_pcm):
            raise ValueError("Sense PCM capture has an all-zero microphone or reference")
        # The BOOT privacy switch can change while the HTTP worker transfers
        # buffered audio. Reject an otherwise complete capture if that happened,
        # even though the head must independently invalidate mid-flight chunks.
        # This final authenticated receipt fences the file write on the Mac.
        final = _json_response(opener, base + "/api/audio.reference", token)
        if (final.get("robot_id") != robot_id
                or _number(final.get("boot"), 0, 0xffffffff, "boot ID") != boot
                or _number(final.get("microphone_privacy_epoch"), 0, 0xffffffff,
                           "microphone privacy epoch") != privacy_epoch
                or _generation(final.get("capture_generation")) != generation
                or final.get("microphone_privacy_muted") is not False
                or final.get("reference_integrity_failed") is not False):
            raise RuntimeError(
                "Sense microphone privacy or boot changed during capture or generation reset"
            )
        mic_frames_after = _number(
            final.get("microphone_frames_read"), 0, 0xffffffff,
            "final microphone frame count",
        )
        speaker_frames_after = _number(
            final.get("speaker_frames_accepted"), 0, 0xffffffff,
            "final speaker frame count",
        )
        if (mic_frames_after - initial_mic_frames < FRAMES
                or speaker_frames_after <= initial_speaker_frames):
            raise RuntimeError("Sense PCM trial has no complete microphone or speaker activity")
        report = {
            "capture_source": "authenticated_sense_codec_private_pcm_window",
            "robot_id": robot_id,
            "boot": boot,
            "microphone_privacy_epoch": privacy_epoch,
            "capture_generation": generation,
            "frames": frames,
            "microphone_frames_read_delta": mic_frames_after - initial_mic_frames,
            "speaker_frames_accepted_delta": speaker_frames_after - initial_speaker_frames,
            "speaker_activity_in_window": True,
            "speaker_activity_not_acoustic_playback": True,
            "sample_rate_hz": RATE,
            "first_sample_us": first,
            "last_sample_us": last,
            "head_bearer_response_checked": True,
            "source_device_physically_authenticated": False,
            "physical_speaker_playback_verified": False,
            "aec_physically_qualified": False,
            "acoustic_delay_measured": False,
        }
        return raw, report
    except BaseException:
        # Ctrl+C, network failure, malformed receipt, or a revoked BOOT
        # consent must not retain an orphaned 256 KiB private PCM window.
        # This best-effort device abort is scoped to the START generation:
        # it must not destroy a later calibration trial.
        try:
            _abort_capture(opener, base, token, robot_id, generation)
        except Exception:
            pass  # The independent 12-second head expiry remains authoritative.
        raise


def _abort_capture(opener, base: str, token: str, robot_id: str,
                   generation: int) -> None:
    """Cancel only this authenticated bench generation after an exception."""
    request = urllib.request.Request(
        base + "/api/audio.capture.abort", data=b"", method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "X-Desk-Audio-Generation": str(generation),
            "Accept": "application/json",
        },
    )
    with opener.open(request, timeout=2.0) as response:
        if response.status != 200:
            raise RuntimeError("Sense PCM ABORT unconfirmed")
        result = json.loads(response.read(1024))
    if (type(result) is not dict or result.get("ok") is not True
            or result.get("robot_id") != robot_id
            or result.get("reply") != "Private bench PCM capture aborted"):
        raise RuntimeError("Sense PCM ABORT identity unconfirmed")


def _generation(value: object) -> int:
    """Reject stale or ambiguous capture IDs before saving private audio."""
    if type(value) is not str or re.fullmatch(r"[1-9][0-9]{0,19}", value) is None:
        raise ValueError("Invalid Sense PCM capture generation")
    return _number(int(value), 1, 2**64 - 1, "capture generation")


def _number_header(response, name: str, low: int, high: int) -> int:
    value = response.headers.get(name)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
        raise ValueError("Invalid Sense PCM header: " + name)
    return _number(int(value), low, high, name)


def _create_private(path: Path, *, directory_fd: int | None = None):
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    # Once a private destination is opened, never resolve its pathname again
    # for actual microphone PCM writes. Another local process may retarget it.
    target = path.name if directory_fd is not None else path
    return os.fdopen(os.open(target, flags, 0o600, dir_fd=directory_fd), "wb")


def _check_private_directory(
    directory: Path, directory_fd: int, expected_identity: tuple[int, int],
) -> None:
    """Reject a swapped recording path without following a replacement link."""
    owned = os.fstat(directory_fd)
    try:
        named = os.stat(directory, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ValueError("AEC capture directory changed during write") from exc
    if (not stat.S_ISDIR(owned.st_mode)
            or stat.S_IMODE(owned.st_mode) & 0o077
            or not stat.S_ISDIR(named.st_mode)
            or (owned.st_dev, owned.st_ino) != (named.st_dev, named.st_ino)
            or (owned.st_dev, owned.st_ino) != expected_identity):
        raise ValueError("AEC capture directory changed during write")


def _private_destination_directory_fd(directory: Path) -> int:
    """Anchor the raw PCM destination through trusted directory components.

    An immediate 0700 directory is not sufficient when a user-controlled
    ancestor link can redirect the entire four-second microphone recording.
    """
    absolute = Path(os.path.abspath(directory))
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            entry = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            owner = os.fstat(descriptor)
            # macOS /var is a root-owned system alias under a nonwritable
            # root directory. Reject every replaceable user-owned link.
            if stat.S_ISLNK(entry.st_mode) and (
                entry.st_uid != 0 or owner.st_uid != 0
                or stat.S_IMODE(owner.st_mode) & 0o022
            ):
                raise ValueError("AEC capture destination has unsafe ancestor symlink")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not stat.S_ISLNK(entry.st_mode):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        selected = os.fstat(descriptor)
        if not stat.S_ISDIR(selected.st_mode) or stat.S_IMODE(selected.st_mode) & 0o077:
            raise ValueError("AEC capture directory must be private mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def preflight_private_destination(directory: Path) -> tuple[int, int]:
    """Record the exact private directory approved before capturing audio.

    Retain its inode across the slow authenticated head transfer; an attacker
    cannot substitute another mode-0700 directory and receive the raw PCM.
    """
    if directory.is_symlink():
        raise ValueError("AEC capture destination has unsafe ancestor symlink")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = _private_destination_directory_fd(directory)
    try:
        identity = os.fstat(descriptor)
        paths = [directory / "microphone.wav", directory / "speaker_reference.wav",
                 directory / "capture.json"]
        if any(p.exists() or p.is_symlink() for p in paths):
            raise FileExistsError("Private audio trial files already exist")
        return identity.st_dev, identity.st_ino
    finally:
        os.close(descriptor)


def save_wavs(directory: Path, raw: bytes, report: dict, *,
              verify_before_publish=None,
              expected_directory_identity: tuple[int, int] | None = None) -> None:
    identity = preflight_private_destination(directory)
    if expected_directory_identity is not None and identity != expected_directory_identity:
        raise ValueError("AEC capture directory changed during write")
    mic, ref = split_pcm(raw)
    paths = [directory / "microphone.wav", directory / "speaker_reference.wav",
             directory / "capture.json"]
    # O_NOFOLLOW on individual WAV paths alone is insufficient: a local
    # process could swap the containing private directory for a symlink after
    # preflight. Anchor creation and cleanup to one verified directory inode.
    directory_fd = _private_destination_directory_fd(directory)
    written = []
    try:
        _check_private_directory(directory, directory_fd, identity)
        for path, pcm in zip(paths[:2], (mic, ref), strict=True):
            with _create_private(path, directory_fd=directory_fd) as out:
                written.append(path.name)
                with wave.open(out, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(RATE)
                    wav.writeframes(pcm)
        with _create_private(paths[2], directory_fd=directory_fd) as out:
            written.append(paths[2].name)
            out.write((json.dumps(report, sort_keys=True, indent=2) + "\n").encode())
        # A BOOT mute during disk I/O invalidates even a validated HTTP
        # response. Recheck both device privacy and destination identity.
        if verify_before_publish is not None:
            verify_before_publish()
        _check_private_directory(directory, directory_fd, identity)
    except BaseException:
        # Do not unlink through the pathname if it was retargeted: that could
        # delete unrelated files and leave the original private PCM orphaned.
        for name in written:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(directory_fd)


def verify_postwrite_privacy(opener, head_url: str, token: str,
                             report: dict) -> None:
    """Reject a BOOT privacy change while the Mac was writing private WAVs."""
    fresh = _json_response(opener, head_address(head_url) + "/api/audio.reference", token)
    if (fresh.get("robot_id") != report["robot_id"]
            or _number(fresh.get("boot"), 0, 0xffffffff, "boot ID") != report["boot"]
            or _number(fresh.get("microphone_privacy_epoch"), 0, 0xffffffff,
                       "privacy epoch") != report["microphone_privacy_epoch"]
            or _generation(fresh.get("capture_generation")) != report["capture_generation"]
            or fresh.get("microphone_privacy_muted") is not False
            or fresh.get("reference_integrity_failed") is not False):
        raise RuntimeError("Sense microphone privacy changed before WAV publication")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head-url", required=True)
    parser.add_argument("--robot-id", required=True)
    parser.add_argument("--token-env", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--i-consent-to-private-raw-audio", action="store_true")
    args = parser.parse_args()
    if not args.i_consent_to_private_raw_audio:
        parser.error("Explicit operator microphone recording consent required")
    if re.fullmatch(r"[A-Z][A-Z0-9_]{4,80}", args.token_env) is None:
        parser.error("Expected private environment variable name")
    token = os.environ.get(args.token_env, "")
    if len(token) < 24:
        parser.error("Missing valid private device token")
    # No capture of private microphone PCM when the destination already fails.
    # This is a preflight only; save_wavs rechecks against concurrent changes.
    head_address(args.head_url)
    operator_directory_identity = preflight_private_destination(args.output_dir)
    # Disable proxies AND redirects. urllib's default redirect handler can
    # carry Authorization from a private robot URL to an unrelated origin.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    raw, report = capture_head(
        opener, args.head_url, args.robot_id, token,
    )
    save_wavs(
        args.output_dir, raw, report,
        expected_directory_identity=operator_directory_identity,
        verify_before_publish=lambda: verify_postwrite_privacy(
            opener, args.head_url, token, report,
        ),
    )
    print(json.dumps({
        "frames": report["frames"],
        "files": ["microphone.wav", "speaker_reference.wav", "capture.json"],
        "aec_physically_qualified": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
