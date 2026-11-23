"""A late unconfirmed decoder STOP cannot admit a fresh group speaker lease."""

import asyncio
from contextlib import asynccontextmanager

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
