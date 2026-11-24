"""A late unconfirmed decoder STOP cannot admit a fresh group speaker lease."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from desk_robot.conversation import Conversation


class PausedGrantSpeaker:
    def __init__(self):
        self.grant_started = asyncio.Event()
        self.finish_grant = asyncio.Event()
        self.released = 0

    @asynccontextmanager
    async def session(self, robots):
        self.grant_started.set()
        await self.finish_grant.wait()
        try:
            yield
        finally:
            self.released += 1


def conversation_with(speaker):
    conversation = Conversation.__new__(Conversation)
    conversation.speaker = speaker
    conversation.speaker_stop_unconfirmed = False
    return conversation


async def test_unconfirmed_stop_during_awaited_grant_refuses_talker_and_releases():
    speaker = PausedGrantSpeaker()
    conversation = conversation_with(speaker)
    spoken = []

    async def try_enter():
        async with conversation._confirmed_speaker_session([]):
            spoken.append(True)

    pending = asyncio.create_task(try_enter())
    await asyncio.wait_for(speaker.grant_started.wait(), timeout=1)
    conversation.speaker_stop_unconfirmed = True
    speaker.finish_grant.set()

    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await asyncio.wait_for(pending, timeout=1)
    assert spoken == []
    assert speaker.released == 1
    assert conversation.speaker_stop_unconfirmed is True


async def test_grant_without_stop_uncertainty_enters_once_and_releases():
    speaker = PausedGrantSpeaker()
    conversation = conversation_with(speaker)
    speaker.finish_grant.set()
    entered = 0

    async with conversation._confirmed_speaker_session([]):
        entered += 1

    assert entered == 1
    assert speaker.released == 1


async def test_preexisting_stop_uncertainty_never_requests_grant():
    speaker = PausedGrantSpeaker()
    conversation = conversation_with(speaker)
    conversation.speaker_stop_unconfirmed = True
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        async with conversation._confirmed_speaker_session([]):
            pytest.fail("Unconfirmed STOP admitted a speaker")
    assert not speaker.grant_started.is_set()
    assert speaker.released == 0


class PausedRecoverySpeaker:
    def __init__(self):
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.calls = []

    async def interrupt(self, robot):
        self.calls.append(robot.device_id)
        self.started.set()
        await self.finish.wait()


def recovery_conversation(speaker):
    conversation = conversation_with(speaker)
    conversation.active = None
    conversation.session_lock = asyncio.Lock()
    conversation.settings = SimpleNamespace(robots=[
        SimpleNamespace(device_id="head-01"),
        SimpleNamespace(device_id="head-02"),
    ])
    conversation.speaker_stop_unconfirmed = True
    return conversation


async def test_concurrent_stop_recovery_only_flushes_each_head_once():
    speaker = PausedRecoverySpeaker()
    conversation = recovery_conversation(speaker)
    first = asyncio.create_task(conversation.recover_speaker_stop())
    await asyncio.wait_for(speaker.started.wait(), timeout=1)
    second_started = asyncio.Event()

    async def recover_again():
        second_started.set()
        await conversation.recover_speaker_stop()

    second = asyncio.create_task(recover_again())
    await asyncio.wait_for(second_started.wait(), timeout=1)
    assert conversation.speaker_stop_unconfirmed is True
    speaker.finish.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=1)

    assert speaker.calls == ["head-01", "head-02"]
    assert conversation.speaker_stop_unconfirmed is False
    assert not conversation.session_lock.locked()


async def test_stop_recovery_cannot_flush_an_owned_session(monkeypatch):
    monkeypatch.setattr("desk_robot.conversation._CONVERSATION_STOP_TIMEOUT_S", 0.01)
    speaker = PausedRecoverySpeaker()
    conversation = recovery_conversation(speaker)
    async with conversation.session_lock:
        with pytest.raises(RuntimeError, match="recovery session still active"):
            await conversation.recover_speaker_stop()
        assert conversation.speaker_stop_unconfirmed is True
        assert speaker.calls == []
        assert conversation.session_lock.locked()
    assert not conversation.session_lock.locked()
