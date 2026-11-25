"""Pure wire helpers for the native model's realtime and HTTP endpoints.

No session state, credentials, network I/O, or playback authority lives here.
"""
from __future__ import annotations

import base64
import ipaddress
import wave
from io import BytesIO
from urllib.parse import urlsplit


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
