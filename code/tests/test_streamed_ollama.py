"""Actual Ollama streaming fragments and Xiaozhi head cancellation regression."""
import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from desk_robot.conversation import Conversation, OllamaChat
from desk_robot.streamed_ollama import ollama_speech_segments


async def chunks(lines):
    for line in lines:
        yield json.dumps(line)


async def test_sentence_stream_does_not_wait_for_final_ollama_reply():
    frames = [
        {"message": {"content": "Hello there. "}, "done": False},
        {"message": {"content": "How are "}, "done": False},
        {"message": {"content": "you today?"}, "done": False},
        {"message": {"content": ""}, "done": True},
    ]
    generator = ollama_speech_segments(chunks(frames))
    assert await anext(generator) == "Hello there."
    assert [segment async for segment in generator] == ["How are you today?"]


async def test_ollama_fractional_number_survives_stream_boundary():
    frames = [
        {"message": {"content": "Value 3."}, "done": False},
        {"message": {"content": "14 is good. "}, "done": False},
        {"message": {"content": "Okay."}, "done": True},
    ]
    assert [segment async for segment in ollama_speech_segments(chunks(frames))] == [
        "Value 3.14 is good.", "Okay."
    ]


@pytest.mark.parametrize("frames", [
    [{"message": {"content": "hello"}, "done": False}],
    [{"message": {"content": 42}, "done": True}],
    [{"error": "malformed"}],
    [{"message": {"content": "x" * 2001}, "done": True}],
])
async def test_malformed_or_unbounded_stream_rejected(frames):
    with pytest.raises(RuntimeError):
        _ = [s async for s in ollama_speech_segments(chunks(frames))]


async def test_actual_ollama_http_stream_is_sentence_incremental():
    seen = []
    def respond(request):
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["stream"] is True and payload["think"] is False
        seen.append("request")
        return httpx.Response(200, text="\n".join([
            json.dumps({"message": {"content": "Hi there. "}, "done": False}),
            json.dumps({"message": {"content": "Ready to play!"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        chat = OllamaChat(
            type("Settings", (), {"ollama_url": "http://local:11434", "ollama_model": "qwen3"})(),
            client,
        )
        assert [s async for s in chat.stream_reply([{"role": "user", "content": "hi"}])] == [
            "Hi there.", "Ready to play!"
        ]
    assert seen == ["request"]


async def test_streamed_peer_turn_uses_one_existing_speech_session(settings):
    class Chat:
        async def stream_reply(self, history):
            yield "First sentence."
            yield "Second sentence."

    class Speaker:
        def __init__(self):
            self.spoken = []
            self.sessions = 0

        @asynccontextmanager
        async def session(self, robots):
            self.sessions += 1
            yield

        async def say(self, robot, text):
            self.spoken.append((robot.id, text))

    speaker = Speaker()
    c = Conversation(settings, Chat(), speaker)
    turns = await c.run(["robot-01", "robot-02"], "hello", 1)
    assert turns[0]["text"] == "First sentence. Second sentence."
    assert speaker.spoken == [
        ("robot-01", "First sentence."),
        ("robot-01", "Second sentence."),
    ]
    assert speaker.sessions == 1


async def test_cancelled_streamed_voice_sends_urgent_real_head_abort(settings):
    in_speaker = asyncio.Event()
    interrupts = []

    class Chat:
        async def stream_reply(self, history):
            yield "Speaking while you interrupt. "
            yield "This must never be spoken."

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            yield

        async def say(self, robot, text):
            in_speaker.set()
            await asyncio.Event().wait()

        async def interrupt(self, robot):
            interrupts.append(robot.id)

    speaker = Speaker()
    c = Conversation(settings, Chat(), speaker)
    task = asyncio.create_task(c.run(["robot-01", "robot-02"], "hello", 1))
    await asyncio.wait_for(in_speaker.wait(), timeout=1)
    await c.stop()
    assert task.cancelled()
    assert interrupts == ["robot-01"]
    assert c.active is None



async def test_failed_stream_flushes_physical_head_before_group_lease_releases(settings):
    events = []

    class Chat:
        async def stream_reply(self, _history):
            yield "I started saying something."
            raise RuntimeError("Ollama streaming connection lost")

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            events.append(("session", "begin"))
            try:
                yield
            finally:
                events.append(("session", "end"))

        async def say(self, robot, text):
            events.append(("spoken", robot.id, text))

        async def interrupt(self, robot):
            events.append(("head_abort", robot.id))

    c = Conversation(settings, Chat(), Speaker())
    with pytest.raises(RuntimeError, match="Ollama streaming connection"):
        await c.run(["robot-01", "robot-02"], "respond", 1)
    assert events == [
        ("session", "begin"),
        ("spoken", "robot-01", "I started saying something."),
        ("session", "end"),
        ("head_abort", "robot-01"),
    ]
    assert c.active is None


async def test_proactive_speaker_partial_transport_failure_sends_real_abort(settings):
    events = []

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            events.append("session_begin")
            try:
                yield
            finally:
                events.append("session_end")

        async def say(self, robot, text):
            events.append("partially_queued")
            raise RuntimeError("Bridge disconnected after audio queued")

        async def interrupt(self, robot):
            events.append("head_abort")

    c = Conversation(settings, None, Speaker())
    with pytest.raises(RuntimeError, match="Bridge disconnected"):
        await c.say_proactive(settings.robots[0], "Hello there")
    assert events == ["session_begin", "partially_queued", "head_abort", "session_end"]
    assert c.active is None
