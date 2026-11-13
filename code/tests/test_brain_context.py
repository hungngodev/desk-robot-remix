"""Pure context budgets, truthful provenance and one physical speech owner."""
from __future__ import annotations

import time
from types import SimpleNamespace

from desk_robot.brain_context import compose_brain_context, repeated_spontaneous_line
from desk_robot.conversation import Conversation
from desk_robot.memory import CoreFact, Memory, MemoryStore
from desk_robot.multimodal import CameraFrameHub
from desk_robot.pet import PetController
from desk_robot.simulator import SimulatedSpeaker
from desk_robot.vision import SceneChange


def episode(robot, eid, kind, summary, source=None, witnessed=True):
    return Memory(
        robot_id=robot, event_id=eid, source_robot=source or robot,
        witnessed=witnessed, kind=kind, summary=summary,
        observed_at=time.time(), confidence=0.8,
    )


def test_context_provenance_and_source_types_are_not_interchangeable():
    recent = [
        episode("robot-01", "key001", "key", "A key appeared"),
        episode("robot-01", "peer001", "peer_utterance",
                "I saw a dragon", source="robot-02", witnessed=False),
        episode("robot-01", "asr001", "heard_human",
                "Maybe I heard a question about keys"),
        episode("robot-01", "key001", "key", "A key appeared"),  # duplicate
    ]
    core = [CoreFact("robot-01", "favorite_game", "chess", time.time())]
    timeline = [
        {"channel": "camera", "kind": "speech", "content": b"raw bytes"},
        {"channel": "sensor", "kind": "touch_tap"},
        {"channel": "tool", "kind": "visual_look",
         "content": "Might be a silver key"},
        {"channel": "robot_speech", "kind": "own_utterance",
         "content": "Let's try a guessing game!"},
    ]
    result = compose_brain_context(recent, core, timeline)
    assert result.recent.count("A key appeared") == 1
    assert "I observed: A key appeared" in result.recent
    assert "I heard robot-02 say: I saw a dragon" in result.recent
    assert "uncertain transcription" in result.recent
    assert "favorite_game: chess" in result.core
    assert "XIAO frame received (contents not inferred)" in result.interaction
    assert "Physical sensor edge: touch_tap" in result.interaction
    assert "Earlier local VLM guess, not fresh sighting" in result.interaction
    assert "playback unverified" in result.interaction
    assert "guessing game" in result.interaction
    assert "raw bytes" not in result.interaction
    assert len(result.recent) <= 600
    assert len(result.core) <= 500
    assert len(result.interaction) <= 400



def test_peer_utterance_cannot_become_firsthand_visual_evidence():
    # Even an incorrectly marked witnessed peer message must not be
    # promoted into a camera observation by the prompt composer.
    peer = episode("robot-01", "peer-witness-1", "peer_utterance",
                   "There is a key on the desk", source="robot-02",
                   witnessed=True)
    context = compose_brain_context([peer], [], [])
    assert "robot-02 said (peer report, not my sighting)" in context.recent
    assert "I observed" not in context.recent
    assert "I heard robot-02 say" not in context.recent

def test_context_budget_is_constant_even_with_many_long_model_outputs():
    memory = [
        episode("robot-01", f"event{i}", "object", "x" * 300)
        for i in range(150)
    ]
    core = [
        CoreFact("robot-01", f"favorite{i}", "y" * 200, time.time())
        for i in range(50)
    ]
    timeline = [
        {"channel": "tool", "kind": "visual_look", "content": "z" * 2000}
        for _ in range(30)
    ]
    result = compose_brain_context(memory, core, timeline)
    assert len(result.recent) <= 600
    assert len(result.core) <= 500
    assert len(result.interaction) <= 400
    assert "\n" not in result.recent + result.core + result.interaction


async def test_pet_brain_uses_same_timeline_without_a_second_media_owner(
    settings, tmp_path
):
    ids = [r.id for r in settings.robots]
    memory = MemoryStore(tmp_path, ids)
    memory.set_core_fact("robot-01", "favorite_game", "hide the key")
    prompts = []

    class ThoughtfulChat:
        async def reply(self, history):
            prompts.append(history)
            return "That key is back! Want to try a tiny hiding game?"

    speaker = SimulatedSpeaker()
    conversation = Conversation(settings, ThoughtfulChat(), speaker,
                                memory=memory)
    pet = PetController(settings, {}, conversation, memory, scene=None)
    hub = CameraFrameHub(ids)
    now = time.monotonic()
    hub.notify("robot-01", "touch_tap", now)
    hub.remember_tool("robot-01", "visual_look",
                      "A silver key might be there", now)
    pet.multimodal = SimpleNamespace(hub=hub)
    pet.states["robot-01"].enabled = True
    try:
        await pet._speak(
            "robot-01", SceneChange(
                "key", "A silver key appeared on the table", 0.97
            ), pet.states["robot-01"].generation,
            offered_at=time.monotonic(),
        )
        assert len(speaker.spoken) == 1
        prompt = prompts[0][1]["content"]
        assert "favorite_game: hide the key" in prompt
        assert "Physical sensor edge: touch_tap" in prompt
        assert "Earlier local VLM guess" in prompt
        assert "not fresh sighting" in prompt
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
        spoken = [item for item in hub.interaction_timeline(
            "robot-01", time.monotonic()
        ) if item["channel"] == "robot_speech"]
        assert len(spoken) == 1
        assert "hiding game" in spoken[0]["content"]
        assert spoken[0]["playback_verified"] is False
        assert memory.count("robot-02") == 0
    finally:
        await pet.close()


def test_novelty_checks_use_only_recent_words_this_pet_actually_sent():
    now = time.time()
    our_line = episode(
        "robot-01", "spoken1", "own_utterance",
        "Want to try guessing where the silver key is hiding?"
    )
    old_line = Memory(
        "robot-01", "spoken0", "robot-01", True, "own_utterance",
        "Let's count the stars together", now - 7200, .9,
    )
    peer_line = episode(
        "robot-01", "spokenpeer", "peer_utterance",
        "Want to try guessing where the silver key is hiding?",
        source="robot-02", witnessed=False,
    )
    assert repeated_spontaneous_line(
        "Want to try guessing where the silver key is hiding!",
        [our_line], now_wall=now,
    )
    assert not repeated_spontaneous_line(
        "Want to try guessing where the silver key is hiding?",
        [peer_line], now_wall=now,
    )
    assert not repeated_spontaneous_line(
        "Let's count the stars together", [old_line], now_wall=now,
    )
    assert not repeated_spontaneous_line(
        "Shall we invent a new tiny game?", [our_line], now_wall=now,
    )


async def test_repeating_an_old_spontaneous_line_is_silently_suppressed(
    settings, tmp_path
):
    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path, ids)
    said = "That key looks familiar! Want to play a tiny guessing game?"
    memory.remember(
        "robot-01", "already_spoken", said,
        kind="own_utterance", source_robot="robot-01", witnessed=True,
    )

    class RepetitiveChat:
        async def reply(self, history):
            return said

    speaker = SimulatedSpeaker()
    agent = Conversation(settings, RepetitiveChat(), speaker, memory=memory)
    pet = PetController(settings, {}, agent, memory, scene=None)
    pet.states["robot-01"].enabled = True
    try:
        await pet._speak(
            "robot-01", SceneChange("key", "A key appeared", 0.94),
            pet.states["robot-01"].generation,
            offered_at=time.monotonic(),
        )
        assert speaker.spoken == []
        assert pet.states["robot-01"].last_initiative_suppression == (
            "repetitive_spontaneous_reply"
        )
    finally:
        await pet.close()


def test_modalities_survive_dense_camera_sensor_timeline():
    from desk_robot.multimodal import CameraEvidence

    now = time.monotonic()
    hub = CameraFrameHub(["robot-01"])
    hub.remember_tool("robot-01", "visual_look", "A red key, perhaps", now - 5)
    hub.remember_spoken("robot-01", "I asked about the key", now - 4)
    hub.notify("robot-01", "human_voice", now - 2.5)
    for index, kind in enumerate((
        "touch", "touch_tap", "touch_double", "petting_zone",
        "hand_wave", "bumper", "magnet", "pir", "nearby_object",
        "side_object", "nfc_tag",
    )):
        hub.notify("robot-01", kind, now - 2.2 + index * 0.1)
    for index in range(3):
        hub.frames["robot-01"].append(CameraEvidence(
            b"jpeg", now - 0.9 + index * 0.1, 0.12, "speech"
        ))
    timeline = hub.interaction_timeline("robot-01", now, limit=5)
    channels = [cue["channel"] for cue in timeline]
    assert len(timeline) == 5
    assert set(channels) == {
        "camera", "sensor", "human_voice", "tool", "robot_speech"
    }
    assert timeline == sorted(timeline, key=lambda item: -item["age_ms"])
    result = compose_brain_context([], [], timeline)
    assert "Physical sensor edge" in result.interaction
    assert "Authenticated human voice" in result.interaction
    assert "Earlier local VLM guess" in result.interaction
    assert "playback unverified" in result.interaction
    assert "XIAO frame received" in result.interaction
    assert len(result.interaction) <= 400


def test_prompt_deduplicates_repetitive_camera_receipts_and_keeps_tool_results():
    timeline = [
        {"channel": "tool", "kind": "visual_look", "content": "The cup moved"},
        {"channel": "robot_speech", "kind": "own_utterance",
         "content": "I asked about your cup"},
        {"channel": "sensor", "kind": "touch_tap"},
    ] + [
        {"channel": "camera", "kind": "speech"}
        for _ in range(13)
    ]
    result = compose_brain_context([], [], timeline)
    assert result.interaction.count("XIAO frame received") == 1
    assert result.interaction.count("Earlier local VLM guess") == 1
    assert result.interaction.count("playback unverified") == 1
    assert "Physical sensor edge: touch_tap" in result.interaction
    assert len(result.interaction) <= 400
