"""Bounded, opt-in UDP PCM capture for the pinned XiaoZhi debug sender.

UDP source filtering is not authentication. Use an isolated bench network.
"""

import argparse
import ipaddress
import os
import socket
import time
import wave
from pathlib import Path


def capture(bind, peer, port, samplerate, channels, duration, output):
    bind = str(ipaddress.IPv4Address(bind))
    peer = str(ipaddress.IPv4Address(peer))
    if bind == "0.0.0.0" or peer == "0.0.0.0":
        raise ValueError("explicit bench and sender IPv4 addresses required")
    if not (1 <= port <= 65535 and 8000 <= samplerate <= 48000
            and channels in (1, 2) and 0 < duration <= 300):
        raise ValueError("invalid capture limits")
    frame_bytes = channels * 2
    remaining = int(samplerate * duration) * frame_bytes
    written = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind((bind, port))
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw, wave.open(raw, "wb") as wav:
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
                if address[0] != peer or not data or len(data) % frame_bytes:
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
    args = parser.parse_args()
    try:
        frames = capture(**vars(args))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Capture failed: {error}\n")
    print(f"Recorded {frames} PCM frames (UDP source is not authenticated)")


if __name__ == "__main__":
    main()
