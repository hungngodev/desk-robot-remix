"""Native duplex deadlines and teardown, without hardware or model service."""
import asyncio
import base64
import importlib.util
import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

ROOT = Path(__file__).resolve().parents[1]
MODEL = "openbmb/MiniCPM-o-4_5"


def smoke_module():
    spec = importlib.util.spec_from_file_location(
        "omni_duplex_smoke", ROOT / "scripts/omni_duplex_smoke.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("stall", ["greeting", "terminal", "partial_audio"])
async def test_stalled_native_probe_reports_phase_and_disconnects(stall):
    smoke = smoke_module()
    disconnected = asyncio.Event()

    async def model_socket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        try:
            async for msg in socket:
                event = json.loads(msg.data)
                if event["type"] == "session.update" and stall != "greeting":
                    await socket.send_json({
                        "type": "session.created",
                        "session": {
                            "model": MODEL,
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm16",
                            "audio": {
                                "input": {"sample_rate_hz": 16000},
                                "output": {"format": {"type": "audio/pcm", "rate": 24000}},
                            },
                            "capabilities": {
                                "implementation_level": "model_native_duplex",
                                "supports_input_append": True,
                                "supports_barge_in": True,
                                "chunk_period_ms": 1000,
                            },
                        },
                    })
                elif event["type"] == "input_audio_buffer.commit" and stall == "partial_audio":
                    await socket.send_json({
                        "type": "response.created", "response_id": "unfinished",
                        "response": {
                            "id": "unfinished", "metadata": {"duplex_event": {"epoch": 0}},
                        },
                    })
                    await socket.send_json({
                        "type": "response.output_audio.delta", "response_id": "unfinished",
                        "format": "pcm16", "sample_rate_hz": 24000, "metadata": {"epoch": 0},
                        "delta": base64.b64encode(bytes(4800)).decode("ascii"),
                    })
        finally:
            disconnected.set()
        return socket

    app = web.Application()
    app.router.add_get("/v1/realtime", model_socket)
    expected = "waiting for session.created" if stall == "greeting" else "terminal response"
    async with TestServer(app) as server:
        url = str(server.make_url("/v1/realtime?duplex=1")).replace("http://", "ws://")
        task = asyncio.create_task(smoke.probe(url, MODEL, bytes(3200), None, deadline=5))
        try:
            done, _ = await asyncio.wait({task}, timeout=8)
            assert task in done, "Probe failed to enforce its own deadline and cleanup bound"
            with pytest.raises(TimeoutError, match=expected):
                await task
            await asyncio.wait_for(disconnected.wait(), timeout=2)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "protocol_error", "success", "close_write"])
async def test_socket_close_has_absolute_bound_and_preserves_primary_failure(failure):
    smoke = smoke_module()
    close_started = asyncio.Event()
    close_cancelled = asyncio.Event()
    close_messages = []

    class StalledSocket:
        async def send_json(self, event):
            close_messages.append(event)
            if failure == "close_write":
                await asyncio.Future()

        async def close(self):
            close_started.set()
            try:
                await asyncio.Future()
            finally:
                close_cancelled.set()

    class Client:
        async def ws_connect(self, *args, **kwargs):
            return StalledSocket()

    async def run():
        async with smoke._probe_socket(Client(), "unused", 0.05, lambda: "test phase"):
            if failure == "timeout":
                await asyncio.Future()
            elif failure == "protocol_error":
                raise RuntimeError("primary protocol failure")

    task = asyncio.create_task(run())
    try:
        done, _ = await asyncio.wait({task}, timeout=3)
        assert task in done, "The WebSocket close operation escaped its absolute bound"
        if failure == "timeout":
            with pytest.raises(TimeoutError, match="test phase"):
                await task
        elif failure == "protocol_error":
            with pytest.raises(RuntimeError, match="primary protocol failure"):
                await task
        else:
            await task
        assert close_started.is_set()
        assert close_cancelled.is_set()
        expected = [{"type": "session.close"}] if failure in ("success", "close_write") else []
        assert close_messages == expected
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
