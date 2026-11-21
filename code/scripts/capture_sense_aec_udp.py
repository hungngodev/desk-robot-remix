"""Opt-in bench capture of the EXISTING Xiaozhi Sense AEC input channels.

The pinned Xiaozhi AudioDebugger::Feed sends AudioService::ReadAudioData's
interleaved 16 kHz MIC,REFERENCE PCM16 over UDP when USE_AUDIO_DEBUGGER=y.
It is DISABLED by default and sends raw private audio without encryption or
authentication. Use only on an isolated trusted lab network with the owner's
explicit permission; disable/reflash immediately after measuring.

This does not detect UDP packet loss without sequence IDs, verify acoustic
speaker playback, or establish AEC calibration/physical qualification.
"""
from __future__ import annotations

import argparse
import array
import ipaddress
import json
import os
import socket
import stat
import sys
import time
import wave
from pathlib import Path

RATE = 16_000
MAX_DATAGRAM = 8192
MAX_OTHER_SOURCE = 32
LAB_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


def lab_ip(value: str) -> ipaddress.IPv4Address:
    """Never bind a raw-mic UDP listener to a wildcard or public address."""
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in LAB_NETWORKS):
        raise ValueError("Use a specific loopback or RFC1918 private IPv4")
    return address


def split_interleaved(raw: bytes) -> tuple[bytes, bytes]:
    """MIC at even indices, the original Sense codec AEC reference at odd."""
    if not isinstance(raw, bytes) or not raw or len(raw) % 4:
        raise ValueError("Expected complete stereo PCM16 microphone/reference frames")
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    mic = array.array("h", samples[0::2])
    reference = array.array("h", samples[1::2])
    if sys.byteorder != "little":
        mic.byteswap()
        reference.byteswap()
    return mic.tobytes(), reference.tobytes()


def receive_capture(sock: socket.socket, *, expected_source_ip: str,
                    duration_s: int = 5, max_gap_ms: int = 150,
                    clock=time.monotonic) -> tuple[bytes, dict]:
    """Receive one bounded interleaved buffer without ever logging PCM."""
    lab_ip(expected_source_ip)
    if (type(duration_s) is not int or not 5 <= duration_s <= 10
            or type(max_gap_ms) is not int or not 40 <= max_gap_ms <= 500):
        raise ValueError("Bench duration or packet gap outside safe bounds")
    target = duration_s * RATE * 4
    recorded = bytearray()
    accepted = 0
    foreign = 0
    previous_at = None
    began_at = None
    while len(recorded) < target:
        try:
            packet, address = sock.recvfrom(MAX_DATAGRAM + 1)
        except socket.timeout as exc:
            raise RuntimeError("Sense AEC UDP feed stopped; no complete recording") from exc
        if not isinstance(address, tuple) or address[0] != expected_source_ip:
            foreign += 1
            if foreign > MAX_OTHER_SOURCE:
                raise RuntimeError("Too many foreign audio packets")
            continue
        now = clock()
        if (previous_at is not None
                and (now < previous_at or (now - previous_at) * 1000 > max_gap_ms)):
            raise RuntimeError("Audio packet gap or clock anomaly; discard capture")
        if not isinstance(packet, bytes) or not 4 <= len(packet) <= MAX_DATAGRAM or len(packet) % 4:
            raise RuntimeError("Truncated, oversized or misaligned Sense PCM packet")
        if began_at is None:
            began_at = now
        previous_at = now
        recorded.extend(packet[:target - len(recorded)])
        accepted += 1
    # The channels share sample positions but UDP has no packet sequence, so
    # packet omission/reordering remains physically UNVERIFIED.
    return bytes(recorded), {
        "frames": len(recorded) // 4,
        "sample_rate_hz": RATE,
        "packets_accepted": accepted,
        "foreign_packets_ignored": foreign,
        "capture_source": "pinned_xiaozhi_audio_debugger_udp_mic_reference",
        "same_codec_read_channel_alignment": True,
        "udp_packet_loss_proven_absent": False,
        "source_device_authenticated": False,
        "physical_playback_verified": False,
        "aec_physically_qualified": False,
        "clock_drift_verified": False,
    }


def _private_file(path: Path):
    # Exclusive create: no replacement, symlink follow, shared temp file or
    # accidental copying into a permissive preexisting report directory.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def write_capture(output_dir: Path, raw: bytes, report: dict) -> None:
    """Write two truly aligned private WAVs, or delete all partial output."""
    if not isinstance(output_dir, Path):
        raise ValueError("Output directory required")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (output_dir.is_symlink() or
            stat.S_IMODE(output_dir.stat().st_mode) & 0o077):
        raise ValueError("AEC output directory must be private (mode 0700)")
    mic, reference = split_interleaved(raw)
    files = (output_dir / "microphone.wav", output_dir / "speaker_reference.wav",
             output_dir / "capture.json")
    if any(path.exists() or path.is_symlink() for path in files):
        raise FileExistsError("Bench capture files already exist; no overwrites")
    created = []
    try:
        for path, payload in zip(files[:2], (mic, reference), strict=True):
            with _private_file(path) as fp:
                created.append(path)
                with wave.open(fp, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(RATE)
                    wav.writeframes(payload)
        with _private_file(files[2]) as fp:
            created.append(files[2])
            fp.write((json.dumps(report, sort_keys=True, indent=2) + "\n").encode())
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind-ip", required=True,
                        help="Mac's private lab IPv4 interface, not a public internet interface")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--expected-source-ip", required=True,
                        help="Actual XIAO Sense IPv4; IP matching is not device authentication")
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--i-consent-to-private-raw-audio", action="store_true")
    args = parser.parse_args()
    if not args.i_consent_to_private_raw_audio:
        parser.error("Raw microphone capture requires explicit operator consent")
    if not 1024 <= args.port <= 65535:
        parser.error("Unprivileged UDP port required")
    try:
        lab_ip(args.bind_ip)
        lab_ip(args.expected_source_ip)
    except ValueError as exc:
        parser.error(str(exc))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.bind_ip, args.port))
        sock.settimeout(1.0)
        raw, report = receive_capture(
            sock, expected_source_ip=args.expected_source_ip,
            duration_s=args.duration,
        )
    write_capture(args.output_dir, raw, report)
    print(json.dumps({
        "frames": report["frames"],
        "files_created": ["microphone.wav", "speaker_reference.wav", "capture.json"],
        "physical_aec_qualified": False,
        "source_device_authenticated": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
