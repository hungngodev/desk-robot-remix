"""Unacknowledged Xiaozhi decoder STOP must outlive cancelled Mac tasks."""
import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from desk_robot.conversation import Conversation
from desk_robot.pet import PetController
from desk_robot.runtime import Runtime
from desk_robot.simulator import SimulatedChat


class BlockingHeadSpeaker:
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


def hardware_conversation(settings):
    settings.mode = "hardware"
    for robot in settings.robots:
        robot.device_id = "head-" + robot.id
    speaker = BlockingHeadSpeaker()
    return Conversation(settings, SimulatedChat(), speaker), speaker


async def test_group_stop_failure_survives_cancellation_and_refuses_new_grant(settings):
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

    # A second explicit STOP can clear the latch only with real receipts
    # for each addressed head. It never infers recovery from cancelled().
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


async def test_proactive_stop_failure_reaches_runtime_and_blocks_audio(settings):
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
