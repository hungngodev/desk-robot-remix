import asyncio

import pytest
from desk_robot.api import create_app
from desk_robot.conversation import Conversation, KokoroHeadSpeaker
from desk_robot.memory import MemoryStore
from desk_robot.simulator import SimulatedChat, SimulatedSpeaker
from fastapi.testclient import TestClient


def test_model_token_cannot_enable_motion_or_manually_drive(settings, tokens):
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/robots").status_code == 401
        assert (
            client.get("/v1/robots", headers={b"Authorization": b"Bearer \xf1"}).status_code == 401
        )
        tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
        operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
        assert client.get("/v1/robots", headers=tool).json()["mode"] == "simulation"
        assert client.post("/v1/robots/robot-01/enable", headers=tool).status_code == 403
        assert client.post("/v1/robots/robot-01/explore", headers=tool).status_code == 403
        assert (
            client.post(
                "/v1/robots/robot-01/move", headers=tool, json={"command": "lift 90"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/robots/robot-01/pickup", headers=tool, json={"target": "key"}
            ).status_code
            == 409
        )
        assert client.post("/v1/robots/robot-01/enable", headers=operator).status_code == 200
        result = client.post("/v1/robots/robot-01/pickup", headers=tool, json={"target": "key"})
        assert result.status_code == 202
        assert client.post("/v1/robots/robot-01/stop", headers=tool).status_code == 200
        assert (
            client.get(f"/v1/jobs/{result.json()['id']}", headers=tool).json()["state"]
            == "cancelled"
        )
        assert (
            client.post(
                "/v1/conversation",
                headers=tool,
                json={"robot_ids": ["robot-01", "robot-02"], "topic": "Hello", "utterances": 7},
            ).status_code
            == 422
        )





async def test_kokoro_wav_generated_after_group_memory_revoke_never_reaches_xiaozhi(
    settings, monkeypatch,
):
    """A long Kokoro HTTP response is not authorization to transmit old secrets."""
    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = True
    settings.voice_memory_tools_enabled = True
    for index, robot in enumerate(settings.robots[:2]):
        robot.device_id = f"mac-0{index + 1}"
    monkeypatch.setenv(settings.speech_bridge_token_env, "p" * 32)
    calls = []

    class Response:
        def __init__(self, content=b""):
            self.content = content

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    class Client:
        async def post(self, url, **kwargs):
            calls.append(url)
            if url.endswith("/v1/audio/speech"):
                settings.voice_memory_tools_enabled = False
                return Response(b"RIFFsynthetic-wav-fixture")
            if url.endswith("/speak"):
                raise AssertionError("Revoked group memory reached Xiaozhi")
            return Response()

    class Chat:
        async def reply(self, history):
            return "The model had prepared a private spoken sentence"

    speaker = KokoroHeadSpeaker(settings, Client())
    conversation = Conversation(settings, Chat(), speaker)
    with pytest.raises(RuntimeError, match="Speech permission revoked during synthesis"):
        await conversation.run(
            ["robot-01", "robot-02"], "Talk about a private memory", 2,
        )
    assert conversation.active is None
    assert sum(url.endswith("/v1/audio/speech") for url in calls) == 1
    assert not any(url.endswith("/speak") for url in calls)
    assert any(url.endswith("/interrupt") for url in calls)


async def test_empty_ollama_stream_never_creates_phantom_social_speech(
    settings, tmp_path,
):
    """An empty stream is a failed turn, not a peer statement or memory."""
    class EmptyStream:
        async def stream_reply(self, history):
            if False:
                yield "Not actually sent"

    memory = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    speaker = SimulatedSpeaker()
    conversation = Conversation(settings, EmptyStream(), speaker, memory=memory)
    with pytest.raises(RuntimeError, match="without spoken segments"):
        await conversation.run(
            ["robot-01", "robot-02"], "Describe a recent toy", utterances=2
        )
    assert speaker.spoken == []
    assert conversation.active is None
    assert memory.count("robot-01") == 0
    assert memory.count("robot-02") == 0
    assert not any(
        item["role"] == "assistant"
        for history in conversation.histories.values()
        for item in history
    )



@pytest.mark.parametrize("permission", ["voice_memory", "fleet_sharing"])
async def test_private_group_consent_revoked_while_model_thinks_sends_no_audio(
    settings, tmp_path, permission,
):
    """Loaded memories cannot outlive consent through a slow peer model turn."""
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    settings.fleet_text_sharing_enabled = True
    memory = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    memory.remember(
        "robot-01", "saved_key_001",
        "Secret cobalt key seen earlier this week",
        kind="key", source_robot="robot-01", witnessed=True,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowChat:
        prompts = []

        async def reply(self, history):
            self.prompts.append(history)
            entered.set()
            await release.wait()
            return "I remember the owner's private cobalt key."

    chat = SlowChat()
    speaker = SimulatedSpeaker()
    c = Conversation(settings, chat, speaker, memory=memory)
    task = asyncio.create_task(c.run(
        ["robot-01", "robot-02"], "What do you remember?", 2,
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert "Secret cobalt key" in str(chat.prompts)
        if permission == "voice_memory":
            settings.voice_memory_tools_enabled = False
        else:
            settings.fleet_text_sharing_enabled = False
        release.set()
        with pytest.raises(RuntimeError, match="Group conversation consent revoked"):
            await asyncio.wait_for(task, timeout=3)
        assert c.active is None
        assert speaker.spoken == []
        assert memory.count("robot-01") == 1
        assert memory.count("robot-02") == 0
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_group_stream_revocation_stops_next_segment_and_never_shares_partial(
    settings, tmp_path,
):
    """Only already sent words stay private; peers never inherit a partial reply."""
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    settings.fleet_text_sharing_enabled = True
    memory = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowStream:
        async def stream_reply(self, history):
            yield "The first phrase."
            entered.set()
            await release.wait()
            yield "A private second phrase."

    speaker = SimulatedSpeaker()
    c = Conversation(settings, SlowStream(), speaker, memory=memory)
    task = asyncio.create_task(c.run(
        ["robot-01", "robot-02"], "Say something", 2,
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert speaker.spoken == [("robot-01", "The first phrase.")]
        settings.fleet_text_sharing_enabled = False
        release.set()
        with pytest.raises(RuntimeError, match="Group conversation consent revoked"):
            await asyncio.wait_for(task, timeout=3)
        assert c.active is None
        assert speaker.spoken == [("robot-01", "The first phrase.")]
        assert memory.count("robot-02") == 0
        own = memory.recent("robot-01")
        assert len(own) == 1
        assert "playback unverified" in own[0].summary
        assert "The first phrase." in own[0].summary
        assert "A private second phrase." not in str(own)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_conversation_six_total_alternating_independent_histories(settings):
    speaker = SimulatedSpeaker()
    c = Conversation(settings, SimulatedChat(), speaker)
    result = await c.run(["robot-01", "robot-02"], "hello")
    assert len(result) == 6 and len(speaker.spoken) == 6
    assert [r["robot_id"] for r in result] == ["robot-01", "robot-02"] * 3
    assert c.histories["robot-01"] is not c.histories["robot-02"]
    assert any("said:" in entry["content"] for entry in c.histories["robot-02"])
    with pytest.raises(ValueError):
        await c.run(["robot-01", "robot-02"], "hello", 7)


async def test_group_chat_uses_each_pet_own_live_audio_sensor_and_tool_context(settings):
    import time
    from types import SimpleNamespace
    from desk_robot.multimodal import CameraFrameHub

    settings.voice_vision_tools_enabled = True
    settings.fleet_text_sharing_enabled = True
    hub = CameraFrameHub(["robot-01", "robot-02"])
    now = time.monotonic()
    hub.notify("robot-01", "petting_zone", now)
    hub.remember_heard("robot-01", "asr_one", "Can we play hide the key?", now)
    hub.remember_tool(
        "robot-02", "robot_status", "backend=stepper_28byj48; armed=False", now,
    )
    conversation = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    conversation.multimodal = SimpleNamespace(hub=hub)
    await conversation.run(["robot-01", "robot-02"], "Play a tiny game", 2)
    own = conversation.histories["robot-01"][1]["content"]
    peer = conversation.histories["robot-02"][1]["content"]
    assert "Recent model ASR guess" in own
    assert "Can we play hide the key?" in own
    assert "Physical sensor edge: petting_zone" in own
    assert "Recent head telemetry" not in own
    assert "Recent head telemetry" in peer
    assert "Can we play hide the key?" not in peer
    assert "Physical sensor edge: petting_zone" not in peer
    assert "not physical action permits" in own
    assert "not physical action permits" in peer



async def test_hardware_group_conversation_does_not_persist_peer_speech_without_sharing(
    settings, tmp_path,
):
    """A shared speaker floor does not grant cross-pet SQLite retention."""
    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = False
    ids = ["robot-01", "robot-02"]
    memory = MemoryStore(tmp_path, ids)
    agent = Conversation(settings, SimulatedChat(), SimulatedSpeaker(), memory=memory)
    await agent.run(ids, "Two robots talking aloud", 2)
    first = memory.recent("robot-01")
    second = memory.recent("robot-02")
    assert len(first) == len(second) == 1
    assert all(item.kind == "own_utterance" for item in first + second)
    assert all(item.source_robot == "robot-01" for item in first)
    assert all(item.source_robot == "robot-02" for item in second)

    settings.fleet_text_sharing_enabled = True
    await agent.run(ids, "Now sharing is permitted", 2)
    first = memory.recent("robot-01")
    second = memory.recent("robot-02")
    assert len(first) == len(second) == 3
    assert sum(item.kind == "peer_utterance" for item in first) == 1
    assert sum(item.kind == "peer_utterance" for item in second) == 1
    assert all(not item.witnessed for item in first + second
               if item.kind == "peer_utterance")



async def test_group_peer_memory_revoked_inside_sqlite_write_is_compensated(
    settings, tmp_path, monkeypatch,
):
    """A completed peer INSERT during opt out must not survive in SQLite."""
    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = True
    ids = ["robot-01", "robot-02"]
    memory = MemoryStore(tmp_path, ids)
    original = memory.remember
    peer_writes = []

    def revoke_during_peer_write(robot_id, event_id, summary, **kwargs):
        inserted = original(robot_id, event_id, summary, **kwargs)
        if kwargs["kind"] == "peer_utterance":
            peer_writes.append((robot_id, event_id, inserted))
            settings.fleet_text_sharing_enabled = False
        return inserted

    monkeypatch.setattr(memory, "remember", revoke_during_peer_write)
    speaker = SimulatedSpeaker()
    conversation = Conversation(
        settings, SimulatedChat(), speaker, memory=memory,
    )
    with pytest.raises(RuntimeError, match="Group conversation consent revoked"):
        await conversation.run(ids, "A simple pet greeting", 2)
    assert len(peer_writes) == 1
    assert peer_writes[0][0] == "robot-02"
    assert peer_writes[0][2] is True
    own = memory.recent("robot-01")
    assert len(own) == 1
    assert own[0].kind == "own_utterance"
    assert own[0].source_robot == "robot-01"
    assert memory.count("robot-02") == 0
    assert conversation.active is None



async def test_hardware_group_memory_respects_fleet_sharing_consent(
    settings, tmp_path,
):
    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = False
    settings.voice_memory_tools_enabled = True
    ids = ["robot-01", "robot-02"]
    store = MemoryStore(tmp_path, ids)
    store.remember(
        "robot-01", "private_event", "A sensitive private remembered detail",
        kind="object", source_robot="robot-01", witnessed=True,
    )
    store.set_core_fact("robot-01", "private_preference", "private value")
    agent = Conversation(settings, SimulatedChat(), SimulatedSpeaker(), memory=store)
    await agent.run(ids, "Talk about a toy game", 2)
    assert "sensitive private" not in str(agent.histories)
    assert "private_preference" not in str(agent.histories)
    settings.fleet_text_sharing_enabled = True
    settings.voice_memory_tools_enabled = False
    await agent.run(ids, "Talk about a toy game", 2)
    assert "sensitive private" not in str(agent.histories)
    assert "private_preference" not in str(agent.histories)
    settings.voice_memory_tools_enabled = True
    await agent.run(ids, "Talk about the sensitive private detail", 2)
    assert "private_preference" in agent.histories["robot-01"][0]["content"]


async def test_group_chat_never_exposes_live_asr_without_fleet_text_consent(settings):
    import time
    from types import SimpleNamespace
    from desk_robot.multimodal import CameraFrameHub

    settings.voice_vision_tools_enabled = True
    settings.fleet_text_sharing_enabled = False
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.remember_heard(
        "robot-01", "asr_private", "A private conversation about my keys",
        time.monotonic(),
    )
    agent = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    agent.multimodal = SimpleNamespace(hub=hub)
    await agent.run(["robot-01", "robot-02"], "Discuss a tiny game", 2)
    assert all(
        "A private conversation about my keys" not in
        agent.histories[robot_id][1]["content"]
        for robot_id in ("robot-01", "robot-02")
    )


async def test_group_chat_does_not_expose_revoked_private_memory_tool_result(
    settings,
):
    import time
    from types import SimpleNamespace
    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = True
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.remember_tool(
        "robot-01", "memory_recall",
        "The user's private key location is under the green mug",
        time.monotonic(),
    )
    agent = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    agent.multimodal = SimpleNamespace(hub=hub)
    await agent.run(["robot-01", "robot-02"], "Tell a harmless riddle", 2)
    assert "green mug" not in str(agent.histories)
    settings.voice_memory_tools_enabled = True
    await agent.run(["robot-01", "robot-02"], "Tell a harmless riddle", 2)
    assert "green mug" in str(agent.histories["robot-01"])
    assert "green mug" not in str(agent.histories["robot-02"][0])


async def test_unknown_robot_does_not_poison_future_conversation(settings):
    c = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    with pytest.raises(KeyError):
        await c.run(["robot-01", "wrong"], "hello")
    assert c.active is None
    assert len(await c.run(["robot-01", "robot-02"], "hello", 1)) == 1


async def test_five_pet_memory_context_does_not_block_live_voice_loop(settings):
    import threading

    speaker = SimulatedSpeaker()
    c = Conversation(settings, SimulatedChat(), speaker)
    entered = threading.Event()
    release = threading.Event()
    original = c._persona_with_memory

    def slow_sqlite_context(robot):
        entered.set()
        release.wait(timeout=1.0)
        return original(robot)

    c._persona_with_memory = slow_sqlite_context
    task = asyncio.create_task(c.run(["robot-01", "robot-02"], "hello", 2))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 0.5), 0.7)
        # A blocking SQLite read would stall this direct real time callback.
        await asyncio.wait_for(asyncio.sleep(0.005), timeout=0.07)
        await asyncio.wait_for(c.stop(), timeout=0.3)
        assert task.cancelled()
        assert c.active is None
        assert speaker.spoken == []
    finally:
        release.set()


async def test_memory_context_error_releases_fleet_owner(settings):
    c = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    original = c._persona_with_memory

    def failed_sqlite_context(_robot):
        raise OSError("failed to read local SQLite memory")

    c._persona_with_memory = failed_sqlite_context
    with pytest.raises(OSError, match="SQLite"):
        await c.run(["robot-01", "robot-02"], "hello", 2)
    assert c.active is None
    c._persona_with_memory = original
    assert len(await c.run(["robot-01", "robot-02"], "recovered", 2)) == 2


async def test_conversation_cancellation_releases_session(settings):
    class SlowSpeaker(SimulatedSpeaker):
        async def say(self, robot, text):
            await asyncio.sleep(20)

    c = Conversation(settings, SimulatedChat(), SlowSpeaker())
    task = asyncio.create_task(c.run(["robot-01", "robot-02"], "hello"))
    await asyncio.sleep(0.01)
    with pytest.raises(RuntimeError, match="active"):
        await c.run(["robot-01", "robot-02"], "hello")
    await c.stop()
    assert task.cancelled() and c.active is None


async def test_five_robot_social_history_labels_observation_and_speech_correctly(settings, tmp_path):
    # Five distinct SQLite stores and personas; speech is not visual evidence.
    ids = ["robot-01", "robot-02", "robot-03", "robot-04", "robot-05"]
    settings.robots = [
        settings.robots[0].model_copy(update={"id": robot_id, "name": robot_id})
        for robot_id in ids
    ]
    memory = MemoryStore(tmp_path, ids)
    memory.remember(
        "robot-01", "camera_event", "A key appeared",
        kind="key", source_robot="robot-01", witnessed=True,
    )
    memory.remember(
        "robot-02", "camera_event", "A key appeared",
        kind="key", source_robot="robot-01", witnessed=False,
    )
    speaker = SimulatedSpeaker()
    c = Conversation(settings, SimulatedChat(), speaker, memory=memory)
    transcripts = await c.run(ids, "Describe a new game", 5)
    assert [line["robot_id"] for line in transcripts] == ids
    assert len(speaker.spoken) == 5
    assert "I observed: A key appeared" in c._persona_with_memory(settings.robots[0])
    assert "robot-01 reported: A key appeared" in c._persona_with_memory(settings.robots[1])
    for robot_id in ids:
        records = memory.recent(robot_id)
        assert any(m.kind == "own_utterance" and m.source_robot == robot_id
                   and m.witnessed for m in records)
        assert sum(m.kind == "peer_utterance" and not m.witnessed for m in records) == 4
        assert memory.count(robot_id) == (6 if robot_id in ids[:2] else 5)
    context = c._persona_with_memory(settings.robots[1])
    assert "I said: " in context
    assert "robot-01 said (peer report, not my sighting): " in context
    assert "I witnessed: I see a candy" not in context
    assert c.histories[ids[0]] is not c.histories[ids[1]]


async def test_group_prompts_never_promote_forged_peer_memory_to_firsthand(settings, tmp_path):
    ids = ["robot-01", "robot-02"]
    memory = MemoryStore(tmp_path, ids)
    # Deliberately inconsistent provenance must remain attributed to its source
    # in both the persona and topic-specific retrieval paths.
    memory.remember(
        "robot-02", "forged_utterance", "I picked up a key",
        kind="own_utterance", source_robot="robot-01", witnessed=True,
    )
    memory.remember(
        "robot-02", "foreign_asr", "The user asked for a move",
        kind="heard_human", source_robot="robot-01", witnessed=True,
    )
    c = Conversation(settings, SimulatedChat(), SimulatedSpeaker(), memory=memory)
    persona = c._persona_with_memory(settings.robot("robot-02"))
    assert "robot-01 reported: I picked up a key" in persona
    assert "robot-01 reported uncertain human speech" in persona
    await c.run(ids, "picked up a key", 1)
    prompt = c.histories["robot-02"][1]["content"]
    assert "robot-01 reported: I picked up a key" in prompt
    assert "I said previously: I picked up a key" not in prompt
