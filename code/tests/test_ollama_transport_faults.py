"""Inject failures into actual HTTPX response iteration, not a fake chat model."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.streamed_ollama import ollama_speech_segments

FAULTS = [
    pytest.param("drop", httpx.RemoteProtocolError, "incomplete", id="dropped-body"),
    pytest.param("malformed", RuntimeError, "Malformed Ollama", id="invalid-ndjson"),
    pytest.param("timeout", httpx.ReadTimeout, "read stalled", id="read-timeout"),
    pytest.param("eof", RuntimeError, "without done marker", id="premature-eof"),
]


class FaultyBody(httpx.AsyncByteStream):
    def __init__(self, fault, request):
        self.fault = fault
        self.request = request
        self.closed = False

    async def __aiter__(self):
        yield b'{"message":{"content":"First sentence. "},"done":false}\n'
        yield b'{"message":{"content":"Unfinished thought"},"done":false}\n'
        if self.fault == "drop":
            raise httpx.RemoteProtocolError("incomplete chunked read", request=self.request)
        if self.fault == "malformed":
            yield b'{"message": invalid}\n'
        if self.fault == "timeout":
            raise httpx.ReadTimeout("read stalled", request=self.request)

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("fault,error,match", FAULTS)
async def test_http_body_failure_never_flushes_unfinished_tail(fault, error, match):
    bodies = []

    def respond(request):
        body = FaultyBody(fault, request)
        bodies.append(body)
        return httpx.Response(200, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        async with client.stream("POST", "http://local/api/chat") as response:
            segments = ollama_speech_segments(response.aiter_lines())
            assert await anext(segments) == "First sentence."
            assert not bodies[0].closed
            with pytest.raises(error, match=match):
                await anext(segments)
            with pytest.raises(StopAsyncIteration):
                await anext(segments)
        assert bodies[0].closed


@pytest.mark.parametrize("fault,error,match", FAULTS)
async def test_model_transport_fault_releases_floor_for_next_turn(settings, fault, error, match):
    from desk_robot.conversation import Conversation, OllamaChat

    events = []
    bodies = []
    requests = []

    def respond(request):
        assert request.url.path == "/api/chat"
        assert json.loads(request.content)["stream"] is True
        requests.append(request)
        if len(requests) == 1:
            body = FaultyBody(fault, request)
            bodies.append(body)
            return httpx.Response(200, stream=body)
        return httpx.Response(200, text='{"message":{"content":"Recovered."},"done":true}\n')

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            events.append("grant")
            try:
                yield
            finally:
                events.append("release")

        async def say(self, robot, text):
            events.append((robot.id, text))

        async def interrupt(self, robot):
            events.append(("abort", robot.id))

    model = SimpleNamespace(ollama_url="http://local", ollama_model="local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        conversation = Conversation(settings, OllamaChat(model, client), Speaker())
        ids = ["robot-01", "robot-02"]
        with pytest.raises(error, match=match):
            await asyncio.wait_for(conversation.run(ids, "first", 2), timeout=5)
        assert bodies[0].closed
        assert len(requests) == 1
        assert conversation.active is None
        assert not conversation.session_lock.locked()
        assert not conversation.speaker_lock.locked()
        assert events == ["grant", (ids[0], "First sentence."), ("abort", ids[0]), "release"]
        assert not any(
            message["role"] == "assistant"
            for history in conversation.histories.values()
            for message in history
        )
        recovered = await asyncio.wait_for(conversation.run(ids, "next", 1), timeout=5)
        assert recovered == [{"robot_id": ids[0], "text": "Recovered."}]
        assert events[-3:] == ["grant", (ids[0], "Recovered."), "release"]
        assert len(requests) == 2
        assert conversation.active is None
