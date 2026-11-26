"""Bounded, explicitly consented loopback UDP PCM capture for local tests.

UDP source filtering is not authentication. Physical Sense calibration uses
the authenticated one-shot capture instead.
"""

import argparse
import ipaddress
import os
import socket
import time
import wave
from pathlib import Path

REJECTED_DATAGRAM_BACKOFF = 0.001


def _private_opener(path, flags):
    return os.open(path, flags, 0o600)


def capture(
    bind: str | ipaddress.IPv4Address,
    peer: str | ipaddress.IPv4Address,
    port: int,
    samplerate: int,
    channels: int,
    duration: float,
    output: str | Path,
    *,
    consent: bool = False,
) -> int:
    if consent is not True:
        raise ValueError("explicit private raw audio consent required")
    bind = ipaddress.IPv4Address(bind)
    peer = ipaddress.IPv4Address(peer)
    if not bind.is_loopback or not peer.is_loopback:
        raise ValueError("legacy UDP capture requires loopback bind and peer addresses")
    bind, peer = str(bind), str(peer)
    if not (
        type(port) is int
        and type(samplerate) is int
        and type(channels) is int
        and type(duration) in (int, float)
        and 1 <= port <= 65535
        and 8000 <= samplerate <= 48000
        and channels in (1, 2)
        and 0 < duration <= 300
    ):
        raise ValueError("invalid capture limits")
    frame_bytes = channels * 2
    remaining = int(samplerate * duration) * frame_bytes
    if not remaining:
        raise ValueError("invalid capture limits: duration below one PCM frame")
    written = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind((bind, port))
        with open(output, "xb", opener=_private_opener) as raw, wave.open(raw, "wb") as wav:
            wav.setparams((channels, 2, samplerate, 0, "NONE", "not compressed"))
            deadline = time.monotonic() + duration
            while remaining:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                receiver.settimeout(timeout)
                try:
                    data, address = receiver.recvfrom(65535)
                except socket.timeout:
                    break
                # A receive may return after the deadline if the process was descheduled.
                received_at = time.monotonic()
                if received_at >= deadline:
                    break
                if address[0] != peer or not data or len(data) % frame_bytes:
                    # Bound rejected-packet processing without delaying valid PCM.
                    time.sleep(min(REJECTED_DATAGRAM_BACKOFF, deadline - received_at))
                    continue
                data = data[:remaining]
                wav.writeframesraw(data)
                remaining -= len(data)
                written += len(data)
    if not written:
        raise ValueError("no valid PCM received")
    return written // frame_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--peer", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--samplerate", "-s", type=int, default=16000)
    parser.add_argument("--channels", "-c", type=int, default=2)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--i-consent-to-private-raw-audio", dest="consent",
                        action="store_true", required=True)
    args = parser.parse_args()
    try:
        frames = capture(**vars(args))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Capture failed: {error}\n")
    print(f"Recorded {frames} PCM frames (UDP source is not authenticated)")


if __name__ == "__main__":
    main()
