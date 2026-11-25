"""Pretransmission STOP tasks must not outlive the fleet admission fence."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from desk_robot.conversation import Conversation


async def test_five_talkers_cannot_overtake_unsettled_pre_audio_stop(monkeypatch):
    monkeypatch.setattr("desk_robot.conversation._SPEAKER_ABORT_TIMEOUT_S", 0.02)
    robots = [SimpleNamespace(id=f"robot-{i:02d}") for i in range(1, 6)]
    stop_started = asyncio.Event()
    stop_cancelled = asyncio.Event()
    release_stop = asyncio.Event()
    stop_finished = asyncio.Event()
    grants = []
    sent = []

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            grants.append(robots[0].id)
            yield

        async def say(self, robot, text):
            sent.append(robot.id)
            await asyncio.sleep(0)

        async def interrupt(self, robot):
            stop_started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                stop_cancelled.set()
                await release_stop.wait()
            finally:
                stop_finished.set()

    conversation = Conversation.__new__(Conversation)
    conversation.speaker = Speaker()
    conversation.settings = SimpleNamespace(mode="simulation", pet_quiet_hours=None)
    conversation.active = None
    conversation.speaker_stop_unconfirmed = False
    conversation.session_lock = asyncio.Lock()
    conversation.speaker_lock = asyncio.Lock()
    checks = 0

    def permission():
        nonlocal checks
        checks += 1
        # The final check at the transmission boundary expires the permission.
        return checks < 4

    first = asyncio.create_task(conversation.say_proactive(
        robots[0], "revoked", permission_check=permission,
    ))
    contenders = []
    try:
        await asyncio.wait_for(stop_started.wait(), 1)
        contenders = [asyncio.create_task(conversation.say_proactive(robot, "new"))
                      for robot in robots[1:]]
        await asyncio.wait_for(stop_cancelled.wait(), 1)
        with pytest.raises(RuntimeError, match="permission revoked before transmission"):
            await asyncio.wait_for(first, 1)
        results = await asyncio.wait_for(asyncio.gather(*contenders, return_exceptions=True), 1)
        assert not stop_finished.is_set()
        assert not conversation.session_lock.locked()
        assert not conversation.speaker_lock.locked()
        assert grants == [robots[0].id]
        assert sent == []
        assert all(isinstance(result, RuntimeError) and "STOP unconfirmed" in str(result)
                   for result in results)
        assert conversation._has_unsettled_speaker_abort()
        release_stop.set()
        await asyncio.wait_for(stop_finished.wait(), 1)
        assert await asyncio.wait_for(conversation.say_proactive(robots[0], "fresh"), 1)
        assert sent == [robots[0].id]
        assert not conversation.session_lock.locked()
        assert not conversation.speaker_lock.locked()
    finally:
        release_stop.set()
        await asyncio.gather(first, *contenders, return_exceptions=True)
        await asyncio.wait_for(stop_finished.wait(), 1)


async def test_failed_group_model_retains_pre_audio_stop_fence(settings, monkeypatch):
    monkeypatch.setattr("desk_robot.conversation._SPEAKER_ABORT_TIMEOUT_S", 0.02)
    release_stop = asyncio.Event()
    stop_cancelled = asyncio.Event()
    stop_finished = asyncio.Event()
    grants = []
    sent = []

    class BrokenChat:
        async def reply(self, history):
            raise ValueError("model failed before audio")

    class Speaker:
        @asynccontextmanager
        async def session(self, robots):
            grants.append(tuple(robot.id for robot in robots))
            yield

        async def say(self, robot, text):
            sent.append(robot.id)

        async def interrupt(self, robot):
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                stop_cancelled.set()
                await release_stop.wait()
            finally:
                stop_finished.set()

    ids = ["robot-01", "robot-02"]
    conversation = Conversation(settings, BrokenChat(), Speaker())
    first = asyncio.create_task(conversation.run(ids, "Discuss a toy", 2))
    try:
        await asyncio.wait_for(stop_cancelled.wait(), 1)
        with pytest.raises(ValueError, match="model failed before audio"):
            await asyncio.wait_for(first, 1)
        assert conversation.active is None
        assert not conversation.session_lock.locked()
        assert not conversation.speaker_lock.locked()
        assert not stop_finished.is_set()
        with pytest.raises(RuntimeError, match="STOP unconfirmed"):
            await conversation.say_proactive(settings.robot(ids[0]), "fresh")
        assert grants == [tuple(ids)]
        assert sent == []
        release_stop.set()
        await asyncio.wait_for(stop_finished.wait(), 1)
        assert await conversation.say_proactive(settings.robot(ids[0]), "fresh")
        assert sent == [ids[0]]
    finally:
        release_stop.set()
        await asyncio.gather(first, return_exceptions=True)
        await asyncio.wait_for(stop_finished.wait(), 1)
