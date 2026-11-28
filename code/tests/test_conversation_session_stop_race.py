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
    conversation._active = None
    conversation._active_changed = asyncio.Event()
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


@pytest.mark.parametrize("kind", ["legacy", "passive", "deliberate"])
@pytest.mark.parametrize("latch", [False, True])
async def test_proactive_grant_rechecks_unconfirmed_stop(kind, latch):
    """The optional talker must use the same STOP fence as group speech."""

    class LegacySpeaker(PausedGrantSpeaker):
        def __init__(self):
            super().__init__()
            self.spoken = []

        async def say(self, robot, text):
            self.spoken.append((robot.id, text))

    class BudgetSpeaker(LegacySpeaker):
        supports_permission_checks = True
        supports_passive_speech_budget = True

        def __init__(self):
            super().__init__()
            self.passive = []

        @asynccontextmanager
        async def session(self, robots, *, passive=False):
            self.passive.append(passive)
            async with super().session(robots):
                yield

        async def say(self, robot, text, *, permission_check=None):
            assert permission_check is None or permission_check()
            await super().say(robot, text)

    speaker = LegacySpeaker() if kind == "legacy" else BudgetSpeaker()
    conversation = conversation_with(speaker)
    conversation.settings = SimpleNamespace(
        mode="simulation" if kind == "legacy" else "hardware",
        pet_quiet_hours=None,
    )
    conversation.active = None
    conversation.session_lock = asyncio.Lock()
    conversation.speaker_lock = asyncio.Lock()
    robot = SimpleNamespace(id="robot-01")
    pending = asyncio.create_task(conversation.say_proactive(
        robot, "A fresh observation", deliberate=kind == "deliberate",
    ))
    try:
        await asyncio.wait_for(speaker.grant_started.wait(), timeout=1)
        conversation.speaker_stop_unconfirmed = latch
        speaker.finish_grant.set()
        if latch:
            with pytest.raises(RuntimeError, match="STOP unconfirmed"):
                await asyncio.wait_for(pending, timeout=1)
            assert speaker.spoken == []
        else:
            assert await asyncio.wait_for(pending, timeout=1) is True
            assert speaker.spoken == [("robot-01", "A fresh observation")]
        assert speaker.released == 1
        assert not conversation.session_lock.locked()
        assert not conversation.speaker_lock.locked()
        if kind != "legacy":
            assert speaker.passive == [kind == "passive"]
    finally:
        speaker.finish_grant.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def test_unsettled_cancellation_resistant_stop_blocks_retry_and_successor(
    monkeypatch,
):
    """Detached overdue STOP must remain fenced until its task actually exits."""
    monkeypatch.setattr("desk_robot.conversation._SPEAKER_ABORT_TIMEOUT_S", 0.02)
    monkeypatch.setattr("desk_robot.conversation._CONVERSATION_STOP_TIMEOUT_S", 0.15)
    entered = asyncio.Event()
    release_first = asyncio.Event()
    flush_owners: list[str | None] = []
    active_session = [None]
    calls = 0

    class CancellationResistantSpeaker(PausedGrantSpeaker):
        def __init__(self):
            super().__init__()
            self.finish_grant.set()

        @asynccontextmanager
        async def session(self, robots):
            active_session[0] = robots[0].id if robots else None
            try:
                yield
            finally:
                active_session[0] = None

        async def interrupt(self, robot):
            nonlocal calls
            calls += 1
            call_num = calls
            if call_num == 1:
                entered.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    await release_first.wait()
                    flush_owners.append(active_session[0])
                    return {"device_id": robot.device_id, "interrupted": True}
            flush_owners.append(active_session[0])
            return {"device_id": robot.device_id, "interrupted": True}

    speaker = CancellationResistantSpeaker()
    conversation = conversation_with(speaker)
    conversation.active = None
    conversation.session_lock = asyncio.Lock()
    conversation.speaker_lock = asyncio.Lock()
    conversation.settings = SimpleNamespace(
        mode="hardware",
        robots=[SimpleNamespace(id="robot-01", device_id="head-01")],
    )
    conversation.speaker_stop_unconfirmed = True

    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await conversation.recover_speaker_stop()
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert conversation.speaker_stop_unconfirmed is True

    # Retry while first interrupt task still refuses exit must fail without issuing B.
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        await conversation.recover_speaker_stop()
    assert calls == 1

    # Successor B cannot enter while stale STOP task is still unsettled.
    with pytest.raises(RuntimeError, match="STOP unconfirmed"):
        async with conversation._confirmed_speaker_session(
            [SimpleNamespace(id="robot-02", device_id="head-02")]
        ):
            pytest.fail("Unsettled STOP admitted successor B")

    # Once delayed STOP finishes, recovery performs a fresh STOP and clears the fence.
    release_first.set()
    await conversation.recover_speaker_stop()
    assert conversation.speaker_stop_unconfirmed is False
    assert calls == 2
    assert flush_owners == [None, None]
    async with conversation._confirmed_speaker_session(
        [SimpleNamespace(id="robot-02", device_id="head-02")]
    ):
        assert active_session[0] == "robot-02"


async def test_real_aiohttp_delayed_interrupt_remains_fenced_until_settled(
    settings, monkeypatch, tokens,
):
    """Real KokoroHeadSpeaker over aiohttp keeps unconfirmed STOP fenced across retries."""
    import httpx
    from aiohttp import web
    from desk_robot.conversation import KokoroHeadSpeaker
    from desk_robot.simulator import SimulatedChat

    monkeypatch.setattr("desk_robot.conversation._SPEAKER_ABORT_TIMEOUT_S", 0.05)
    monkeypatch.setattr("desk_robot.conversation._CONVERSATION_STOP_TIMEOUT_S", 0.25)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    interrupt_calls = 0

    async def interrupt_handler(request):
        nonlocal interrupt_calls
        interrupt_calls += 1
        body = await request.json()
        if interrupt_calls == 1:
            first_started.set()
            await asyncio.wait_for(release_first.wait(), timeout=2)
        return web.json_response({
            "device_id": body["device_id"],
            "interrupted": True,
            "head_flush_requested": True,
        })

    app = web.Application()
    app.router.add_post("/interrupt", interrupt_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    settings.mode = "hardware"
    settings.speech_bridge_url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv(settings.speech_bridge_token_env, "s" * 40)
    robot = settings.robots[0]
    robot.device_id = "head-01"
    settings.robots = [robot]
    async with httpx.AsyncClient(trust_env=False) as client:
        speaker = KokoroHeadSpeaker(settings, client)
        conversation = Conversation(settings, SimulatedChat(), speaker)
        conversation.speaker_stop_unconfirmed = True
        try:
            with pytest.raises(RuntimeError, match="STOP unconfirmed"):
                await conversation.recover_speaker_stop()
            await asyncio.wait_for(first_started.wait(), timeout=1)
            assert conversation.speaker_stop_unconfirmed is True
            with pytest.raises(RuntimeError, match="STOP unconfirmed"):
                async with conversation._confirmed_speaker_session([robot]):
                    pytest.fail("Timeout on real aiohttp /interrupt admitted session")
            release_first.set()
            await conversation.recover_speaker_stop()
            assert conversation.speaker_stop_unconfirmed is False
            assert interrupt_calls == 2
        finally:
            release_first.set()
            await runner.cleanup()
