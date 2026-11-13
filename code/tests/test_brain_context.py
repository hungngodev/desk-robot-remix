"""Pure context budgets, truthful provenance and one physical speech owner."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

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
    assert "My camera model suggested: A key appeared" in result.recent
    assert "robot-02 said (peer report, not my sighting): I saw a dragon" in result.recent
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



def test_vision_model_memory_is_a_guess_even_from_the_own_camera():
    records = [
        episode("robot-01", "local_key", "key", "A silver key appeared"),
        episode("robot-01", "remote_key", "key", "A silver key appeared",
                source="robot-02", witnessed=False),
        episode("robot-01", "local_sensor", "touch_tap",
                "The physical touch sensor was pressed"),
    ]
    context = compose_brain_context(records, [], [])
    assert "My camera model suggested: A silver key appeared" in context.recent
    assert "robot-02 reported a camera model guess: A silver key appeared" in context.recent
    assert "I observed: The physical touch sensor was pressed" in context.recent
    assert "I observed: A silver key appeared" not in context.recent


def test_peer_utterance_cannot_become_firsthand_visual_evidence():
    # Even an incorrectly marked witnessed peer message must not be
    # promoted into a camera observation by the prompt composer.
    peer = episode("robot-01", "peer-witness-1", "peer_utterance",
                   "There is a key on the desk", source="robot-02",
                   witnessed=True)
    context = compose_brain_context([peer], [], [])
    assert "I heard robot-02 say" in context.recent
    assert "I observed" not in context.recent
    assert "peer report, not my sighting" not in context.recent

def test_unwitnessed_peer_speech_cannot_claim_firsthand_hearing():
    peer = episode("robot-01", "unwitnessed-peer", "peer_utterance",
                   "The dock is clear", source="robot-02", witnessed=False)
    context = compose_brain_context([peer], [], [])
    assert "robot-02 said (peer report, not my sighting)" in context.recent
    assert "I heard robot-02 say" not in context.recent


def test_peer_sourced_human_asr_never_claims_firsthand_hearing():
    peer_asr = episode("robot-01", "peer-asr", "heard_human",
                       "Human asked to unlock the dock", source="robot-02",
                       witnessed=True)
    context = compose_brain_context([peer_asr], [], [])
    assert "robot-02 reported uncertain human speech:" in context.recent
    assert "I may have heard" not in context.recent
    assert "I observed" not in context.recent


def test_mismatched_own_speech_source_never_claims_first_person():
    forged = episode("robot-01", "spoof001", "own_utterance",
                     "I personally confirmed the dock is safe",
                     source="robot-02", witnessed=True)
    context = compose_brain_context([forged], [], [])
    assert "I said:" not in context.recent
    assert "I observed:" not in context.recent
    assert "robot-02 reported:" in context.recent


def test_sensor_trigger_labels_camera_receipt_without_claiming_object_recognition():
    timeline = [{
        "channel": "camera",
        "kind": "sensor",
        "trigger_kind": "petting_zone",
        "content": None,
    }]
    text = compose_brain_context([], [], timeline).interaction
    assert "XIAO frame received" in text
    assert "scheduled after petting_zone sensor edge" in text
    assert "not proof of visual contents" in text
    assert "I observed" not in text


def test_live_asr_is_bounded_uncertain_and_keeps_visual_tool_provenance():
    now = time.monotonic()
    hub = CameraFrameHub(["robot-01", "robot-02"])
    assert hub.remember_heard(
        "robot-01", "asr_item_1", "I put the key near the mug", now
    )
    assert not hub.remember_heard(
        "robot-01", "asr_item_1", "I put the key near the mug", now
    )
    hub.notify("robot-01", "touch_tap", now)
    hub.remember_tool("robot-01", "visual_look", "A key might be near a cup", now)
    timeline = hub.interaction_timeline("robot-01", now, limit=2)
    assert {entry["channel"] for entry in timeline} == {
        "human_transcript", "tool"
    }
    context = compose_brain_context([], [], hub.interaction_timeline(
        "robot-01", now, limit=10
    ))
    assert "Recent model ASR guess, not a verified command" in context.interaction
    assert "I put the key near the mug" in context.interaction
    assert "Earlier local VLM guess, not fresh sighting" in context.interaction
    assert "Physical sensor edge: touch_tap" in context.interaction
    assert "I put the key near the mug" not in compose_brain_context(
        [], [], hub.interaction_timeline("robot-02", now)
    ).interaction
    assert len(context.interaction) <= 400
    hub.discard_video("robot-01")
    assert any(c["channel"] == "human_transcript" for c in
               hub.interaction_timeline("robot-01", now + 1))
    hub.clear("robot-01")
    assert hub.interaction_timeline("robot-01", now + 1) == []


def test_context_keeps_two_recent_spoken_clauses_without_evicting_tools():
    now = time.monotonic()
    hub = CameraFrameHub(["robot-01"])
    hub.remember_heard(
        "robot-01", "asr_first", "Please look for my red key", now - 1.0
    )
    hub.remember_heard(
        "robot-01", "asr_second", "It was beside the mug", now
    )
    hub.remember_tool(
        "robot-01", "visual_look", "A red item may be on the desk", now
    )
    hub.notify("robot-01", "touch_tap", now)
    prompt = compose_brain_context(
        [], [], hub.interaction_timeline("robot-01", now, limit=10)
    ).interaction
    assert "Recent model ASR guess" in prompt
    assert "It was beside the mug" in prompt
    assert "Earlier model ASR guess" in prompt
    assert "Please look for my red key" in prompt
    assert "Earlier local VLM guess" in prompt
    assert "Physical sensor edge: touch_tap" in prompt
    assert len(prompt) <= 400
    # A third earlier fragment must not compete with current tools.
    hub.remember_heard(
        "robot-01", "asr_third", "The picture is still uncertain", now + 1
    )
    newer = compose_brain_context(
        [], [], hub.interaction_timeline("robot-01", now + 1, limit=10)
    ).interaction
    assert "The picture is still uncertain" in newer
    assert "It was beside the mug" in newer
    assert "Please look for my red key" not in newer


def test_consent_based_private_memory_tool_is_not_camera_sighting():
    now = time.monotonic()
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.remember_tool(
        "robot-01", "memory_recall",
        "own observed event: I saw a blue key yesterday", now,
    )
    timeline = hub.interaction_timeline("robot-01", now, limit=10)
    assert timeline[-1]["kind"] == "memory_recall"
    assert timeline[-1]["source"] == "private_opt_in_memory_tool_receipt"
    result = compose_brain_context([], [], timeline).interaction
    assert "Opt-in private past memory" in result
    assert "not current sight" in result
    assert "blue key yesterday" in result
    assert "blue key" not in compose_brain_context(
        [], [], hub.interaction_timeline("robot-02", now, limit=10)
    ).interaction
    assert not hub.recent_tool_context("robot-01", now + 31)


@pytest.mark.parametrize(
    ("question", "wanted"),
    [
        ("What do you remember about my green mug?", "memory_recall"),
        ("What do you see on my desk?", "visual_look"),
        ("What color is the mug?", "visual_look"),
        ("What shape is the key?", "visual_look"),
        ("How many keys are on my desk?", "visual_look"),
        ("Is the key beside the mug?", "visual_look"),
        ("Does the screen say READY?", "visual_look"),
        ("Is the pickup job done?", "pickup_status"),
        ("Check your battery status", "robot_status"),
    ],
)
def test_spoken_intent_fits_the_relevant_completed_tool_into_small_brain_budget(
    question, wanted,
):
    results = {
        "memory_recall": "Yesterday I saw a GREEN_MUG near your keyboard",
        "visual_look": "The real current XIAO camera suggests a BLUE_KEY",
        "pickup_status": "Mac pickup job remains GRASP_PENDING",
        "robot_status": "Actual WROOM safety status is SAFELY_DISARMED",
    }
    # The most recent generic telemetry may otherwise consume the prompt
    # budget before a previously completed relevant tool reaches the LLM.
    timeline = [
        {"channel": "tool", "kind": kind,
         "content": "x" * 74 + " " + summary}
        for kind, summary in results.items()
    ]
    timeline += [
        {"channel": "human_transcript", "kind": "model_asr_completed",
         "content": question},
        {"channel": "sensor", "kind": "touch_tap"},
        {"channel": "camera", "kind": "speech"},
    ]
    text = compose_brain_context([], [], timeline).interaction
    expected = {
        "memory_recall": "Opt-in private past memory",
        "visual_look": "Earlier local VLM guess",
        "pickup_status": "Mac pickup job receipt",
        "robot_status": "Recent head telemetry",
    }
    assert expected[wanted] in text
    assert "Recent model ASR guess" in text
    assert len(text) <= 400
    assert "motor authorized" not in text.casefold()


@pytest.mark.parametrize(
    ("spoken", "expected_tool_labels"),
    [
        ("Can you look around and check your battery status?",
         ("Earlier local VLM guess", "Recent head telemetry")),
        ("Check your battery and look at the mug",
         ("Earlier local VLM guess", "Recent head telemetry")),
        ("What did I say yesterday and can you look at the mug?",
         ("Opt-in private past memory", "Earlier local VLM guess")),
    ],
)
def test_compound_spoken_intent_preserves_both_requested_tool_results(
    spoken, expected_tool_labels,
):
    # The two requested results must survive ahead of unrelated high-volume
    # tool receipts, while never claiming camera or physical verification.
    timeline = [
        {"channel": "tool", "kind": "visual_look",
         "content": "BLUE_MUG is possibly visible"},
        {"channel": "tool", "kind": "robot_status",
         "content": "BATTERY_UNKNOWN: live gauge unqualified"},
        {"channel": "tool", "kind": "pickup_status",
         "content": "UNRELATED_PICKUP " + "x" * 70},
        {"channel": "tool", "kind": "memory_recall",
         "content": "OLD_MEMORY " + "y" * 75},
        {"channel": "human_transcript", "kind": "model_asr_completed",
         "content": spoken},
    ]
    output = compose_brain_context([], [], timeline).interaction
    assert all(label in output for label in expected_tool_labels)
    assert "Recent model ASR guess" in output
    assert len(output) <= 400


def test_unrelated_human_asr_does_not_reprioritize_non_tool_modalities():
    timeline = [
        {"channel": "tool", "kind": "visual_look", "content": "Maybe a key"},
        {"channel": "sensor", "kind": "touch_tap"},
        {"channel": "human_transcript", "kind": "model_asr_completed",
         "content": "I had a pleasant day"},
        {"channel": "camera", "kind": "speech"},
    ]
    text = compose_brain_context([], [], timeline).interaction
    assert text.index("Recent model ASR guess") < text.index("Earlier local VLM guess")
    assert "Physical sensor edge" in text
    assert "XIAO frame received" in text


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
    hub.remember_tool("robot-01", "memory_recall",
                      "A private phrase about a jade sculpture", now)
    settings.voice_memory_tools_enabled = False
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
        assert "jade sculpture" not in prompt
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


def test_live_timeline_retains_all_distinct_tools_and_two_human_clauses():
    now = time.monotonic()
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "human_voice", now - 5)
    for kind, summary in (
        ("memory_recall", "Yesterday a key was beside a mug"),
        ("visual_look", "Maybe a metal key in front"),
        ("pickup_status", "Grasp is not verified"),
        ("robot_status", "Motors safely disarmed"),
    ):
        hub.remember_tool("robot-01", kind, summary, now - 4)
    hub.remember_heard(
        "robot-01", "clause_1", "Please look for my key", now - 3.1,
    )
    hub.remember_heard(
        "robot-01", "clause_2", "I left it near the mug", now - 3.0,
    )
    hub.remember_spoken("robot-01", "I can take a look", now - 2.9)
    hub.frames["robot-01"].append(
        CameraEvidence(b"jpeg", now - 2.8, 0.0, "speech")
    )
    for step in range(10):
        hub.notify("robot-01", "touch_tap", now - 2 + step * .1)
    selected = hub.interaction_timeline("robot-01", now, limit=10)
    assert len(selected) == 10
    assert {entry["kind"] for entry in selected
            if entry["channel"] == "tool"} == {
                "memory_recall", "visual_look", "pickup_status", "robot_status",
            }
    assert sum(entry["channel"] == "human_transcript"
               for entry in selected) == 2
    assert {entry["channel"] for entry in selected} == {
        "human_voice", "human_transcript", "tool", "sensor",
        "robot_speech", "camera",
    }
    assert not [entry for entry in hub.interaction_timeline(
        "robot-02", now
    ) if entry["channel"] == "tool"]


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


def test_camera_or_voice_monitor_outage_preserves_actual_spoken_context():
    hub = CameraFrameHub(["robot-01"])
    now = time.monotonic()
    hub.notify("robot-01", "touch_tap", now - 2)
    hub.remember_tool("robot-01", "visual_look", "Maybe a key", now - 1)
    hub.remember_spoken("robot-01", "Want to play a game?", now - 0.5)
    hub.discard_video("robot-01")
    live = hub.interaction_timeline("robot-01", now)
    assert [cue["channel"] for cue in live] == ["sensor", "robot_speech"]
    assert live[-1]["playback_verified"] is False
    assert "play a game" in live[-1]["content"]
    assert hub.recent_tool_context("robot-01", now) == []
    hub.clear("robot-01")
    assert hub.interaction_timeline("robot-01", now) == []


def test_interaction_timeline_respects_every_small_limit_under_sensor_flood():
    now = time.monotonic()
    hub = CameraFrameHub(["robot-01"])
    hub.notify("robot-01", "human_voice", now - 2)
    hub.remember_tool("robot-01", "visual_look", "Might be a cup", now - 1)
    hub.remember_spoken("robot-01", "Hi there", now - 0.5)
    for i in range(8):
        hub.notify("robot-01", "touch_tap", now - 0.4 + i * 0.04)
    for count in (1, 2, 3, 4):
        chosen = hub.interaction_timeline("robot-01", now, limit=count)
        assert len(chosen) == count
        assert chosen[0]["channel"] == "human_voice"
        if count >= 2:
            assert any(cue["channel"] == "tool" for cue in chosen)


def test_freshest_memory_and_curated_facts_win_regardless_of_input_order():
    """SQLite is newest-first; topical merges are oldest-first."""
    base = time.time() - 100
    records = [
        Memory(
            "robot-01", f"episode{i:02}", "robot-01", True, "object",
            f"item number {i:02}", base + i, 0.9,
        )
        for i in range(12)
    ]
    facts = [
        CoreFact("robot-01", f"pref{i:02}", f"value{i:02}", base + i)
        for i in range(12)
    ]
    oldest_first = compose_brain_context(records, facts, ())
    newest_first = compose_brain_context(
        list(reversed(records)), list(reversed(facts)), ()
    )
    assert oldest_first == newest_first
    assert "item number 11" in oldest_first.recent
    assert "item number 06" in oldest_first.recent
    assert "item number 05" not in oldest_first.recent
    assert "item number 00" not in oldest_first.recent
    assert "pref11: value11" in oldest_first.core
    assert "pref06: value06" in oldest_first.core
    assert "pref05: value05" not in oldest_first.core
    assert "pref00: value00" not in oldest_first.core
    assert oldest_first.recent.index("item number 06") < (
        oldest_first.recent.index("item number 11")
    )
    assert len(oldest_first.recent) <= 600
    assert len(oldest_first.core) <= 500


def test_brain_budget_keeps_newest_evidence_and_deduplicates_late_updates():
    base = time.time() - 100
    records = [
        Memory(
            "robot-01", f"old{i}", "robot-01", True, "object",
            "older long observation " + "x" * 280, base + i, 0.75,
        )
        for i in range(20)
    ]
    records.extend([
        Memory("robot-01", "same", "robot-01", True, "object",
               "stale key location", base + 18, .7),
        Memory("robot-01", "same", "robot-01", True, "object",
               "new location is the green box", base + 30, .9),
    ])
    facts = [
        CoreFact("robot-01", "same_slot", "old value", base + 1),
        CoreFact("robot-01", "same_slot", "new value", base + 30),
    ]
    composed = compose_brain_context(records, facts, [])
    assert "new location is the green box" in composed.recent
    assert "stale key location" not in composed.recent
    assert "new value" in composed.core and "old value" not in composed.core
    assert len(composed.recent) <= 600 and len(composed.core) <= 500


def test_dense_camera_receipts_do_not_evict_earlier_tool_and_touch():
    # A noisy camera may publish far more receipts than the former 16-cue
    # composer window; distinct evidence must survive deduplication.
    timeline = [
        {"channel": "tool", "kind": "visual_look", "content": "Maybe a red key"},
        {"channel": "sensor", "kind": "touch_tap"},
    ] + [{"channel": "camera", "kind": "speech"} for _ in range(30)]
    result = compose_brain_context([], [], timeline).interaction
    assert "Earlier local VLM guess" in result
    assert "Maybe a red key" in result
    assert "Physical sensor edge: touch_tap" in result
    assert result.count("XIAO frame received") == 1
    assert len(result) <= 400


def test_two_recent_asr_clauses_prioritize_both_distinct_tool_receipts():
    # A completed question can arrive as separate ASR chunks. An earlier
    # visual request must not lose priority to the latest battery question.
    timeline = [
        {"channel": "tool", "kind": "visual_look",
         "content": "Possibly a blue key"},
        {"channel": "human_transcript", "kind": "model_asr_completed",
         "content": "Please look at my key"},
        {"channel": "tool", "kind": "robot_status",
         "content": "Battery reading 72 percent"},
        {"channel": "human_transcript", "kind": "model_asr_completed",
         "content": "Check your battery"},
        {"channel": "tool", "kind": "memory_recall",
         "content": "Unrelated private story " + "x" * 100},
        {"channel": "sensor", "kind": "touch_tap"},
    ]
    result = compose_brain_context([], [], timeline).interaction
    assert "Possibly a blue key" in result
    assert "Battery reading 72 percent" in result
    assert "Recent model ASR guess" in result
    assert len(result) <= 400


def test_earlier_compound_asr_clause_keeps_battery_tool_under_budget():
    # The latest chunk requests vision; the earlier one says "and check the
    # battery". The latter is not a sentence-initial status request.
    timeline = [
        {"channel": "tool", "kind": "robot_status",
         "content": "Battery 23 percent"},
        {"channel": "human_transcript", "kind": "model_asr_completed",
         "content": "And check the battery"},
        {"channel": "tool", "kind": "memory_recall",
         "content": "Unrelated long memory " + "m" * 90},
        {"channel": "tool", "kind": "visual_look",
         "content": "A small key beside the cup"},
        {"channel": "human_transcript", "kind": "model_asr_completed",
         "content": "Please look at the cup"},
        {"channel": "sensor", "kind": "touch_tap"},
    ]
    result = compose_brain_context([], [], timeline).interaction
    assert "Battery 23 percent" in result
    assert "A small key beside the cup" in result
    assert len(result) <= 400


def test_delayed_tool_completion_cannot_replace_newer_same_kind_receipt():
    hub = CameraFrameHub(["robot-01"])
    now = time.monotonic()
    hub.remember_tool("robot-01", "visual_look", "Current cup", now - 1)
    hub.remember_tool("robot-01", "visual_look", "Obsolete key", now - 3)
    receipts = hub.recent_tool_context("robot-01", now)
    assert len(receipts) == 1
    assert receipts[0]["summary"] == "Current cup"
    assert "Current cup" in compose_brain_context(
        [], [], hub.interaction_timeline("robot-01", now)
    ).interaction
    hub.remember_tool("robot-01", "visual_look", "New mug", now - .5)
    assert hub.recent_tool_context("robot-01", now)[0]["summary"] == "New mug"
