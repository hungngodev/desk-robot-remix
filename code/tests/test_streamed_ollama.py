"""Actual Ollama streaming fragments and Xiaozhi head cancellation regression."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.conversation import Conversation, KokoroHeadSpeaker, OllamaChat
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


@pytest.mark.parametrize("frame", [
    {"message": {"role": "tool", "content": "Private tool receipt"}, "done": True},
    {"message": {"role": "user", "content": "Human transcript"}, "done": True},
    {"message": {"role": "system", "content": "System secret"}, "done": True},
    {"message": {"role": "assistant", "content": "Do it",
                 "tool_calls": [{"function": {"name": "drive"}}]}, "done": True},
    {"message": {"role": "assistant", "content": "Hello"}, "done": "true"},
    {"message": {"role": "assistant", "content": "Hello"}, "done": 1},
])
async def test_streamed_speech_never_relabels_tool_or_nonassistant_content(frame):
    with pytest.raises(RuntimeError, match="non-assistant/tool|completion marker"):
        _ = [s async for s in ollama_speech_segments(chunks([frame]))]


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
        ("head_abort", "robot-01"),
        ("session", "end"),
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


async def test_partially_transmitted_stream_is_private_and_labeled_uncertain(
    settings, tmp_path,
):
    from desk_robot.memory import MemoryStore

    sent, ended = [], []
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])

    class Chat:
        async def stream_reply(self, history):
            yield "I noticed your silver key."
            raise RuntimeError("Upstream stream dropped after one sentence")

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            yield

        async def say(self, robot, text):
            sent.append((robot.id, text))

        async def interrupt(self, robot):
            ended.append(robot.id)

    c = Conversation(settings, Chat(), Speaker(), memory=memory)
    with pytest.raises(RuntimeError, match="Upstream stream dropped"):
        await c.run(["robot-01", "robot-02"], "keys", 1)
    assert sent == [("robot-01", "I noticed your silver key.")]
    assert ended == ["robot-01"]
    saved = memory.recent("robot-01")
    assert len(saved) == 1
    assert saved[0].kind == "own_utterance"
    assert saved[0].summary == (
        "I started to say (sent, playback unverified): "
        "I noticed your silver key."
    )
    assert memory.recent("robot-02") == []
    # A later model may know what was SENT without being told the peer heard.
    reloaded = Conversation(settings, Chat(), Speaker(), memory=memory)
    assert "playback unverified" in reloaded._persona_with_memory(
        settings.robot("robot-01")
    )


async def test_cancelled_stream_keeps_only_completed_sends_for_speaker_owner(
    settings, tmp_path,
):
    from desk_robot.memory import MemoryStore

    first_sent, blocked, aborted = (
        asyncio.Event(), asyncio.Event(), asyncio.Event()
    )
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])

    class Chat:
        async def stream_reply(self, history):
            yield "I was going to suggest a game."
            blocked.set()
            await asyncio.Event().wait()
            yield "Never spoken."

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            yield

        async def say(self, robot, text):
            first_sent.set()

        async def interrupt(self, robot):
            aborted.set()

    c = Conversation(settings, Chat(), Speaker(), memory=memory)
    task = asyncio.create_task(c.run(["robot-01", "robot-02"], "play", 1))
    await asyncio.wait_for(blocked.wait(), timeout=1)
    await c.stop()
    assert task.cancelled()
    assert aborted.is_set() and first_sent.is_set()
    saved = memory.recent("robot-01")
    assert len(saved) == 1 and "suggest a game" in saved[0].summary
    assert "Never spoken" not in saved[0].summary
    assert memory.recent("robot-02") == []


async def test_ollama_proactive_uses_real_json_schema_and_one_model_call():
    captured = []

    def handle(request: httpx.Request):
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": json.dumps({
                "action": "inspect", "text": "", "tool": "status"
            })}
        })

    settings = SimpleNamespace(
        ollama_url="http://ollama.local:11434",
        ollama_model="local",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle)
    ) as client:
        result = await OllamaChat(settings, client).proactive_decision([
            {"role": "system", "content": "Private pet initiative policy"},
            {"role": "user", "content": "Fresh authenticated sensor change"},
        ])
    assert result == {"action": "inspect", "text": "", "tool": "status"}
    assert len(captured) == 1
    query = captured[0]
    assert query["format"]["properties"]["tool"]["enum"] == [
        "none", "status", "aux_status"
    ]
    assert "drive" not in str(query["format"])
    assert query["stream"] is False
    assert query["think"] is False
    assert query["messages"][0]["role"] == "system"
    assert query["messages"][1]["role"] == "user"


@pytest.mark.parametrize("output", [
    {"action": "inspect", "text": "Run motor!", "tool": "status"},
    {"action": "inspect", "text": "", "tool": "drive"},
    {"action": "speak", "text": "", "tool": "none"},
    {"action": "silence", "text": "Something!", "tool": "none"},
    {"action": "speak", "text": "Okay", "tool": "aux_status"},
    {"action": "silence", "text": "", "tool": "drive"},
    {"action": "speak", "text": "X" * 201, "tool": "none"},
])
async def test_ollama_proactive_refuses_invalid_actions_and_tool_requests(output):
    def handle(request):
        return httpx.Response(200, json={
            "message": {"content": json.dumps(output)}
        })

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle)
    ) as client:
        chat = OllamaChat(SimpleNamespace(
            ollama_url="http://ollama.local:11434",
            ollama_model="local",
        ), client)
        with pytest.raises(RuntimeError, match="Invalid proactive model decision"):
            await chat.proactive_decision([
                {"role": "user", "content": "A genuine visual change"}
            ])


async def test_existing_xiaozhi_speaker_keeps_human_barge_distinct_from_operator_quiet(
    monkeypatch,
):
    sent = []

    def handle(request: httpx.Request):
        assert request.url.path == "/interrupt"
        assert request.headers["authorization"] == "Bearer " + "s" * 40
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "device_id": "mac-01",  # Exact authenticated head identity is required.
            "interrupted": True,
            "head_flush_requested": True,
            "head_flush_acknowledged": False,
        })

    monkeypatch.setenv("BRIDGE_TEST_TOKEN", "s" * 40)
    settings = SimpleNamespace(
        speech_bridge_url="http://local-robot-bridge:9000",
        speech_bridge_token_env="BRIDGE_TEST_TOKEN",
    )
    robot = SimpleNamespace(device_id="mac-01")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle)
    ) as client:
        speaker = KokoroHeadSpeaker(settings, client)
        assert (await speaker.interrupt(robot))["interrupted"] is True
        assert (await speaker.operator_stop(robot))["interrupted"] is True
    assert sent == [
        {"device_id": "mac-01"},
        {"device_id": "mac-01", "revoke_initiative": True},
    ]


@pytest.mark.parametrize("receipt,acceptable", [
    ({"device_id": "head-01", "transmitted": True,
      "physical_playback_verified": False}, True),
    ({"device_id": "head-02", "transmitted": True,
      "physical_playback_verified": False}, False),
    ({"transmitted": True, "physical_playback_verified": False}, False),
    ({"device_id": "head-01", "transmitted": 1,
      "physical_playback_verified": False}, False),
    ({"device_id": "head-01", "transmitted": True}, False),
    ({"device_id": "head-01", "transmitted": True,
      "physical_playback_verified": True}, False),
    ([], False),
])
async def test_kokoro_speech_receipt_must_match_exact_head_and_not_claim_acoustic_playback(
    monkeypatch, receipt, acceptable,
):
    """No queued Opus receipt can impersonate a different fleet speaker."""
    monkeypatch.setenv("DESK_SPEECH_RECEIPT_TOKEN", "s" * 40)
    seen = []

    def respond(request):
        seen.append(request.url.path)
        if request.url.path == "/session":
            body = json.loads(request.content)
            return httpx.Response(200, json={
                "device_ids": body["device_ids"],
                "enabled": body["enabled"],
                "expires_in_seconds": 305 if body["enabled"] else 0,
                "lease_id": body["lease_id"],
            })
        if request.url.path == "/v1/audio/speech":
            return httpx.Response(200, content=b"RIFFsynthetic-audio")
        assert request.url.path == "/speak"
        assert json.loads(request.content)["device_id"] == "head-01"
        return httpx.Response(200, json=receipt)

    settings = SimpleNamespace(
        kokoro_url="http://kokoro.local",
        speech_bridge_url="http://xiaozhi.local",
        speech_bridge_token_env="DESK_SPEECH_RECEIPT_TOKEN",
    )
    robot = SimpleNamespace(device_id="head-01", voice="af_bella")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        speaker = KokoroHeadSpeaker(settings, client)
        async with speaker.session([robot]):
            if acceptable:
                await speaker.say(robot, "Hello there")
            else:
                with pytest.raises(RuntimeError, match="receipt missing matching head identity"):
                    await speaker.say(robot, "Hello there")
    assert seen == ["/session", "/v1/audio/speech", "/speak", "/session"]


@pytest.mark.parametrize("corrupt_grant", [
    None, "wrong_head", "missing_ids", "false_grant", "fake_lease",
    "duplicate_head", "missing_lease_id", "wrong_lease_id",
])
async def test_kokoro_session_grant_and_release_bind_exact_device_set(
    monkeypatch, corrupt_grant,
):
    """A valid HTTP status alone cannot authorize the shared acoustic floor."""
    monkeypatch.setenv("DESK_SESSION_PROOF_TOKEN", "s" * 40)
    requests = []
    ids = ["head-01", "head-02"]

    def respond(request):
        assert request.url.path == "/session"
        assert request.headers["authorization"] == "Bearer " + "s" * 40
        sent = json.loads(request.content)
        requests.append(sent)
        permitted = {
            "device_ids": sorted(ids),
            "enabled": sent["enabled"],
            "lease_id": sent["lease_id"],
            "expires_in_seconds": 305 if sent["enabled"] else 0,
        }
        if sent["enabled"]:
            if corrupt_grant == "wrong_head":
                permitted["device_ids"] = ["head-01", "head-03"]
            elif corrupt_grant == "missing_ids":
                permitted.pop("device_ids")
            elif corrupt_grant == "false_grant":
                permitted["enabled"] = False
            elif corrupt_grant == "fake_lease":
                permitted["expires_in_seconds"] = True
            elif corrupt_grant == "duplicate_head":
                permitted["device_ids"] = ["head-01", "head-01"]
            elif corrupt_grant == "missing_lease_id":
                permitted.pop("lease_id")
            elif corrupt_grant == "wrong_lease_id":
                permitted["lease_id"] = "different-lease"
        return httpx.Response(200, json=permitted)

    settings = SimpleNamespace(
        speech_bridge_url="http://xiaozhi.local",
        speech_bridge_token_env="DESK_SESSION_PROOF_TOKEN",
    )
    robots = [SimpleNamespace(device_id=device) for device in ids]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        speaker = KokoroHeadSpeaker(settings, client)
        if corrupt_grant is None:
            async with speaker.session(robots):
                assert len(requests) == 1
                assert requests[0]["device_ids"] == ids
                assert requests[0]["enabled"] is True
                assert isinstance(requests[0]["lease_id"], str)
                assert len(requests[0]["lease_id"]) == 32
        else:
            with pytest.raises(RuntimeError, match="grant identity unconfirmed"):
                async with speaker.session(robots):
                    pytest.fail("Corrupt session grant must never hand over audio")
    assert len(requests) == 2
    assert requests[0]["device_ids"] == requests[1]["device_ids"] == ids
    assert [request["enabled"] for request in requests] == [True, False]
    assert requests[0]["lease_id"] == requests[1]["lease_id"]
    assert len(requests[0]["lease_id"]) == 32


@pytest.mark.parametrize("receipt_lease_id", [None, "different-lease"])
async def test_kokoro_session_requires_release_lease_receipt(monkeypatch, receipt_lease_id):
    monkeypatch.setenv("DESK_SESSION_PROOF_TOKEN", "s" * 40)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        response = {
            "device_ids": body["device_ids"],
            "enabled": body["enabled"],
            "expires_in_seconds": 305 if body["enabled"] else 0,
            "lease_id": body["lease_id"],
        }
        if not body["enabled"]:
            if receipt_lease_id is None:
                response.pop("lease_id")
            else:
                response["lease_id"] = receipt_lease_id
        return httpx.Response(200, json=response)

    settings = SimpleNamespace(
        speech_bridge_url="http://xiaozhi.local",
        speech_bridge_token_env="DESK_SESSION_PROOF_TOKEN",
    )
    robot = SimpleNamespace(device_id="head-01")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        speaker = KokoroHeadSpeaker(settings, client)
        with pytest.raises(RuntimeError, match="release unconfirmed"):
            async with speaker.session([robot]):
                pass
    assert [request["enabled"] for request in requests] == [True, False]



async def test_kokoro_session_rejects_unconfirmed_release_and_duplicate_devices(
    monkeypatch,
):
    monkeypatch.setenv("DESK_SESSION_PROOF_TOKEN", "s" * 40)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={
            "device_ids": body["device_ids"],
            "enabled": True,  # release request must not be misacknowledged
            "lease_id": body["lease_id"],
            "expires_in_seconds": 305,
        })

    settings = SimpleNamespace(
        speech_bridge_url="http://xiaozhi.local",
        speech_bridge_token_env="DESK_SESSION_PROOF_TOKEN",
    )
    robot = SimpleNamespace(device_id="head-01")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        speaker = KokoroHeadSpeaker(settings, client)
        with pytest.raises(RuntimeError, match="distinct Xiaozhi"):
            async with speaker.session([robot, robot]):
                pytest.fail("Duplicated physical robot identity cannot open a session")
        assert requests == []
        with pytest.raises(RuntimeError, match="release unconfirmed"):
            async with speaker.session([robot]):
                pass
    assert [request["enabled"] for request in requests] == [True, False]



@pytest.mark.parametrize("reason", ["stop", None])
async def test_ollama_normal_terminal_reason_or_legacy_absence_completes(reason):
    terminal = {
        "message": {"role": "assistant", "content": "All done."},
        "done": True,
    }
    if reason is not None:
        terminal["done_reason"] = reason
    frames = [
        {"message": {"role": "assistant", "content": "First sentence. "}, "done": False},
        terminal,
    ]
    assert [s async for s in ollama_speech_segments(chunks(frames))] == [
        "First sentence.", "All done."
    ]


@pytest.mark.parametrize("reason", ["length", "load", False, None])
async def test_ollama_nonstop_terminal_never_emits_unsent_partial_tail(reason):
    frames = [
        {"message": {"role": "assistant", "content": "A complete sentence. "},
         "done": False},
        {"message": {"role": "assistant", "content": "The answer is"},
         "done": True, "done_reason": reason},
    ]
    stream = ollama_speech_segments(chunks(frames))
    assert await anext(stream) == "A complete sentence."
    with pytest.raises(RuntimeError, match="before normal completion"):
        await anext(stream)


async def test_ollama_token_exhaustion_aborts_head_and_keeps_only_sent_private_text(
    settings, tmp_path,
):
    """Actual NDJSON -> OllamaChat -> Conversation -> speaker abort -> SQLite."""
    from desk_robot.memory import MemoryStore

    frames = [
        {"message": {"role": "assistant", "content": "I saw the silver key. "},
         "done": False},
        {"message": {"role": "assistant", "content": "It seems to be"},
         "done": True, "done_reason": "length"},
    ]
    requests = []
    def respond(request):
        assert request.url.path == "/api/chat"
        assert json.loads(request.content)["stream"] is True
        requests.append(request)
        return httpx.Response(200, text="\n".join(json.dumps(p) for p in frames))

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
            events.append(("sent", robot.id, text))

        async def interrupt(self, robot):
            events.append(("head_abort", robot.id))

    store = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    model_settings = SimpleNamespace(
        ollama_url="http://ollama.local:11434", ollama_model="qwen3",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        chat = OllamaChat(model_settings, client)
        conversation = Conversation(settings, chat, Speaker(), memory=store)
        with pytest.raises(RuntimeError, match="before normal completion"):
            await conversation.run(["robot-01", "robot-02"], "what is the key?", 2)

    assert len(requests) == 1  # The second pet cannot inherit a cut-off answer.
    assert events == [
        "session_begin",
        ("sent", "robot-01", "I saw the silver key."),
        ("head_abort", "robot-01"),
        "session_end",
    ]
    saved = store.recent("robot-01")
    assert len(saved) == 1
    assert saved[0].kind == "own_utterance"
    assert saved[0].summary == (
        "I started to say (sent, playback unverified): I saw the silver key."
    )
    assert store.recent("robot-02") == []
    assert not any(
        message["role"] == "assistant"
        for history in conversation.histories.values()
        for message in history
    )
    assert conversation.active is None


@pytest.mark.parametrize("fragments", [[""], [" \t\n"], [" " * 200, "\t\n"]])
async def test_ollama_rejects_stream_without_speakable_content(fragments):
    frames = [
        {"message": {"content": fragment}, "done": index == len(fragments) - 1}
        for index, fragment in enumerate(fragments)
    ]
    with pytest.raises(RuntimeError, match="empty streamed speech"):
        _ = [segment async for segment in ollama_speech_segments(chunks(frames))]


async def test_ollama_accepts_padding_around_emitted_sentence():
    frames = [
        {"message": {"content": "  Hello there. "}, "done": False},
        {"message": {"content": " \t\n"}, "done": True},
    ]
    assert [s async for s in ollama_speech_segments(chunks(frames))] == ["Hello there."]
