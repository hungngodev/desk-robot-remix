"""Pure wire helpers for the native model's realtime and HTTP endpoints.

No session state, credentials, connection ownership, or playback authority lives here.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import wave
from collections.abc import AsyncIterable
from io import BytesIO
from urllib.parse import urlsplit


MAX_MODEL_RESPONSE_BYTES = 2_000_000


def approved_backend_url(url: str) -> str:
    """No microphone plaintext may leave this Mac over an arbitrary LAN URL."""
    value = urlsplit(url)
    if (value.scheme not in ("ws", "wss") or not value.hostname
            or value.username or value.password or value.fragment
            or value.path != "/v1/realtime" or value.query != "duplex=1"):
        raise ValueError("Use the official realtime /v1/realtime?duplex=1 URL")
    if value.scheme == "ws":
        if value.hostname != "localhost":
            try:
                if not ipaddress.ip_address(value.hostname).is_loopback:
                    raise ValueError("Mic traffic over LAN requires wss://")
            except ValueError as exc:
                raise ValueError("Mic traffic requires loopback ws or secure wss") from exc
    return url


def chat_completion_endpoint(url: str) -> str:
    """Derive the HTTP sibling of an already approved realtime endpoint."""
    value = urlsplit(approved_backend_url(url))
    return (
        ("https" if value.scheme == "wss" else "http")
        + "://" + value.netloc + "/v1/chat/completions"
    )


def _validate_wav_extent(encoded: bytes) -> None:
    """Check the bounded RIFF container even beyond the first PCM chunk."""
    if len(encoded) < 12 or int.from_bytes(encoded[4:8], "little") != len(encoded) - 8:
        raise ValueError("Incomplete or inconsistent model WAV container")
    offset = 12
    while offset < len(encoded):
        if len(encoded) - offset < 8:
            raise ValueError("Incomplete model WAV container chunk header")
        size = int.from_bytes(encoded[offset + 4:offset + 8], "little")
        offset += 8 + size + (size & 1)
        if offset > len(encoded):
            raise ValueError("Incomplete model WAV container chunk payload or padding")


def decode_tool_completion(result: object) -> tuple[bytes, str]:
    """Return bounded 24 kHz mono PCM16 and optional model text, not playback."""
    choices = result.get("choices") if isinstance(result, dict) else None
    if not isinstance(choices, list):
        raise ValueError("No model chat completion choices")
    wav_text = next((
        choice.get("message", {}).get("audio", {}).get("data")
        for choice in choices if isinstance(choice, dict)
        and isinstance(choice.get("message"), dict)
        and isinstance(choice["message"].get("audio"), dict)
        and isinstance(choice["message"]["audio"].get("data"), str)
    ), None)
    # MiniCPM-o 4.5 returns separate text and speech choices.
    # This text is *not* proof of what the physical speaker played.
    generated_text = next((
        choice.get("message", {}).get("content")
        for choice in choices if isinstance(choice, dict)
        and isinstance(choice.get("message"), dict)
        and isinstance(choice["message"].get("content"), str)
        and choice["message"]["content"].strip()
    ), "")
    if not wav_text or len(wav_text) > 1_600_000:
        raise ValueError("No bounded model speech audio")
    encoded = base64.b64decode(wav_text, validate=True)
    if len(encoded) > 1_200_000:
        raise ValueError("Model audio exceeds duration limit")
    _validate_wav_extent(encoded)
    try:
        with wave.open(BytesIO(encoded), "rb") as wav:
            if (wav.getnchannels() != 1 or wav.getsampwidth() != 2
                    or wav.getframerate() != 24000
                    or not 0 < wav.getnframes() <= 24_000 * 20):
                raise ValueError("Expected 24 kHz mono PCM16 model WAV")
            frames = wav.getnframes()
            # wave.readframes may return fewer bytes than the header
            # promises, or a trailing incomplete sample. Do not treat
            # either as completed speech or feed it to the Opus encoder.
            pcm = wav.readframes(frames + 1)
            if len(pcm) != frames * 2:
                raise ValueError("Truncated or misaligned model WAV PCM")
    except (EOFError, wave.Error) as exc:
        raise ValueError("Invalid model WAV container") from exc
    return pcm, generated_text


async def read_tool_completion(chunks: AsyncIterable[bytes]) -> tuple[bytes, str]:
    """Bound the decoded HTTP body before parsing JSON or speech audio."""
    body = bytearray()
    async for chunk in chunks:
        if len(chunk) > MAX_MODEL_RESPONSE_BYTES - len(body):
            raise ValueError("Model chat completion exceeds response limit")
        body.extend(chunk)
    try:
        result = json.loads(body.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid model chat completion JSON") from exc
    return decode_tool_completion(result)
