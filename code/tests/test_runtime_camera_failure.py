"""Optional camera faults must not bypass independent urgent STOP owners."""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from desk_robot.runtime import Runtime


@pytest.mark.parametrize("memory_fails", [False, True])
async def test_camera_prepare_fault_cannot_skip_motion_or_audio_stop(memory_fails):
    audio_started = asyncio.Event()
    motion_stopped = asyncio.Event()
    release = asyncio.Event()
    camera_error = OSError("camera disconnected")
    memory_error = sqlite3.OperationalError("database or disk is full")

    class Camera:
        def prepare_human_turn(self, robot_id, *, end_expected):
            raise camera_error

        def start_speech_frames(self, *args, **kwargs):
            pytest.fail("Camera restart must not follow failed preparation")

    class Pet:
        async def interrupt(self, robot_id):
            if memory_fails:
                raise memory_error

    class Conversation:
        async def stop(self):
            audio_started.set()
            await release.wait()

    class Coordinator:
        async def stop_active_exploration(self):
            motion_stopped.set()

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])
    runtime.multimodal = Camera()
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.coordinator = Coordinator()
    task = asyncio.create_task(runtime._on_voice_interrupt("robot-01", "speech_start"))
    try:
        await asyncio.wait_for(audio_started.wait(), timeout=0.5)
        await asyncio.wait_for(motion_stopped.wait(), timeout=0.5)
        assert runtime._voice_stop_unconfirmed is True
        assert not task.done()
        release.set()
        if memory_fails:
            with pytest.raises(RuntimeError, match="Unable to preempt") as caught:
                await asyncio.wait_for(task, timeout=1)
            assert caught.value.__cause__ is memory_error
            assert runtime._voice_stop_unconfirmed is True
        else:
            with pytest.raises(OSError, match="camera disconnected") as caught:
                await asyncio.wait_for(task, timeout=1)
            assert caught.value is camera_error
            assert runtime._voice_stop_unconfirmed is False
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
