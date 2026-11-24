#!/usr/bin/env python3
"""Experimental native MiniCPM-o duplex backend smoke test, NO robot speaker.

Exercise the published vLLM-Omni /v1/realtime?duplex=1 protocol with a REAL
16kHz mono WAV and optional JPEG. The output is a 24kHz WAV file for offline
review, not an acoustic playback ACK or head integration. No motor permissions.
The backend must already be running in a supported execution environment.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from desk_robot.realtime_omni_protocol import OmniDuplexWire, verify_native_server


def server_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in ("ws", "wss")
            or parsed.username or parsed.password
            or parsed.fragment
            or parsed.path != "/v1/realtime"
            or parsed.query != "duplex=1" or not parsed.hostname):
        raise ValueError("Require a vLLM Omni /v1/realtime?duplex=1 WebSocket")
    if parsed.scheme == "ws":
        try:
            if not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise ValueError("Remote native audio requires encrypted wss://")
        except ValueError as exc:
            if parsed.hostname not in ("localhost",):
                raise ValueError("Use localhost or TLS for native voice") from exc
    return url


def validate_pcm(pcm: bytes) -> None:
    if (not isinstance(pcm, bytes) or not 0 < len(pcm) <= 32000 * 60
            or len(pcm) % 2):
        raise ValueError("Input must contain nonempty <=60s complete PCM16 samples")


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        if (wav.getnchannels() != 1 or wav.getsampwidth() != 2
                or wav.getframerate() != 16000
                or not 0 < frames <= 16000 * 60):
            raise ValueError("Input must be <=60s mono 16kHz PCM16 WAV")
        pcm = wav.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError("Truncated PCM16 WAV data")
        validate_pcm(pcm)
        return pcm


def validate_jpeg(jpeg: bytes) -> None:
    if (not isinstance(jpeg, bytes) or not 10 <= len(jpeg) <= 1_000_000
            or not jpeg.startswith(b"\xff\xd8")
            or not jpeg.endswith(b"\xff\xd9")):
        raise ValueError("A complete <=1MB JPEG image is required")


def read_jpeg(path: Path | None) -> bytes | None:
    if path is None:
        return None
    with path.open("rb") as stream:
        jpeg = stream.read(1_000_001)
    validate_jpeg(jpeg)
    return jpeg


async def probe(url: str, model: str, pcm: bytes, jpeg: bytes | None,
                *, deadline: float,
                barrier: asyncio.Barrier | None = None,
                quiet_input: bool = False) -> tuple[bytes, dict]:
    if not 5 <= deadline <= 180:
        raise ValueError("Probe deadline must be between 5 and 180 seconds")
    if type(quiet_input) is not bool:
        raise ValueError("Quiet input must be an explicit boolean")
    validate_pcm(pcm)
    if jpeg is not None:
        validate_jpeg(jpeg)
    wire = OmniDuplexWire(model=model)
    output = bytearray()
    transcript = []
    results = {
        "native_backend_protocol_only": True,
        "head_speaker_connected": False,
        "audible_stop_verified": False,
        "actual_playback_acknowledged": False,
        "motion_authorized": False,
    }
    first_audio_at = None
    input_appends_after_first_audio = 0
    model_decision = None
    started_at = time.monotonic()
    # This is a prerecorded operator-supplied test JPEG, NOT a live
    # XIAO exposure timestamp. Use its one local receipt identity for the
    # entire probe so the real wire never duplicates a single test frame.
    test_frame_receipt_us = time.monotonic_ns() // 1000 if jpeg else None
    # The model only receives an attached JPEG on a completed 1 s audio
    # unit. Reject too-short AV probes instead of silently testing audio
    # alone while reporting that a frame was provided.
    if jpeg is not None and len(pcm) < 32000:
        raise ValueError("Audiovisual probe requires at least one second of PCM")

    # A single communication budget covers connection, negotiation, fleet
    # admission, paced input, and the terminal model decision.
    async with asyncio.timeout(deadline) as budget, aiohttp.ClientSession() as client:
        async with client.ws_connect(
            server_url(url), heartbeat=20, max_msg_size=2_000_000,
            timeout=aiohttp.ClientWSTimeout(ws_close=1.0),
        ) as socket:
            await socket.send_json(wire.session_update())
            greeting = await socket.receive_json(timeout=10)
            verify_native_server(greeting, wire.model)
            wire.handle_event(greeting)
            if barrier is not None:
                # Hold every authenticated backend session open BEFORE
                # sending a single audio unit. Serial one-at-a-time probes
                # cannot qualify a five-pet session admission ceiling.
                await asyncio.wait_for(
                    barrier.wait(), timeout=min(10.0, deadline),
                )

            async def reader():
                nonlocal first_audio_at, model_decision, input_appends_after_first_audio
                async for msg in socket:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        raise RuntimeError("Non-JSON response from native backend")
                    event = json.loads(msg.data)
                    previous_response = wire.response_id
                    packet = wire.handle_event(event)
                    if wire.response_id != previous_response:
                        # The output file must contain one completed response,
                        # not partial PCM from a superseded response.
                        output.clear()
                        transcript.clear()
                        first_audio_at = None
                        input_appends_after_first_audio = 0
                    if (event.get("type") in (
                        "response.output_text.delta",
                        "response.output_audio_transcript.delta",
                    ) and wire.accept_output
                            and wire.response_id is not None
                            and event.get("response_id") == wire.response_id
                            and len(transcript) < 64):
                        transcript.append(str(event.get("delta", ""))[:512])
                    if (quiet_input and not output
                            and wire.model_listen_current(event)):
                        # In true duplex a silent room may correctly yield a
                        # model listen decision without response.created/done.
                        # It is not generated audio, a playback ACK, or a fail.
                        model_decision = "listen"
                        return
                    if packet is not None:
                        if first_audio_at is None:
                            first_audio_at = time.monotonic()
                        if len(output) + len(packet.pcm24k) > 24000 * 2 * 30:
                            raise RuntimeError("Native audio output exceeds 30s bound")
                        output.extend(packet.pcm24k)
                    if event.get("type") == "response.done":
                        if (wire.response_id is None
                                or event.get("response_id") != wire.response_id):
                            continue
                        response = event.get("response")
                        if (not isinstance(response, dict)
                                or response.get("status") != "completed"
                                or response.get("id") != event.get("response_id")):
                            raise RuntimeError(
                                "Native duplex response failed, cancelled or malformed"
                            )
                        if not output:
                            # A completed text-only or empty model response is
                            # not evidence of native audio generation. Deliberate
                            # quiet must arrive as response.listen instead.
                            raise RuntimeError(
                                "Native duplex completed without generated speech"
                            )
                        model_decision = "speak"
                        return
                raise RuntimeError("Native duplex socket ended before response.done")

            listener = asyncio.create_task(reader())
            try:
                # Same single audio timeline as vLLM-Omni's official demo.
                # Pacing is deliberate. This is not a device microphone.
                padded = pcm + b"\0" * (-len(pcm) % 32)
                for index in range(0, len(padded), 3200):
                    if listener.done():
                        await listener  # Propagate backend failure or early turn.
                        break
                    chunk = padded[index:index + 3200]
                    packet = wire.append_audio(
                        chunk, speech=not quiet_input,
                        jpeg=jpeg,
                        camera_age_ms=0 if jpeg is not None else None,
                        frame_receipt_us=test_frame_receipt_us,
                    )
                    # Count actual successful appends begun after the first
                    # accepted audio of the same response, not a declared
                    # duplex capability or audio arriving only after commit.
                    response_at_send = wire.response_id if first_audio_at is not None else None
                    await socket.send_json(packet)
                    if (response_at_send is not None
                            and response_at_send == wire.response_id
                            and first_audio_at is not None):
                        input_appends_after_first_audio += 1
                    await asyncio.sleep(packet["duration_ms"] / 1000)
                    if listener.done():
                        await listener
                        break
                if not listener.done():
                    await socket.send_json(wire.commit())
                    # Propagate backend errors and interrupted turns promptly.
                    await listener
                if jpeg is not None and wire.frames_sent == 0:
                    raise RuntimeError("Native backend decided before receiving video")
            finally:
                if not listener.done():
                    listener.cancel()
                # Always retrieve a concurrent reader exception, including
                # when the writer failed or the deadline interrupted input.
                await asyncio.gather(listener, return_exceptions=True)
                if not budget.expired():
                    try:
                        await asyncio.wait_for(
                            socket.send_json({"type": "session.close"}), timeout=1.0,
                        )
                    except Exception:
                        pass

    results.update({
        "input_duration_ms": wire.input_ms,
        "input_mode": "quiet_mic" if quiet_input else "human_speech",
        "model_decision": model_decision,
        "video_frames_sent": wire.frames_sent,
        "generated_audio_ms": len(output) * 1000 // (24000 * 2),
        "input_appends_after_first_audio": input_appends_after_first_audio,
        "input_output_overlap_observed": input_appends_after_first_audio > 0,
        "first_audio_ms_since_connect": (
            round((first_audio_at - started_at) * 1000)
            if first_audio_at is not None else None
        ),
        "transcript_excerpt": "".join(transcript)[:300],
    })
    return bytes(output), results



async def probe_fleet(url: str, model: str, pcm: bytes, jpeg: bytes | None,
                      *, deadline: float, count: int = 5,
                      quiet_input: bool = False
                      ) -> list[tuple[bytes, dict]]:
    """Require N concurrent full AV turns, not N sequential lucky handshakes.

    This only tests backend protocol session admission and generated sound.
    It never proves Mac deployment, microphone AEC, a Xiaozhi speaker, battery,
    or a physical five-robot fleet.
    """
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError("Fleet duplex preflight requires one to five sessions")
    barrier = asyncio.Barrier(count)
    tasks = [
        asyncio.create_task(probe(
            url, model, pcm, jpeg, deadline=deadline, barrier=barrier,
            quiet_input=quiet_input,
        ))
        for _ in range(count)
    ]
    try:
        results = await asyncio.gather(*tasks)
        if any(
            not audio and not (
                quiet_input and stats.get("model_decision") == "listen"
            )
            for audio, stats in results
        ):
            raise RuntimeError("Native session produced neither speech nor intentional silence")
        return results
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8099/v1/realtime?duplex=1")
    parser.add_argument("--model", default="openbmb/MiniCPM-o-4_5")
    parser.add_argument("--input-wav", required=True, type=Path)
    parser.add_argument("--frame-jpeg", type=Path)
    parser.add_argument("--output-wav", required=True, type=Path)
    parser.add_argument("--deadline-s", type=float, default=90.0,
                        help="Total communication deadline; bounded socket cleanup may follow")
    parser.add_argument("--fleet-sessions", type=int, choices=range(1, 6),
                        default=1)
    parser.add_argument("--quiet-input", action="store_true",
                        help="Feed actual quiet PCM as non-speech; allow model listen")
    args = parser.parse_args()
    pcm = read_wav(args.input_wav)
    jpeg = read_jpeg(args.frame_jpeg)
    results = asyncio.run(probe_fleet(
        args.url, args.model, pcm, jpeg, deadline=args.deadline_s,
        count=args.fleet_sessions, quiet_input=args.quiet_input,
    ))
    reports = []
    for index, (output, stats) in enumerate(results, 1):
        # Never overwrite one pet's evidence with another's output WAV.
        dest = (
            args.output_wav if args.fleet_sessions == 1 else
            args.output_wav.with_name(
                f"{args.output_wav.stem}.pet{index:02d}{args.output_wav.suffix}"
            )
        )
        if output:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(dest), "wb") as dst:
                dst.setnchannels(1)
                dst.setsampwidth(2)
                dst.setframerate(24000)
                dst.writeframes(output)
        reports.append({**stats, "output_wav": str(dest) if output else None})
    if args.fleet_sessions == 1:
        print(json.dumps(reports[0], indent=2))
    else:
        print(json.dumps({
            "concurrent_backend_sessions_tested": args.fleet_sessions,
            "backend_turns_completed": len(reports),
            "full_av_turns_completed": sum(row["video_frames_sent"] > 0 for row in reports),
            "input_output_overlap_sessions": sum(
                row["input_output_overlap_observed"] for row in reports
            ),
            "five_physical_robots_verified": False,
            "head_speaker_playback_verified": False,
            "per_session": reports,
        }, indent=2))


if __name__ == "__main__":
    main()
