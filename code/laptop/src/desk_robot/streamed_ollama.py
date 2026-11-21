"""Bounded Ollama NDJSON to speakable incremental sentence chunks.

Reuse the existing Ollama /api/chat stream instead of waiting for every token.
The caller owns Xiaozhi session and cancellation; no audio or motion transport
is created here. Fragments are never treated as machine commands.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator


def _cut(buffer: str, target: int) -> tuple[str, str] | None:
    # Only cut after an actual sentence punctuation boundary, not at the first
    # arbitrary token. A long run-on paragraph is split at a word boundary.
    for pos, char in enumerate(buffer):
        # A period at the fragment boundary might be part of a decimal.
        # Wait for following whitespace before streaming that sentence.
        if char in ".!?" and pos >= 2 and (
            pos + 1 < len(buffer) and buffer[pos + 1].isspace()
        ):
            return buffer[:pos + 1].strip(), buffer[pos + 1:].lstrip()
    if len(buffer) >= target:
        end = buffer.rfind(" ", 0, target + 1)
        if end > target // 2:
            return buffer[:end].strip(), buffer[end + 1:].lstrip()
    return None


async def ollama_speech_segments(
    lines: AsyncIterable[str], *, max_total: int = 2000, target: int = 150
) -> AsyncIterator[str]:
    """Convert actual Ollama JSON chunks to bounded TTS segments.

    Requires a proper done marker. On truncated/invalid streams it fails
    rather than claiming a complete spoken turn. Partial already-spoken audio
    can only be stopped by the outer Xiaozhi owner.
    """
    if not 30 <= target <= 300 or not 1 <= max_total <= 5000:
        raise ValueError("Invalid streaming speech limits")
    buffered = ""
    count = 0
    done = False
    async for line in lines:
        if not line.strip():
            continue
        try:
            packet = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Malformed Ollama streaming frame") from exc
        if not isinstance(packet, dict):
            raise RuntimeError("Ollama streaming frame must be an object")
        if packet.get("error"):
            raise RuntimeError("Ollama streaming provider error")
        if "done" in packet and type(packet["done"]) is not bool:
            raise RuntimeError("Ollama streaming completion marker invalid")
        message = packet.get("message", {})
        if not isinstance(message, dict):
            raise RuntimeError("Ollama streaming message invalid")
        # The speech channel owns assistant words, NOT tool output or
        # untrusted user/system frames. A model tool request needs the
        # separately authorized completed-tool path before speech synthesis.
        if ("role" in message and message["role"] != "assistant"
                or message.get("tool_calls")):
            raise RuntimeError("Ollama streaming non-assistant/tool frame rejected")
        fragment = message.get("content", "")
        if not isinstance(fragment, str):
            raise RuntimeError("Ollama streaming content invalid")
        count += len(fragment)
        if count > max_total:
            raise RuntimeError("Ollama streaming response exceeds speech limit")
        buffered += fragment
        while (piece := _cut(buffered, target)) is not None:
            sentence, buffered = piece
            if sentence:
                yield sentence
        if packet.get("done") is True:
            done = True
            break
    if not done:
        raise RuntimeError("Ollama streaming response ended without done marker")
    if buffered.strip():
        yield buffered.strip()
    if not count:
        raise RuntimeError("Ollama returned empty streamed speech")
