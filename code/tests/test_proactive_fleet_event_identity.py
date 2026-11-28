"""Physical interactions are per-pet; repeated shared camera scenes are not."""
from __future__ import annotations

import asyncio
import time
from io import BytesIO
from types import SimpleNamespace

import pytest
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.multimodal import CameraFrameHub
from desk_robot.pet import PetController
from desk_robot.runtime import Runtime
from desk_robot.simulator import SimulatedSpeaker
from desk_robot.vision import SceneChange, VisualChangeGate
from PIL import Image, ImageDraw


def isolated_pet(settings):
    pet = PetController(
        settings, {}, SimpleNamespace(active=None), None, None,
        speech_cooldown=0.0, interaction_cooldown=0.0, group_window=3.0,
    )
    for state in pet.states.values():
        state.enabled = True

    async def no_audio(*args, **kwargs):
        return None

    pet._speak = no_audio
    return pet


@pytest.mark.asyncio
async def test_identical_taps_on_two_distinct_heads_are_independent_events(settings):
    pet = isolated_pet(settings)
    touch = SceneChange("touch_tap", "Physical head touched", 1.0)
    first = pet.states["robot-01"]
    second = pet.states["robot-02"]

    pet._consider_speech("robot-01", touch, first.generation)
    assert pet._speech_robot == "robot-01"
    await pet._speech_task
    pet._consider_speech("robot-02", touch, second.generation)
    assert pet._speech_robot == "robot-02"
    assert second.suppressed == 0
    await pet._speech_task
    assert len(pet._event_kinds) == 2


@pytest.mark.asyncio
async def test_identical_camera_guess_across_heads_remains_deduplicated(settings):
    pet = isolated_pet(settings)
    scene = SceneChange("object", "A blue object may be on the desk", 0.99)
    first = pet.states["robot-01"]
    second = pet.states["robot-02"]

    pet._consider_speech(
        "robot-01", scene, first.generation, camera_derived=True,
    )
    await pet._speech_task
    pet._consider_speech(
        "robot-02", scene, second.generation, camera_derived=True,
    )
    assert second.suppressed == 1
    assert second.last_initiative_suppression == "quiet_voice_or_group_budget"
    assert len(pet._event_kinds) == 1


@pytest.mark.asyncio
async def test_real_touch_is_not_silenced_by_passive_120_second_group_budget(settings):
    """Twelve seconds applies to deliberate contact, never passive greetings."""
    pet = PetController(
        settings, {}, SimpleNamespace(active=None), None, None,
        speech_cooldown=120.0, interaction_cooldown=12.0, group_window=3.0,
    )
    for state in pet.states.values():
        state.enabled = True

    async def no_audio(*args, **kwargs):
        return None

    pet._speak = no_audio
    pet._group_last_spoken = time.monotonic() - 20.0
    state = pet.states["robot-01"]

    pet._consider_speech(
        "robot-01", SceneChange("object", "A new blue item appeared", 0.99),
        state.generation, camera_derived=True,
    )
    assert pet._speech_task is None
    assert state.last_initiative_suppression == "quiet_voice_or_group_budget"

    pet._consider_speech(
        "robot-01", SceneChange("touch_tap", "Actual contact", 1.0),
        state.generation,
    )
    assert pet._speech_task is not None
    assert pet._speech_robot == "robot-01"
    await pet._speech_task

    # The shorter physical-interaction window does not let an unrelated
    # passive camera observation bypass the normal 120 second voice budget.
    pet._group_last_spoken = time.monotonic() - 20.0
    pet._consider_speech(
        "robot-01", SceneChange("object", "A second different item", 0.99),
        state.generation, camera_derived=True,
    )
    assert state.last_initiative_suppression == "quiet_voice_or_group_budget"


@pytest.mark.asyncio
@pytest.mark.parametrize("replayed", [False, True])
async def test_authenticated_camera_receipt_to_fleet_and_speaker(
    settings, tmp_path, replayed,
):
    """Replay the normal observer, private memory, peer fanout and audio owner."""
    settings.fleet_text_sharing_enabled = True
    settings.fleet_text_auto_fanout_enabled = True
    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path, ids)
    speaker = SimulatedSpeaker()
    change = SceneChange("key", "A flat key appeared on the desk", 0.96)

    class Chat:
        async def reply(self, history):
            return "That key looks interesting!"

    class Scene:
        async def compare(self, before, after):
            assert before != after
            return change

    conversation = Conversation(settings, Chat(), speaker, memory=memory)
    pet = PetController(
        settings, {}, conversation, memory, Scene(),
        interval=0.01, speech_cooldown=0,
    )
    hub = CameraFrameHub(ids)
    pet.multimodal = SimpleNamespace(
        hub=hub, stream_owns_camera=lambda rid: rid == "robot-01",
    )
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 37

    white = Image.new("RGB", (128, 96), "white")
    red = white.copy()
    ImageDraw.Draw(red).rectangle((40, 26, 78, 65), fill=(220, 20, 20))

    def jpeg(image):
        out = BytesIO()
        image.save(out, "JPEG")
        return out.getvalue()

    images = [jpeg(white), jpeg(red), jpeg(red)]
    received = time.monotonic()
    identity = (5, 13, 1400000)
    event_id = "camera_robot-01_00000005_0000000d_155cc0"
    if replayed:
        # A prior authenticated receipt may survive a Mac restart even
        # though the new controller's in-memory speech window is empty.
        assert await pet._store_observation(
            "robot-01", change, camera_derived=True,
            camera_received_at=received, camera_source_identity=identity,
        )
    for index, image in enumerate(images):
        hub.offer_prepared(
            "robot-01", (image, VisualChangeGate._reduced(image), 0.0),
            time.monotonic(), source="proactive",
            source_identity=(5, 11 + index, 1000000 + 200000 * index),
        )
    observer = asyncio.create_task(pet._observe("robot-01", 37))
    try:
        async with asyncio.timeout(4):
            while not (
                state.suppressed if replayed
                else state.spoken == 1 and pet._speech_task is None
            ):
                await asyncio.sleep(0.01)
        originals = [row for row in memory.recent("robot-01") if row.kind == "key"]
        copies = [row for row in memory.recent("robot-02") if row.kind == "key"]
        assert len(originals) == len(copies) == 1
        assert originals[0].event_id == copies[0].event_id == event_id
        assert originals[0].witnessed and not copies[0].witnessed
        assert originals[0].source_robot == copies[0].source_robot == "robot-01"
        if replayed:
            assert state.last_initiative_suppression == "camera_receipt_not_admitted"
            assert state.events == state.spoken == 0
            assert speaker.spoken == []
            assert not pet._admitted_event_kinds
        else:
            assert state.events == state.spoken == 1
            assert speaker.spoken == [("robot-01", "That key looks interesting!")]
        assert state.last_error is None
    finally:
        state.enabled = False
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
        await pet.close()


@pytest.mark.asyncio
async def test_runtime_replayed_touch_release_dispatches_once(settings, tmp_path):
    """A same-count stale report cannot rewind a completed gesture."""
    settings.memory_dir = tmp_path
    settings.fleet_text_sharing_enabled = True
    settings.fleet_text_auto_fanout_enabled = True
    runtime = Runtime(settings)
    pet = runtime.pet
    pet.speech_cooldown = 0
    pet.interaction_cooldown = 0
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 7
    head = pet.heads["robot-01"]
    speaker = runtime.conversation.speaker

    class Chat:
        async def reply(self, history):
            return "I felt that tap."

    runtime.conversation.chat = Chat()

    async def report(count, taps, *, boot=19, typed=True):
        touch = {"active": False, "count": count}
        if typed:
            touch.update(tap_count=taps, double_count=0, hold_count=0)
        head.replay_body_status({
            "robot_id": "robot-01",
            "imu": {"boot_id": boot},
            "side_ranges": {"boot_id": boot},
            "touch": touch,
        })
        await pet._touch_from_body("robot-01", 7)
        task = pet._speech_task
        if task is not None:
            await asyncio.wait_for(task, timeout=4)

    def taps(robot_id):
        return [
            row for row in runtime.memory.recent(robot_id)
            if row.kind == "touch_tap"
        ]

    try:
        await report(0, 0)  # boot baseline
        await report(1, 0)  # press, classifier has not completed the tap
        await report(1, 1)  # release, one genuine event
        assert state.events == state.spoken == 1
        assert speaker.spoken == [("robot-01", "I felt that tap.")]
        first, copy = taps("robot-01")[0], taps("robot-02")[0]
        assert first.event_id == copy.event_id
        assert first.witnessed and not copy.witnessed
        assert first.source_robot == copy.source_robot == "robot-01"

        await report(1, 0)  # late copy of the same raw press
        assert state.last_touch_events["tap_count"] == 1
        await report(0, 0)  # delayed zero from the same authenticated boot
        assert state.last_touch_count == 1
        await report(1, 1)  # same release again
        assert len(taps("robot-01")) == len(taps("robot-02")) == 1
        assert state.events == state.spoken == 1
        assert len(speaker.spoken) == 1

        await report(2, 2, typed=False)  # cannot downgrade the typed source
        assert state.events == 1 and state.last_touch_count == 1
        await report(2, 2)  # a distinct real counter edge is still recorded
        assert len(taps("robot-01")) == len(taps("robot-02")) == 2
        assert state.events == 2

        # A real reboot sets a baseline; genuine uint32 rollover advances it.
        await report(0xffffffff, 0xffffffff, boot=20)
        await report(0, 0, boot=20)
        await report(0xffffffff, 0xffffffff, boot=20)  # retired pre-wrap value
        await report(0, 0, boot=20)
        assert state.events == 3 and state.last_touch_count == 0
        assert len(taps("robot-01")) == len(taps("robot-02")) == 3
        assert {row.event_id for row in taps("robot-01")} == {
            row.event_id for row in taps("robot-02")
        }
        assert not head.commands  # no autonomous physical authority
    finally:
        await runtime.close()



@pytest.mark.asyncio
async def test_five_camera_witnesses_keep_distinct_receipts_one_initiative(
    settings, tmp_path,
):
    """One shared scene is one speech candidate, not one camera receipt."""
    from desk_robot.brain_context import compose_brain_context

    for index in range(3, 6):
        settings.robots.append(settings.robots[0].model_copy(update={
            "id": f"robot-{index:02d}", "name": f"Pet {index}",
            "token_env": f"DESK_ROBOT_HEAD_{index:02d}_TOKEN",
        }))
    settings.fleet_text_sharing_enabled = True
    settings.fleet_text_auto_fanout_enabled = True
    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path, ids)
    pet = isolated_pet(settings)
    pet.memory = memory
    pet.group_window = 30.0
    change = SceneChange("key", "A silver key appeared on the desk", 0.96)
    identities = {
        rid: (5 + index, 13, 1400000 + index * 10000)
        for index, rid in enumerate(ids)
    }
    offered = {}
    for rid, identity in identities.items():
        received = time.monotonic()
        assert await pet._store_observation(
            rid, change, camera_derived=True, camera_received_at=received,
            camera_source_identity=identity,
        )
        offered[rid] = received
        pet._consider_speech(
            rid, change, pet.states[rid].generation,
            camera_derived=True, received_at=received,
        )
        if pet._speech_task is not None:
            await pet._speech_task

    assert len(pet._admitted_event_kinds) == 1
    assert sum(state.suppressed for state in pet.states.values()) == 4
    for receiver in ids:
        records = memory.recent(receiver)
        assert len(records) == 5
        assert sum(row.witnessed for row in records) == 1
        assert {row.source_robot for row in records} == set(ids)
        for row in records:
            assert row.witnessed is (row.source_robot == receiver)
            assert row.confidence == 0.96
            source = memory.get_episode(row.source_robot, row.event_id)
            assert source is not None and source.witnessed
            assert row.observed_at == source.observed_at
            receipt = memory.get_camera_provenance(receiver, row.event_id)
            assert receipt is not None
            assert receipt.source_identity == identities[row.source_robot]
        peer = next(row for row in records if not row.witnessed)
        text = compose_brain_context([peer], [], []).recent
        assert f"{peer.source_robot} reported a camera model guess" in text
        assert "s old; confidence 0.96" in text
        assert "My camera model" not in text

    # Same authenticated device completion is not a new observation.
    assert not await pet._store_observation(
        ids[0], change, camera_derived=True, camera_received_at=offered[ids[0]],
        camera_source_identity=identities[ids[0]],
    )
    assert all(memory.count(rid) == 5 for rid in ids)


@pytest.mark.asyncio
async def test_proactive_context_filters_old_peer_stories_without_sharing(
    settings, tmp_path,
):
    memory = MemoryStore(tmp_path, [robot.id for robot in settings.robots])
    pet = isolated_pet(settings)
    pet.memory = memory
    rid = "robot-02"
    assert memory.remember(
        rid, "peer_key", "Secret silver key story", kind="key",
        source_robot="robot-01", witnessed=False,
    )
    assert memory.remember(
        rid, "own_key", "Own silver key observation", kind="key",
        source_robot=rid, witnessed=True,
    )
    change = SceneChange("key", "silver key", 0.96)
    settings.fleet_text_sharing_enabled = True
    context = await pet._load_proactive_context(rid, change)
    assert "Secret silver key story" in context[1].recent
    settings.fleet_text_sharing_enabled = False
    context = await pet._load_proactive_context(rid, change)
    assert "Secret silver key story" not in context[1].recent
    assert "Own silver key observation" in context[1].recent
    assert all(row.witnessed for row in context[0])


@pytest.mark.parametrize("observe_disconnect", [True, False])
def test_voice_session_replacement_retires_only_its_live_context(observe_disconnect):
    robot, peer = "robot-01", "robot-02"
    hub = CameraFrameHub([robot, peer])
    runtime = Runtime.__new__(Runtime)
    runtime.multimodal = SimpleNamespace(hub=hub)
    runtime._on_voice_generations({robot: 7, peer: 4})
    now = time.monotonic()
    for rid in (robot, peer):
        hub.remember_tool(rid, "robot_status", f"Status of {rid}", now)
        assert hub.remember_heard(rid, f"old_{rid}", "Previous question", now)
        hub.remember_spoken(rid, "Already transmitted", now)
    peer_tools = tuple(hub.tool_history[peer])
    peer_heard = tuple(hub.heard_history[peer])
    sent = tuple(hub.spoken_history[robot])
    if observe_disconnect:
        runtime._on_voice_generations({peer: 4})
        assert robot not in runtime._voice_turn_generations
        assert not hub.recent_tool_context(robot, now)
        assert not hub.heard_history[robot]

    # A reconnect can complete between polls, with no observed absent entry.
    runtime._on_voice_generations({robot: 8, peer: 4})
    assert not hub.recent_tool_context(robot, now)
    assert not hub.heard_history[robot]
    assert tuple(hub.tool_history[peer]) == peer_tools
    assert tuple(hub.heard_history[peer]) == peer_heard
    assert tuple(hub.spoken_history[robot]) == sent
    assert not hub.remember_heard(robot, f"old_{robot}", "Replay", time.monotonic())

    fresh_at = time.monotonic()
    hub.remember_tool(robot, "robot_status", "Fresh status", fresh_at)
    assert hub.remember_heard(robot, "new_session", "New question", fresh_at)
    runtime._on_voice_generations({robot: 8, peer: 4})
    assert hub.recent_tool_context(robot, fresh_at)[0]["summary"] == "Fresh status"
    assert hub.heard_history[robot][0][0] == "new_session"
    assert not hub.recent_tool_context(robot, fresh_at + 31)
    assert not hub.recent_tool_context(peer, now + 31)
