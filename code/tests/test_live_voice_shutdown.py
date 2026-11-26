"""Shutdown must retain ownership of real voice callback tasks."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.conversation import Conversation
from desk_robot.live_voice_events import VoiceEventListener


@pytest.mark.parametrize("owner", ["event", "global", "fallback"])
async def test_monitor_shutdown_joins_cancellation_resistant_callback(owner):
    entered = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    health = []
    generations = []
    peer_callbacks = []

    async def blocked_callback():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()
        finally:
            finished.set()

    async def on_interrupt(robot_id, kind):
        peer_callbacks.append((robot_id, kind))
        if robot_id == "robot-01":
            await blocked_callback()

    async def on_global(_reason):
        await blocked_callback()

    async def on_ready(ready):
        health.append(ready)

    def mock(request):
        snapshot = {
            "reset": False, "lost": False, "active_human_robots": [],
            "voice_turn_generations": {"robot-01": 1, "robot-02": 1},
        }
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={**snapshot, "cursor": 0, "events": []})
        if owner != "event":
            return httpx.Response(503)
        return httpx.Response(200, json={
            **snapshot, "cursor": 1, "active_human_robots": ["robot-01"],
            "events": [{
                "seq": 1, "robot_id": "robot-01", "kind": "speech_start",
                "source": "xiaozhi_server_vad", "voice_turn_generation": 1,
            }],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=on_interrupt,
            on_global_interrupt=on_global if owner == "global" else None,
            on_monitor_ready=on_ready, on_voice_generations=generations.append,
            require_snapshot=True, require_turn_generations=True,
        )
        runner = asyncio.create_task(listener.run())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            runner.cancel()
            await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
            done, _ = await asyncio.wait({runner}, timeout=0.05)
            assert not done, "monitor exited with a live callback"
            assert not finished.is_set()
            assert not listener.monitor_ready
            assert health == [True, False]
            assert generations[-1] is None
            assert listener.cursor == 0 and listener.handled == 0
            if owner == "event":
                assert peer_callbacks == [("robot-01", "speech_start")]
            elif owner == "global":
                assert not peer_callbacks
            else:
                assert sorted(peer_callbacks) == [
                    ("robot-01", "stream_unavailable"),
                    ("robot-02", "stream_unavailable"),
                ]
        finally:
            release.set()
            if not runner.done() and not runner.cancelling():
                runner.cancel()
            await asyncio.wait_for(
                asyncio.gather(runner, return_exceptions=True), timeout=2
            )
        assert runner.cancelled()
        assert finished.is_set()

@pytest.mark.parametrize("cancel_caller", [True, False])
def test_stop_recovery_preserves_caller_cancellation(cancel_caller):
    async def scenario():
        entered = asyncio.Event()
        released = asyncio.Event()
        pending = set()

        async def interrupt(_robot):
            entered.set()
            try:
                if not cancel_caller:
                    raise asyncio.CancelledError
                await asyncio.Event().wait()
            finally:
                released.set()

        def track(task):
            pending.add(task)
            task.add_done_callback(pending.discard)

        owner = SimpleNamespace(
            speaker_stop_unconfirmed=True,
            session_lock=asyncio.Lock(),
            active=None,
            settings=SimpleNamespace(robots=[SimpleNamespace(id="r", device_id="head")]),
            speaker=SimpleNamespace(interrupt=interrupt),
            _unsettled_speaker_aborts=pending,
            _has_unsettled_speaker_abort=lambda: any(not task.done() for task in pending),
            _track_speaker_abort=track,
        )
        recovery = asyncio.create_task(Conversation.recover_speaker_stop(owner))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            if cancel_caller:
                recovery.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(recovery, timeout=1)
            else:
                with pytest.raises(RuntimeError, match="STOP unconfirmed"):
                    await asyncio.wait_for(recovery, timeout=1)
            await asyncio.wait_for(released.wait(), timeout=1)
            assert recovery.cancelled() is cancel_caller
            assert owner.speaker_stop_unconfirmed
            assert not owner.session_lock.locked()
        finally:
            if not recovery.done():
                recovery.cancel()
            await asyncio.gather(recovery, *pending, return_exceptions=True)

    asyncio.run(scenario())


def test_shutdown_repeated_cancel_preserves_callback_ownership():
    async def scenario():
        entered = asyncio.Event()
        cleaning = asyncio.Event()
        release = asyncio.Event()
        second_cancel = asyncio.Event()

        async def callback():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleaning.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    second_cancel.set()
                    raise
                raise OSError("secondary callback failure")

        async def health(_ready):
            pass

        child = asyncio.create_task(callback())
        owner = SimpleNamespace(
            monitor_ready=True,
            _event_task=child,
            _event_sequence=1,
            _event_task_generation=0,
            _global_abort_task=None,
            _fallback_abort_tasks={},
            _publish_generations=lambda _: None,
            _set_monitor_ready=health,
            last_error=None,
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        shutdown = asyncio.create_task(VoiceEventListener._shutdown_callbacks(owner))
        try:
            await asyncio.wait_for(cleaning.wait(), timeout=1)
            shutdown.cancel()
            done, _ = await asyncio.wait({shutdown}, timeout=0.05)
            assert not done
            assert not second_cancel.is_set()
            assert owner._event_task is child
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(shutdown, timeout=1)
            assert owner._event_task is None
            assert owner.last_error == "Shutdown callback failed: OSError"
            assert not owner.monitor_ready
        finally:
            release.set()
            await asyncio.gather(shutdown, child, return_exceptions=True)

    asyncio.run(scenario())
