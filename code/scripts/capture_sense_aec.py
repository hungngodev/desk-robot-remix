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
            or pre.get("speaker_playback_verified") is not False
            or pre.get("aec_physically_qualified") is not False):
        raise ValueError("Sense reference stream not eligible for trial")
    boot = _number(pre.get("boot"), 0, 0xffffffff, "boot ID")
    started = _json_response(
        opener, base + "/api/audio.capture.start", token, method="POST",
    )
    if started.get("ok") is not True or started.get("robot_id") != robot_id:
        # The current Envelope returns robot_id for the authenticated head.
        # Do not retry: the first START may already own the private buffer.
        raise RuntimeError("Sense PCM START identity unconfirmed")
    end_by = clock() + 8.0
    previous = 0
    while clock() < end_by:
        data = _json_response(opener, base + "/api/audio.capture.status", token)
        count = _number(data.get("frames"), 0, FRAMES, "frame count")
        if (data.get("robot_id") != robot_id
                or _number(data.get("boot"), 0, 0xffffffff, "boot ID") != boot
                or type(data.get("active")) is not bool
                or type(data.get("ready")) is not bool
                or type(data.get("failed")) is not bool
                or data.get("physical_aec_qualified") is not False
                or count < previous):
            raise RuntimeError("Sense PCM status changed identity or generation")
        if data["failed"]:
            raise RuntimeError("Sense reference sample gap invalidated trial")
        if data["ready"]:
            if count != FRAMES or data["active"]:
                raise RuntimeError("Sense ready state has wrong PCM length")
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
        frames = _number_header(response, "X-Desk-Audio-Frames", FRAMES, FRAMES)
        first = _number_header(response, "X-Desk-Audio-First-Us", 1, 2**63 - 1)
        last = _number_header(response, "X-Desk-Audio-Last-Us", 1, 2**63 - 1)
        if reported_boot != boot or not 3_500_000 <= last - first <= 4_500_000:
            raise RuntimeError("Sense PCM boot or capture timestamps inconsistent")
        raw = response.read(BYTES + 1)
    if len(raw) != BYTES:
        raise ValueError("Incomplete or oversized authenticated Sense PCM body")
    report = {
        "capture_source": "authenticated_sense_codec_private_pcm_window",
        "robot_id": robot_id,
        "boot": boot,
        "frames": frames,
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


def _number_header(response, name: str, low: int, high: int) -> int:
    value = response.headers.get(name)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
        raise ValueError("Invalid Sense PCM header: " + name)
    return _number(int(value), low, high, name)


def _create_private(path: Path):
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def save_wavs(directory: Path, raw: bytes, report: dict) -> None:
    mic, ref = split_pcm(raw)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise ValueError("AEC capture directory must be private mode 0700")
    paths = [directory / "microphone.wav", directory / "speaker_reference.wav",
             directory / "capture.json"]
    if any(p.exists() or p.is_symlink() for p in paths):
        raise FileExistsError("Private audio trial files already exist")
    written = []
    try:
        for path, pcm in zip(paths[:2], (mic, ref), strict=True):
            with _create_private(path) as out:
                written.append(path)
                with wave.open(out, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(RATE)
                    wav.writeframes(pcm)
        with _create_private(paths[2]) as out:
            written.append(paths[2])
            out.write((json.dumps(report, sort_keys=True, indent=2) + "\n").encode())
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise


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
    # Disable proxies AND redirects. urllib's default redirect handler can
    # carry Authorization from a private robot URL to an unrelated origin.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    raw, report = capture_head(
        opener, args.head_url, args.robot_id, token,
    )
    save_wavs(args.output_dir, raw, report)
    print(json.dumps({
        "frames": report["frames"],
        "files": ["microphone.wav", "speaker_reference.wav", "capture.json"],
        "aec_physically_qualified": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
