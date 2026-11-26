"""Host VAD preemption with a cancellation-resistant optional tool transport."""

import asyncio
from types import SimpleNamespace

import pytest
from desk_robot.conversation import Conversation
from desk_robot.pet import PetController
from desk_robot.runtime import Runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["status", "aux_status"])
@pytest.mark.parametrize("tool_robot", ["robot-01", "robot-02"])
async def test_human_vad_cancels_optional_tool_without_waiting_for_transport(tool, tool_robot):
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    speech_started = asyncio.Event()
    speech_stopped = asyncio.Event()

    async def slow_read():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        finally:
            finished.set()
        return {"robot_id": tool_robot}

    async def simulated_group_speech():
        # This models a cancellable speech owner, not a physical decoder ACK.
        speech_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            speech_stopped.set()

    robot_ids = ("robot-01", "robot-02")
    settings = SimpleNamespace(robots=[SimpleNamespace(id=rid) for rid in robot_ids])
    conversation = Conversation.__new__(Conversation)
    conversation.stop_generation = 0
    conversation.speaker_stop_unconfirmed = False
    conversation._active = asyncio.create_task(simulated_group_speech())
    pet = PetController.__new__(PetController)
    pet.conversation = conversation
    pet.heads = {tool_robot: SimpleNamespace(status=slow_read, aux_status=slow_read)}
    pet.states = {
        rid: SimpleNamespace(deferred_speech_candidate=None, deferred_speech_task=None)
        for rid in robot_ids
    }

    def pet_status(robot_id):
        return {"robot_id": robot_id}

    pet.status = pet_status
    pet._vision_preemption_epoch = 0
    pet._vision_inflight = None
    pet._speech_participants = {tool_robot}
    receipt = asyncio.create_task(pet._proactive_tool_receipt(tool_robot, tool))
    pet._speech_task = receipt

    runtime = Runtime.__new__(Runtime)
    runtime.settings = settings
    runtime.pet = pet
    runtime.conversation = conversation
    vad = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        await asyncio.wait_for(speech_started.wait(), timeout=1)
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        vad = asyncio.create_task(runtime._on_voice_interrupt("robot-01", "speech_start"))
        done, _ = await asyncio.wait({vad}, timeout=0.5)
        assert vad in done, "P1 VAD waited for the slow optional tool"
        assert loop.time() - started_at <= 0.5
        await vad
        assert cancelled.is_set()
        assert receipt.cancelled()
        assert conversation.active.cancelled()
        assert speech_stopped.is_set()
        assert not finished.is_set(), "The tool must still be blocked at speech cutoff"
        assert conversation.stop_generation == 1
        assert runtime._voice_speech_active == {"robot-01"}
        assert not runtime._voice_stop_unconfirmed
    finally:
        release.set()
        tasks = [receipt, conversation.active]
        if vad is not None:
            tasks.append(vad)
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if entered.is_set():
            await asyncio.wait_for(finished.wait(), timeout=1)

    # A cancellation-resistant transport can return, but the receipt owner
    # remains retired and cannot hand that result to the old model turn.
    assert receipt.cancelled()
