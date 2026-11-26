"""Model HTTP boundary tests without a model or physical head."""
import asyncio
import base64
import json
import wave
from io import BytesIO
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer


@pytest.fixture
def protocol(monkeypatch):
    monkeypatch.syspath_prepend(str(
        Path(__file__).resolve().parents[1] / "laptop/server/overlay"
    ))
    import desk_robot_omni_http_protocol

    return desk_robot_omni_http_protocol


def _wav(pcm, *, rate=24000, channels=1, width=2):
    with BytesIO() as output:
        with wave.open(output, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(width)
            wav.setframerate(rate)
            wav.writeframes(pcm)
        return output.getvalue()


def _audio(raw):
    return {"message": {"audio": {"data": base64.b64encode(raw).decode()}}}


@pytest.mark.parametrize(("url", "endpoint"), [
    ("ws://localhost:8099/v1/realtime?duplex=1",
     "http://localhost:8099/v1/chat/completions"),
    ("ws://[::1]:8099/v1/realtime?duplex=1",
     "http://[::1]:8099/v1/chat/completions"),
    ("ws://127.0.0.1/v1/realtime?duplex=1",
     "http://127.0.0.1/v1/chat/completions"),
    ("wss://model.example/v1/realtime?duplex=1",
     "https://model.example/v1/chat/completions"),
])
def test_model_http_endpoint_preserves_approved_origin(protocol, url, endpoint):
    assert protocol.approved_backend_url(url) == url
    assert protocol.chat_completion_endpoint(url) == endpoint


@pytest.mark.parametrize("url", [
    "ws://192.168.0.5/v1/realtime?duplex=1",
    "http://127.0.0.1/v1/realtime?duplex=1",
    "wss://user:pass@model.example/v1/realtime?duplex=1",
    "wss://model.example/v1/realtime?duplex=0",
    "wss://model.example/v1/realtime?duplex=1#fragment",
    "wss://model.example/other?duplex=1",
])
def test_model_http_endpoint_rejects_unapproved_origin(protocol, url):
    with pytest.raises(ValueError):
        protocol.chat_completion_endpoint(url)


def test_decode_split_model_text_and_audio_choices(protocol):
    pcm = b"\x12\x34" * 240
    result = {"choices": [None, {"message": {"content": "  Hello  "}},
                          _audio(_wav(pcm))]}
    assert protocol.decode_tool_completion(result) == (pcm, "  Hello  ")
    assert protocol.decode_tool_completion({"choices": [_audio(_wav(pcm))]}) == (pcm, "")


@pytest.mark.parametrize("result", [None, [], {}, {"choices": {}},
    {"choices": [None, {"message": {"content": "No audio"}}]},
    {"choices": [{"message": {"audio": {"data": "!"}}}]},
    {"choices": [{"message": {"audio": {"data": "A" * 1_600_001}}}]},
])
def test_decode_rejects_invalid_response_structure(protocol, result):
    with pytest.raises(ValueError):
        protocol.decode_tool_completion(result)


@pytest.mark.parametrize("raw", [
    b"RIFF", b"not a wave file", _wav(b""), _wav(b"\x00" * 481),
    _wav(b"\x00" * 480)[:-1], _wav(b"\x00" * 480)[:-2],
    _wav(b"\x00" * 480, rate=16000),
    _wav(b"\x00" * 480, channels=2),
    _wav(b"\x00" * 480, width=1),
    _wav(b"\x00" * 960002),
])
def test_decode_rejects_invalid_or_incomplete_pcm(protocol, raw):
    with pytest.raises(ValueError):
        protocol.decode_tool_completion({"choices": [_audio(raw)]})


def test_decode_accepts_exact_twenty_second_pcm_limit(protocol):
    pcm = b"\x01\x00" * (24000 * 20)
    assert protocol.decode_tool_completion({"choices": [_audio(_wav(pcm))]}) == (pcm, "")


@pytest.mark.parametrize("delta", [-2, 2])
def test_decode_rejects_inconsistent_riff_length(protocol, delta):
    raw = _wav(b"\x01\x00" * 240)
    declared = int.from_bytes(raw[4:8], "little") + delta
    malformed = raw[:4] + declared.to_bytes(4, "little") + raw[8:]
    with pytest.raises(ValueError):
        protocol.decode_tool_completion({"choices": [_audio(malformed)]})


def test_decode_accepts_complete_trailing_metadata(protocol):
    pcm = b"\x01\x00" * 240
    raw = _wav(pcm) + b"JUNK\x02\x00\x00\x00ab"
    raw = raw[:4] + (len(raw) - 8).to_bytes(4, "little") + raw[8:]
    assert protocol.decode_tool_completion({"choices": [_audio(raw)]}) == (pcm, "")
    with pytest.raises(ValueError):
        protocol.decode_tool_completion({"choices": [_audio(raw[:-1])]})


@pytest.mark.parametrize("trailing", [
    b"JUNK",
    b"JUNK\x04\x00\x00\x00ab",
    b"JUNK\x01\x00\x00\x00a",
])
def test_decode_rejects_incomplete_trailing_chunk(protocol, trailing):
    raw = _wav(b"\x01\x00" * 240) + trailing
    raw = raw[:4] + (len(raw) - 8).to_bytes(4, "little") + raw[8:]
    with pytest.raises(ValueError, match="WAV container"):
        protocol.decode_tool_completion({"choices": [_audio(raw)]})


def test_decode_accepts_padded_odd_metadata_chunk(protocol):
    pcm = b"\x01\x00" * 240
    raw = _wav(pcm) + b"JUNK\x01\x00\x00\x00a\x00"
    raw = raw[:4] + (len(raw) - 8).to_bytes(4, "little") + raw[8:]
    assert protocol.decode_tool_completion({"choices": [_audio(raw)]}) == (pcm, "")


async def _chunks(*parts):
    for part in parts:
        yield part


@pytest.mark.asyncio
async def test_read_model_completion_accepts_exact_body_limit(protocol, monkeypatch):
    pcm = b"\x01\x00" * 240
    body = json.dumps({"choices": [_audio(_wav(pcm))]}).encode("utf-8")
    monkeypatch.setattr(protocol, "MAX_MODEL_RESPONSE_BYTES", len(body))
    assert await protocol.read_tool_completion(_chunks(body[:17], body[17:])) == (pcm, "")


@pytest.mark.asyncio
async def test_read_model_completion_stops_at_body_limit(protocol, monkeypatch):
    monkeypatch.setattr(protocol, "MAX_MODEL_RESPONSE_BYTES", 8)

    async def oversized():
        yield b"12345678"
        yield b"9"
        pytest.fail("Body reader continued after exceeding its byte limit")

    with pytest.raises(ValueError, match="response limit"):
        await protocol.read_tool_completion(oversized())


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"{", b"\xff"], ids=["partial_json", "invalid_utf8"])
async def test_read_model_completion_rejects_invalid_json(protocol, body):
    with pytest.raises(ValueError, match="Invalid model chat completion JSON"):
        await protocol.read_tool_completion(_chunks(body))


@pytest.mark.asyncio
async def test_read_model_completion_propagates_timeout_and_cancellation(protocol):
    waiting = asyncio.Event()

    async def slow():
        yield b"{"
        waiting.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(protocol.read_tool_completion(slow()))
    try:
        await asyncio.wait_for(waiting.wait(), timeout=1)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0.01)
        assert task.cancelled()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_read_model_completion_obeys_client_total_timeout(protocol):
    release = asyncio.Event()

    async def slow_response(request):
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        await response.write(b"{")
        await release.wait()
        return response

    app = web.Application()
    app.router.add_get("/", slow_response)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        try:
            async with session.get(
                server.make_url("/"), timeout=aiohttp.ClientTimeout(total=0.2),
            ) as response:
                with pytest.raises(asyncio.TimeoutError):
                    await protocol.read_tool_completion(response.content.iter_chunked(64 * 1024))
        finally:
            release.set()
