"""Unacknowledged Xiaozhi STOP request or head drain must outlive cancelled Mac tasks."""
import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from desk_robot.conversation import Conversation, KokoroHeadSpeaker
from desk_robot.pet import PetController
from desk_robot.runtime import Runtime
from desk_robot.simulator import SimulatedChat


class BlockingHeadSpeaker:
    """Fake adapter reporting transport STOP requests only (no PCM drain oracle)."""

    supports_permission_checks = True
    supports_passive_speech_budget = True

    def __init__(self):
        self.started = asyncio.Event()
        self.fail_stop = True
        self.grants = 0
        self.stop_calls = []

    @asynccontextmanager
    async def session(self, robots, *, passive=False):
        self.grants += 1
        yield

    async def say(self, robot, text, *, permission_check=None):
        self.started.set()
        await asyncio.Event().wait()

    async def interrupt(self, robot):
        self.stop_calls.append(robot.id)
        if self.fail_stop:
            raise httpx.TimeoutException("head /interrupt unavailable")
        return {
            "device_id": robot.device_id,
            "interrupted": True,
            "head_flush_requested": True,
        }


class QueuedDrainHeadSpeaker:
    """Stateful head queue oracle tracking per-head PCM and drain generations."""

    supports_permission_checks = True
    supports_passive_speech_budget = True
    supports_head_drain_receipt = True

    def __init__(self, robots, *, drain_mode="ok"):
        self.started = asyncio.Event()
        self.grants = 0
        self.stop_calls = []
        self.drain_mode = drain_mode
        self.queued_pcm_samples = {robot.id: 0 for robot in robots}
        self.playback_generation = {robot.id: 0 for robot in robots}

    @asynccontextmanager
    async def session(self, robots, *, passive=False):
        self.grants += 1
        yield

    async def say(self, robot, text, *, permission_check=None):
        self.playback_generation[robot.id] += 1
        self.queued_pcm_samples[robot.id] = 2400
        self.started.set()
        await asyncio.Event().wait()

    async def interrupt(self, robot):
        generation = self.playback_generation[robot.id]
        self.stop_calls.append((robot.id, generation))
        mode = self.drain_mode
        if mode == "timeout":
            raise httpx.TimeoutException("head drain receipt stalled")
        if mode == "disabled_drain":
            # Simulate request accepted while 2400 old PCM samples remain queued.
            return {
                "device_id": robot.device_id,
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": False,
                "head_queue_drained": False,
                "queued_pcm_samples": self.queued_pcm_samples[robot.id],
                "flush_generation": generation,
                "audible_stop_verified": False,
            }
        if mode == "missing_ack":
            return {
                "device_id": robot.device_id,
                "interrupted": True,
                "head_flush_requested": True,
                "head_queue_drained": False,
                "queued_pcm_samples": self.queued_pcm_samples[robot.id],
                "flush_generation": generation,
            }
        if mode == "missing_queue_drained":
            return {
                "device_id": robot.device_id,
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": True,
                "queued_pcm_samples": self.queued_pcm_samples[robot.id],
                "flush_generation": generation,
            }
        if mode == "nonzero_pcm":
            return {
                "device_id": robot.device_id,
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": True,
                "head_queue_drained": True,
                "queued_pcm_samples": 1200,
                "flush_generation": generation,
            }
        if mode == "bool_pcm":
            return {
                "device_id": robot.device_id,
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": True,
                "head_queue_drained": True,
                "queued_pcm_samples": False,
                "flush_generation": generation,
            }
        if mode == "stale_generation":
            # Stale ACK from previous generation leaves current 2400 PCM queued.
            return {
                "device_id": robot.device_id,
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": True,
                "head_queue_drained": True,
                "queued_pcm_samples": 0,
                "flush_generation": generation - 1,
            }
        if mode == "bool_generation":
            return {
                "device_id": robot.device_id,
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": True,
                "head_queue_drained": True,
                "queued_pcm_samples": 0,
                "flush_generation": True,
            }
        if mode == "wrong_head":
            return {
                "device_id": f"other-{robot.device_id}",
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": True,
                "head_queue_drained": True,
                "queued_pcm_samples": 0,
                "flush_generation": generation,
            }
        self.queued_pcm_samples[robot.id] = 0
        return {
            "device_id": robot.device_id,
            "interrupted": True,
            "head_flush_requested": True,
            "head_flush_acknowledged": True,
            "head_queue_drained": True,
            "queued_pcm_samples": 0,
            "flush_generation": generation,
            "audible_stop_verified": False,
        }


def hardware_conversation(settings, speaker=None):
    settings.mode = "hardware"
    for robot in settings.robots:
        robot.device_id = "head-" + robot.id
    if speaker is None:
        speaker = BlockingHeadSpeaker()
    return Conversation(settings, SimulatedChat(), speaker), speaker


async def test_group_stop_request_recovery_survives_cancellation_and_refuses_new_grant(
    settings,
):
    """Validate transport STOP request failure/recovery (not head PCM drain)."""
    conversation, speaker = hardware_conversation(settings)
    task = asyncio.create_task(
        conversation.run(["robot-01", "robot-02"], "hello", 2)
    )
    await asyncio.wait_for(speaker.started.wait(), timeout=2)

    class IdlePet:
        async def interrupt(self, robot_id):
            return None

    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.pet = IdlePet()
    runtime.conversation = conversation
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._preempt_audio_floor()
    assert conversation.speaker_stop_unconfirmed
    assert task.cancelled()
    assert speaker.grants == 1
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await conversation.run(["robot-01", "robot-02"], "obsolete", 2)
    assert speaker.grants == 1

    # A second explicit STOP clears the transport-request latch once every head
    # returns a request receipt. Head drain & acoustic 500 ms stop are separate.
    speaker.fail_stop = False
    await conversation.stop()
    assert not conversation.speaker_stop_unconfirmed
    assert speaker.stop_calls[-2:] == ["robot-01", "robot-02"]
    speaker.started.clear()
    resumed = asyncio.create_task(
        conversation.run(["robot-01", "robot-02"], "fresh", 2)
    )
    await asyncio.wait_for(speaker.started.wait(), timeout=2)
    assert speaker.grants == 2
    await conversation.stop()
    assert resumed.cancelled()
    assert not conversation.speaker_stop_unconfirmed


async def test_proactive_stop_request_recovery_reaches_runtime_and_blocks_audio(
    settings,
):
    """Validate proactive transport STOP request failure/recovery (not head drain)."""
    conversation, speaker = hardware_conversation(settings)
    robot = settings.robot("robot-01")
    pet = PetController.__new__(PetController)
    pet.conversation = conversation
    pet._speech_participants = frozenset({"robot-01"})
    pet._speech_task = asyncio.create_task(
        conversation.say_proactive(
            robot, "unconfirmed optional audio", permission_check=lambda: True,
        )
    )
    await asyncio.wait_for(speaker.started.wait(), timeout=2)

    class CancelPet:
        async def interrupt(self, robot_id):
            await pet._cancel_speech(robot_id)

    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.pet = CancelPet()
    runtime.conversation = conversation
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._preempt_audio_floor()
    assert pet._speech_task.cancelled()
    assert conversation.speaker_stop_unconfirmed
    assert speaker.grants == 1
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await conversation.say_proactive(
            robot, "forbidden successor", permission_check=lambda: True,
        )
    assert speaker.grants == 1

    speaker.fail_stop = False
    await conversation.stop()
    assert not conversation.speaker_stop_unconfirmed
    assert speaker.stop_calls[-2:] == ["robot-01", "robot-02"]


async def test_consent_revoked_before_any_speaker_send_never_latches_decoder(settings):
    """Transport pre-transmission consent gate: no PCM was sent or queued."""
    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = True

    class RevokingChat:
        async def reply(self, history):
            settings.fleet_text_sharing_enabled = False
            return "This output was revoked before entering a speaker."

    class NoPlaybackSpeaker:
        supports_permission_checks = True

        def __init__(self):
            self.session_grants = 0
            self.sends = 0

        @asynccontextmanager
        async def session(self, robots):
            self.session_grants += 1
            yield

        async def say(self, robot, text, *, permission_check=None):
            self.sends += 1
            raise AssertionError("Consent revocation must stop before transmission")

    speaker = NoPlaybackSpeaker()
    conversation = Conversation(settings, RevokingChat(), speaker)
    with pytest.raises(RuntimeError, match="consent revoked"):
        await conversation.run(["robot-01", "robot-02"], "private camera context", 2)
    assert speaker.session_grants == 1
    assert speaker.sends == 0
    assert not conversation.speaker_stop_unconfirmed


async def test_pre_synthesis_human_cancel_still_requests_optional_stop(settings):
    """Pre-synthesis cancel requests transport STOP without inventing queued PCM."""
    conversation, speaker = hardware_conversation(settings)
    started = asyncio.Event()

    class SlowChat:
        async def reply(self, history):
            started.set()
            await asyncio.Event().wait()

    conversation.chat = SlowChat()
    task = asyncio.create_task(
        conversation.run(["robot-01", "robot-02"], "cancel pre synthesis", 2)
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    await conversation.stop()
    assert task.cancelled()
    assert speaker.grants == 1
    assert speaker.stop_calls == ["robot-01"]
    # A failed precautionary STOP did not mask a non-existent audio send.
    assert not conversation.speaker_stop_unconfirmed


@pytest.mark.parametrize(
    "fault",
    [
        "disabled_drain",
        "timeout",
        "missing_ack",
        "missing_queue_drained",
        "nonzero_pcm",
        "bool_pcm",
        "stale_generation",
        "bool_generation",
        "wrong_head",
    ],
)
async def test_generation_bound_drain_faults_retain_old_pcm_and_block_successor(
    settings, fault,
):
    """Requested-only, delayed, missing, stale, or wrong-head drain keeps PCM & latch."""
    speaker = QueuedDrainHeadSpeaker(settings.robots, drain_mode=fault)
    conversation, speaker = hardware_conversation(settings, speaker=speaker)
    task = asyncio.create_task(
        conversation.run(["robot-01", "robot-02"], "hello", 2)
    )
    await asyncio.wait_for(speaker.started.wait(), timeout=2)
    assert speaker.queued_pcm_samples["robot-01"] == 2400

    class IdlePet:
        async def interrupt(self, robot_id):
            return None

    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.pet = IdlePet()
    runtime.conversation = conversation
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._preempt_audio_floor()
    assert task.cancelled()
    assert conversation.speaker_stop_unconfirmed is True
    assert speaker.queued_pcm_samples["robot-01"] == 2400
    assert speaker.grants == 1

    # Neither group nor proactive speech can acquire a successor grant while old
    # PCM remains un-drained.
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await conversation.run(["robot-01", "robot-02"], "successor group", 2)
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await conversation.say_proactive(
            settings.robot("robot-01"), "successor pet", permission_check=lambda: True,
        )
    # Recovery without valid current-generation drain evidence still refuses.
    with pytest.raises(RuntimeError, match="recovery STOP unconfirmed"):
        await conversation.stop()
    assert conversation.speaker_stop_unconfirmed is True
    assert speaker.queued_pcm_samples["robot-01"] == 2400
    assert speaker.grants == 1

    # Once every head drains its queue for the current generation, the latch clears
    # (without fabricating audible_stop_verified) and admits a successor grant.
    speaker.drain_mode = "ok"
    await conversation.stop()
    assert conversation.speaker_stop_unconfirmed is False
    assert speaker.queued_pcm_samples == {"robot-01": 0, "robot-02": 0}
    speaker.started.clear()
    resumed = asyncio.create_task(
        conversation.run(["robot-01", "robot-02"], "resumed", 2)
    )
    await asyncio.wait_for(speaker.started.wait(), timeout=2)
    assert speaker.grants == 2
    await conversation.stop()
    assert resumed.cancelled()
    assert conversation.speaker_stop_unconfirmed is False
    assert speaker.queued_pcm_samples == {"robot-01": 0, "robot-02": 0}


async def test_proactive_generation_bound_drain_blocks_until_current_drain_evidence(
    settings,
):
    """Proactive audio stays latched across stale/disabled drain until real drain."""
    speaker = QueuedDrainHeadSpeaker(settings.robots, drain_mode="stale_generation")
    conversation, speaker = hardware_conversation(settings, speaker=speaker)
    robot = settings.robot("robot-01")
    pet = PetController.__new__(PetController)
    pet.conversation = conversation
    pet._speech_participants = frozenset({"robot-01"})
    pet._speech_task = asyncio.create_task(
        conversation.say_proactive(
            robot, "proactive queued audio", permission_check=lambda: True,
        )
    )
    await asyncio.wait_for(speaker.started.wait(), timeout=2)
    assert speaker.queued_pcm_samples["robot-01"] == 2400

    class CancelPet:
        async def interrupt(self, robot_id):
            await pet._cancel_speech(robot_id)

    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.pet = CancelPet()
    runtime.conversation = conversation
    with pytest.raises(RuntimeError, match="Unable to preempt"):
        await runtime._preempt_audio_floor()
    assert pet._speech_task.cancelled()
    assert conversation.speaker_stop_unconfirmed is True
    assert speaker.queued_pcm_samples["robot-01"] == 2400
    assert speaker.grants == 1

    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await conversation.say_proactive(
            robot, "blocked proactive successor", permission_check=lambda: True,
        )
    assert speaker.grants == 1

    speaker.drain_mode = "ok"
    await conversation.stop()
    assert conversation.speaker_stop_unconfirmed is False
    assert speaker.queued_pcm_samples["robot-01"] == 0

    speaker.started.clear()
    successor = asyncio.create_task(
        conversation.say_proactive(
            robot, "admitted after drain", permission_check=lambda: True,
        )
    )
    pet._speech_task = successor
    await asyncio.wait_for(speaker.started.wait(), timeout=2)
    assert speaker.grants == 2
    await pet._cancel_speech(robot.id)
    assert successor.cancelled()
    assert conversation.speaker_stop_unconfirmed is False
    assert speaker.queued_pcm_samples["robot-01"] == 0


async def test_kokoro_adapter_generation_bound_head_drain_over_http_transport(
    settings, monkeypatch,
):
    """End-to-end KokoroHeadSpeaker(..., require_head_drain_receipt=True) drain fence."""
    monkeypatch.setenv(settings.speech_bridge_token_env, "z" * 32)
    settings.mode = "hardware"
    for robot in settings.robots:
        robot.device_id = "head-" + robot.id

    queued_pcm = {"head-robot-01": 0, "head-robot-02": 0}
    interrupt_mode = "disabled_drain"
    speak_entered = asyncio.Event()
    interrupt_calls = []
    fail_speak = True

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/v1/audio/speech"):
            return httpx.Response(200, content=b"RIFF" + b"\x00" * 64)
        body = json.loads(request.read())
        if url.endswith("/session"):
            enabled = body["enabled"]
            return httpx.Response(200, json={
                "device_ids": sorted(body["device_ids"]),
                "enabled": enabled,
                "expires_in_seconds": 30 if enabled else 0,
                "lease_id": body["lease_id"],
                **({"passive": True} if body.get("passive") else {}),
            })
        if url.endswith("/speak"):
            queued_pcm[body["device_id"]] = 2400
            speak_entered.set()
            if fail_speak:
                raise httpx.ReadError("stream interrupted mid-playback", request=request)
            return httpx.Response(200, json={
                "device_id": body["device_id"],
                "transmitted": True,
                "physical_playback_verified": False,
            })
        if url.endswith("/interrupt"):
            dev = body["device_id"]
            interrupt_calls.append(dev)
            if interrupt_mode == "disabled_drain":
                return httpx.Response(200, json={
                    "device_id": dev,
                    "interrupted": True,
                    "head_flush_requested": True,
                    "head_flush_acknowledged": False,
                    "head_queue_drained": False,
                    "queued_pcm_samples": queued_pcm[dev],
                    "flush_generation": 1 if dev == "head-robot-01" else 0,
                    "audible_stop_verified": False,
                })
            if interrupt_mode == "stale_generation":
                return httpx.Response(200, json={
                    "device_id": dev,
                    "interrupted": True,
                    "head_flush_requested": True,
                    "head_flush_acknowledged": True,
                    "head_queue_drained": True,
                    "queued_pcm_samples": 0,
                    "flush_generation": 0,
                    "audible_stop_verified": False,
                })
            queued_pcm[dev] = 0
            return httpx.Response(200, json={
                "device_id": dev,
                "interrupted": True,
                "head_flush_requested": True,
                "head_flush_acknowledged": True,
                "head_queue_drained": True,
                "queued_pcm_samples": 0,
                "flush_generation": 1 if dev == "head-robot-01" else 0,
                "audible_stop_verified": False,
            })
        raise AssertionError(f"Unexpected URL {url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        speaker = KokoroHeadSpeaker(settings, client, require_head_drain_receipt=True)
        conversation = Conversation(settings, SimulatedChat(), speaker)
        with pytest.raises(httpx.ReadError):
            await conversation.say_proactive(
                settings.robot("robot-01"),
                "hello",
                permission_check=lambda: True,
            )
        assert speak_entered.is_set()
        assert queued_pcm["head-robot-01"] == 2400
        assert conversation.speaker_stop_unconfirmed is True

        # Stale generation ACK still keeps the latch closed and retains 2400 PCM.
        interrupt_mode = "stale_generation"
        with pytest.raises(RuntimeError, match="recovery STOP unconfirmed"):
            await conversation.stop()
        assert conversation.speaker_stop_unconfirmed is True
        assert queued_pcm["head-robot-01"] == 2400
        with pytest.raises(RuntimeError, match="STOP unconfirmed"):
            await conversation.run(["robot-01", "robot-02"], "blocked", 2)

        # Valid generation-1 drain evidence drains PCM and clears the latch while
        # keeping audible_stop_verified=False for physical 500 ms qualification,
        # allowing a subsequent clean turn to be admitted.
        interrupt_mode = "ok"
        await conversation.stop()
        assert conversation.speaker_stop_unconfirmed is False
        assert queued_pcm == {"head-robot-01": 0, "head-robot-02": 0}
        assert interrupt_calls[-2:] == ["head-robot-01", "head-robot-02"]
        fail_speak = False
        assert await conversation.say_proactive(
            settings.robot("robot-01"),
            "fresh turn after drain",
            permission_check=lambda: True,
        ) is True
