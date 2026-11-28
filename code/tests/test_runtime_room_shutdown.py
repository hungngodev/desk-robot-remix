"""Shared room USB reader ownership on bounded runtime shutdown."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from desk_robot.runtime import Runtime


def test_room_shutdown_timeout_keeps_live_reader_owned():
    async def scenario():
        release = asyncio.Event()
        entered = asyncio.Event()

        async def stalled_reader():
            entered.set()
            await release.wait()

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(close=AsyncMock())
        runtime.conversation = SimpleNamespace(stop=AsyncMock())
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        task = asyncio.create_task(stalled_reader())
        runtime._room_task = task
        await entered.wait()
        try:
            with pytest.raises(TimeoutError, match="Shared room USB shutdown unconfirmed"):
                await runtime.close()
            assert runtime._closed
            assert runtime._room_stop.is_set()
            assert runtime._room_task is task
            assert not task.done()
            assert task.cancelling() == 0  # timeout must not cancel reader
        finally:
            release.set()
            await task

    asyncio.run(scenario())


def test_cancelled_reader_keeps_cleanup_order_and_reports_unconfirmed_stop():
    """An independently cancelled USB task must not skip final other owners."""
    async def scenario():
        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(close=AsyncMock())
        runtime.conversation = SimpleNamespace(stop=AsyncMock())
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        task = asyncio.create_task(asyncio.sleep(60))
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        runtime._room_task = task

        with pytest.raises(
            RuntimeError,
            match="Shared room USB shutdown task cancelled without confirmation",
        ):
            await runtime.close()

        assert runtime._room_stop.is_set()
        assert runtime._room_task is None
        runtime.coordinator.close.assert_awaited_once()
        runtime.pet.close.assert_awaited_once()
        runtime.conversation.stop.assert_awaited_once()
        runtime.client.aclose.assert_awaited_once()

    asyncio.run(scenario())


def test_room_consumer_failure_does_not_break_subsequent_delivery(caplog):
    """An optional room context failure must not poison later USB evidence."""
    async def scenario():
        received = []
        recovered = asyncio.Event()

        def remember_room(observation):
            received.append(observation)
            if len(received) == 1:
                raise RuntimeError("transient room context failure")
            recovered.set()

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(room_station_context_enabled=True)
        runtime.multimodal = SimpleNamespace(
            hub=SimpleNamespace(remember_room=remember_room)
        )
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        runtime.room_context_failures = 0
        runtime._closed = False

        loop = asyncio.get_running_loop()
        first, second = object(), object()
        runtime._queue_room_observation(loop, first)
        await asyncio.sleep(0)
        assert received == [first]
        assert runtime.room_context_failures == 1
        assert not runtime._room_dispatch_enqueued

        runtime._queue_room_observation(loop, second)
        await asyncio.wait_for(recovered.wait(), timeout=1)
        assert received == [first, second]
        assert runtime.room_context_failures == 1
        assert not runtime._room_dispatch_enqueued

    asyncio.run(scenario())
    assert "Room context consumer failed (1 total)" in caplog.text


def test_cancelled_shutdown_waiter_does_not_cancel_owner_cleanup():
    """Repeated lifespan cancellation cannot skip the USB or other owners."""
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def stop_motion():
            entered.set()
            await release.wait()

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(side_effect=stop_motion), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(close=AsyncMock())
        runtime.conversation = SimpleNamespace(stop=AsyncMock())
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = SimpleNamespace(close=AsyncMock())
        runtime._voice_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        reader = asyncio.create_task(runtime._room_stop.wait())
        runtime._room_task = reader

        waiter = asyncio.create_task(runtime.close())
        peer = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            waiter.cancel()
            await asyncio.sleep(0)
            waiter.cancel()
            await asyncio.sleep(0)
            assert not waiter.done()
            assert not runtime._room_stop.is_set()
            peer = asyncio.create_task(runtime.close())
            await asyncio.sleep(0)
            runtime.coordinator.close.assert_awaited_once()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(waiter, timeout=1)
            await asyncio.wait_for(peer, timeout=1)
            assert runtime._room_stop.is_set()
            assert reader.done() and not reader.cancelled()
            assert runtime._room_task is None
            assert runtime._close_task is None
            runtime.pet.close.assert_awaited_once()
            runtime.multimodal.close.assert_awaited_once()
            runtime.conversation.stop.assert_awaited_once()
            runtime.client.aclose.assert_awaited_once()
        finally:
            release.set()
            runtime._room_stop.set()
            await asyncio.gather(
                reader, waiter, *([peer] if peer is not None else []),
                return_exceptions=True,
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("exit_kind", ["error", "return", "cancel"])
def test_unexpected_runtime_service_exit_closes_all_owners(monkeypatch, exit_kind):
    """A permanent critical voice-monitor exit must close all runtime owners."""
    service = "voice"
    import sys

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        shutdown_started = asyncio.Event()

        async def run_service():
            entered.set()
            await release.wait()
            if exit_kind == "error":
                raise ValueError("permanent service failure")

        class VoiceListener:
            def __init__(self, *args, **kwargs):
                pass

            async def run(self):
                await run_service()

        class RoomFeed:
            def __init__(self, *args, **kwargs):
                pass

            async def run(self, stop):
                await run_service()

        async def stop_motion():
            shutdown_started.set()

        monkeypatch.setitem(sys.modules, "serial", SimpleNamespace())
        monkeypatch.setattr("desk_robot.runtime.RoomSerialFeed", RoomFeed)
        monkeypatch.setattr("desk_robot.runtime.VoiceEventListener", VoiceListener)
        monkeypatch.setattr("desk_robot.runtime.secret", lambda name: "s" * 32)
        monkeypatch.setattr("desk_robot.dock_runtime.close_detector_pool", AsyncMock())

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(
            mode="hardware",
            room_station_enabled=service == "room",
            room_station_port="fake",
            room_station_soil_dry_adc=None,
            speech_bridge_url="http://127.0.0.1:8766",
            speech_bridge_token_env="SPEECH_TOKEN",
            pet_autostart_enabled=False,
            robots=[SimpleNamespace(
                id="robot-01", device_id="head01" if service == "voice" else "",
            )],
        )
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(side_effect=stop_motion), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(
            close=AsyncMock(), set_voice_monitor_ready=lambda ready: None,
        )
        runtime.conversation = SimpleNamespace(
            stop=AsyncMock(),
            speaker=SimpleNamespace(monitor_lost=AsyncMock()),
        )
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        runtime._closed = False
        runtime._voice_turn_generations = {"robot-01": 7}

        await runtime.start()
        task = runtime._voice_task if service == "voice" else runtime._room_task
        assert task is not None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            if exit_kind == "cancel":
                task.cancel()
            else:
                release.set()
            await asyncio.wait_for(shutdown_started.wait(), timeout=1)
            assert runtime._closed
            assert runtime._voice_turn_generations is None
            with pytest.raises(RuntimeError, match="stopped unexpectedly") as failure:
                await asyncio.wait_for(runtime.close(), timeout=2)
            if exit_kind == "error":
                assert isinstance(failure.value.__cause__, ValueError)
            assert runtime._room_stop.is_set()
            assert runtime._voice_task is None
            assert runtime._room_task is None
            assert task.done()
            runtime.coordinator.close.assert_awaited_once()
            runtime.pet.close.assert_awaited_once()
            runtime.conversation.stop.assert_awaited_once()
            runtime.client.aclose.assert_awaited_once()
            if service == "voice":
                runtime.conversation.speaker.monitor_lost.assert_awaited_once()
            with pytest.raises(RuntimeError, match="Closed runtime"):
                await runtime.start()
            # The fatal result is retained; a second close cannot reopen IO.
            with pytest.raises(RuntimeError, match="stopped unexpectedly"):
                await runtime.close()
            runtime.coordinator.close.assert_awaited_once()
        finally:
            release.set()
            if not runtime._closed:
                runtime._closed = True
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            shutdown = getattr(runtime, "_close_task", None)
            if shutdown is not None:
                await asyncio.gather(shutdown, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("owner", ["pet", "voice"])
def test_repeated_shutdown_retains_cancellation_resistant_owner(monkeypatch, owner):
    """A deadline is not permission to abandon or duplicate an async owner."""
    monkeypatch.setattr("desk_robot.runtime._RUNTIME_PET_STOP_TIMEOUT_S", 0.03)
    monkeypatch.setattr("desk_robot.runtime._RUNTIME_VOICE_STOP_TIMEOUT_S", 0.03)

    async def scenario():
        release = asyncio.Event()
        started = asyncio.Event()
        cancellation_seen = asyncio.Event()
        tasks = []

        async def stubborn_owner():
            tasks.append(asyncio.current_task())
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release.wait()

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(close=AsyncMock(
            side_effect=stubborn_owner if owner == "pet" else None,
        ))
        runtime.conversation = SimpleNamespace(stop=AsyncMock())
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = (
            asyncio.create_task(stubborn_owner()) if owner == "voice" else None
        )
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        if owner == "voice":
            await asyncio.wait_for(started.wait(), timeout=1)

        message = (
            "Pet observer shutdown unconfirmed" if owner == "pet"
            else "Native voice monitor shutdown unconfirmed"
        )
        try:
            with pytest.raises(TimeoutError, match=message):
                await runtime.close()
            await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
            task = tasks[0]
            assert not task.done() and task.cancelling() == 1
            with pytest.raises(TimeoutError, match=message):
                await runtime.close()
            assert tasks == [task]
            assert not task.done() and task.cancelling() == 1
            if owner == "pet":
                assert runtime._shutdown_step_tasks["Pet observer"] is task
                runtime.pet.close.assert_awaited_once()
            else:
                assert runtime._voice_task is task
            release.set()
            await asyncio.wait_for(task, timeout=1)
            assert not task.cancelled()
            if owner == "pet":
                assert "Pet observer" not in runtime._shutdown_step_tasks
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())


def test_spatial_invalidation_failure_does_not_skip_fleet_shutdown(monkeypatch):
    """One damaged map must not prevent any of five heads from stopping."""
    monkeypatch.setattr("desk_robot.dock_runtime.close_detector_pool", AsyncMock())

    async def scenario():
        robots = [
            SimpleNamespace(id=f"robot-{i:02d}", device_id=f"head-{i:02d}")
            for i in range(1, 6)
        ]
        invalidated = []

        def invalidate(robot_id, *, reason):
            assert reason == "runtime_closed"
            invalidated.append(robot_id)
            if robot_id == robots[1].id:
                raise ValueError("spatial invalidation fault")

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="hardware", robots=robots)
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(), shutdown_stop_failures={}
        )
        runtime.spatial = SimpleNamespace(invalidate_robot=invalidate)
        runtime.pet = SimpleNamespace(
            close=AsyncMock(), set_voice_monitor_ready=lambda ready: None,
        )
        speaker = SimpleNamespace(monitor_lost=AsyncMock())
        runtime.conversation = SimpleNamespace(stop=AsyncMock(), speaker=speaker)
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = SimpleNamespace(close=AsyncMock())
        runtime._voice_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        reader = asyncio.create_task(runtime._room_stop.wait())
        runtime._room_task = reader

        try:
            with pytest.raises(ValueError, match="spatial invalidation fault"):
                await runtime.close()
            assert invalidated == [robot.id for robot in robots]
            assert runtime._room_stop.is_set()
            assert reader.done() and not reader.cancelled()
            assert runtime._room_task is None
            assert speaker.monitor_lost.await_count == 5
            for robot in robots:
                speaker.monitor_lost.assert_any_await(robot)
            runtime.coordinator.close.assert_awaited_once()
            runtime.pet.close.assert_awaited_once()
            runtime.multimodal.close.assert_awaited_once()
            runtime.conversation.stop.assert_awaited_once()
            runtime.client.aclose.assert_awaited_once()
        finally:
            runtime._room_stop.set()
            await reader

    asyncio.run(scenario())


@pytest.mark.parametrize("close_during_warmup", [True, False])
def test_runtime_start_rechecks_ownership_after_detector_warmup(
    monkeypatch, close_during_warmup,
):
    """An awaited prewarm cannot reopen closed IO or orphan a second monitor."""
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        voice_stop = asyncio.Event()
        calls = []

        async def warm():
            calls.append("warm")
            if len(calls) == (1 if close_during_warmup else 2):
                entered.set()
            await release.wait()

        class Listener:
            def __init__(self, *args, **kwargs):
                calls.append("listener")

            async def run(self):
                await voice_stop.wait()

        monkeypatch.setattr("desk_robot.dock_runtime.prewarm_detector_pool", warm)
        monkeypatch.setattr("desk_robot.dock_runtime.close_detector_pool", AsyncMock())
        monkeypatch.setattr("desk_robot.runtime.VoiceEventListener", Listener)
        monkeypatch.setattr("desk_robot.runtime.secret", lambda name: "s" * 32)

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(
            mode="hardware", room_station_enabled=False,
            robots=[SimpleNamespace(
                id="robot-01", device_id="head01", dock_calibration="test",
            )],
            speech_bridge_url="http://127.0.0.1:8766",
            speech_bridge_token_env="SPEECH_TOKEN", pet_autostart_enabled=False,
        )
        runtime._closed = False
        runtime._voice_task = None
        runtime._room_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(
            close=AsyncMock(), set_voice_monitor_ready=lambda ready: None,
        )
        runtime.conversation = SimpleNamespace(
            stop=AsyncMock(), speaker=SimpleNamespace(monitor_lost=AsyncMock()),
        )
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None

        starts = [asyncio.create_task(runtime.start())]
        if not close_during_warmup:
            starts.append(asyncio.create_task(runtime.start()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            if close_during_warmup:
                await runtime.close()
            release.set()
            results = await asyncio.wait_for(
                asyncio.gather(*starts, return_exceptions=True), timeout=1,
            )
            if close_during_warmup:
                assert isinstance(results[0], RuntimeError)
                assert calls.count("listener") == 0
                assert runtime._voice_task is None
            else:
                assert results == [None, None]
                assert calls.count("listener") == 1
                assert runtime._voice_task is not None
        finally:
            release.set()
            voice_stop.set()
            await asyncio.gather(*starts, return_exceptions=True)
            if not runtime._closed:
                await runtime.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("exit_kind", ["error", "return", "cancel"])
def test_optional_room_service_exit_degrades_without_closing_runtime(monkeypatch, exit_kind):
    """A terminal room-feed exit invalidates cached context without closing robots."""
    import sys

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        class RoomFeed:
            def __init__(self, *args, **kwargs):
                pass

            async def run(self, stop):
                entered.set()
                await release.wait()
                if exit_kind == "error":
                    raise ValueError("usb bridge unplugged permanently")

        class VoiceListener:
            def __init__(self, *args, **kwargs):
                pass

            async def run(self):
                await asyncio.Event().wait()

        monkeypatch.setitem(sys.modules, "serial", SimpleNamespace())
        monkeypatch.setattr("desk_robot.runtime.RoomSerialFeed", RoomFeed)
        monkeypatch.setattr("desk_robot.runtime.VoiceEventListener", VoiceListener)
        monkeypatch.setattr("desk_robot.runtime.secret", lambda name: "s" * 32)
        monkeypatch.setattr("desk_robot.dock_runtime.close_detector_pool", AsyncMock())

        hub = SimpleNamespace(invalidate_room=AsyncMock())
        # Use a synchronous invalidate_room matching CameraFrameHub.invalidate_room
        invalidated = []
        hub.invalidate_room = lambda *, epoch=None: invalidated.append(epoch)

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(
            mode="hardware", room_station_enabled=True, room_station_port="/dev/cu.usbserial-1",
            room_station_soil_dry_adc=None, speech_bridge_url="http://127.0.0.1:8766",
            speech_bridge_token_env="SPEECH_TOKEN", pet_autostart_enabled=False,
            robots=[SimpleNamespace(id="robot-01", device_id="head01")],
        )
        runtime.coordinator = SimpleNamespace(close=AsyncMock(), shutdown_stop_failures={})
        runtime.pet = SimpleNamespace(close=AsyncMock(), set_voice_monitor_ready=lambda ready: None)
        runtime.conversation = SimpleNamespace(
            stop=AsyncMock(), speaker=SimpleNamespace(monitor_lost=AsyncMock()),
        )
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = SimpleNamespace(start_streams=lambda: None, close=AsyncMock(), hub=hub)
        runtime._voice_task = None
        runtime._room_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = ("stale",)
        runtime._room_dispatch_enqueued = False
        runtime._closed = False
        runtime._voice_turn_generations = {"robot-01": 7}

        await runtime.start()
        task = runtime._room_task
        assert task is not None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            if exit_kind == "cancel":
                task.cancel()
            else:
                release.set()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1)
            await asyncio.sleep(0)
            assert not runtime._closed
            assert runtime.room_station_degraded is True
            assert runtime._room_task is None
            assert runtime._room_dispatch_pending is None
            assert invalidated
            runtime.coordinator.close.assert_not_called()
        finally:
            release.set()
            await runtime.close()

    asyncio.run(scenario())


def test_fatal_shutdown_retries_unconfirmed_owner_and_preserves_fatal_error():
    """After fatal exit, a failed/timed-out close() can retry unconfirmed owners safely."""
    async def scenario():
        entered = asyncio.Event()
        release_second = asyncio.Event()
        attempts = 0

        async def flaky_coordinator_close():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                entered.set()
                await asyncio.Future()
            await release_second.wait()

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(side_effect=flaky_coordinator_close), shutdown_stop_failures={},
        )
        runtime.pet = SimpleNamespace(close=AsyncMock())
        runtime.conversation = SimpleNamespace(stop=AsyncMock())
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._fatal_service_error = RuntimeError("Native voice monitor stopped unexpectedly")
        runtime._closed = True

        # Replace _shutdown_step_tasks scenario with an already-done failed close task,
        # simulating a previous pass where coordinator.close raised/timed out.
        async def fail_first():
            await flaky_coordinator_close()

        # First pass triggers timeout in step("WROOM motion", ..., 4.0) if real 4s;
        # instead test a direct raising step so close() fails fast and allows retry!
        attempts = 0

        async def fail_then_succeed():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("simulated WROOM cleanup timeout")

        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(side_effect=fail_then_succeed), shutdown_stop_failures={},
        )
        with pytest.raises(RuntimeError, match="Native voice monitor stopped unexpectedly"):
            await runtime.close()
        assert attempts == 1

        # Second close() retries the unconfirmed coordinator step without re-running already
        # confirmed owners, while still surfacing sticky _fatal_service_error!
        with pytest.raises(RuntimeError, match="Native voice monitor stopped unexpectedly"):
            await runtime.close()
        assert attempts == 2
        runtime.pet.close.assert_awaited_once()
        runtime.conversation.stop.assert_awaited_once()
        runtime.client.aclose.assert_awaited_once()

    asyncio.run(scenario())


def test_shutdown_native_monitor_stop_timeout_stays_owned_by_runtime_and_conversation():
    async def scenario():
        release = asyncio.Event()
        tracked: list[asyncio.Task] = []

        async def stalled_stop(_robot):
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(
            mode="hardware",
            robots=[SimpleNamespace(id="robot-01", device_id="head01")],
        )
        runtime.coordinator = SimpleNamespace(close=AsyncMock(), shutdown_stop_failures={})
        runtime.pet = SimpleNamespace(
            close=AsyncMock(), set_voice_monitor_ready=lambda ready: None,
        )
        runtime.conversation = SimpleNamespace(
            stop=AsyncMock(),
            speaker=SimpleNamespace(monitor_lost=stalled_stop),
            _track_speaker_abort=tracked.append,
        )
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._closed = False

        try:
            with pytest.raises(RuntimeError, match="Native speaker shutdown STOP unconfirmed"):
                await runtime.close()
            assert len(tracked) >= 1
            assert any(not t.done() for t in tracked)
            assert runtime._has_unsettled_native_stop()
        finally:
            release.set()
            await asyncio.gather(*tracked, return_exceptions=True)

    asyncio.run(scenario())


def test_room_context_consumer_throttles_logs_and_sanitizes_payload(caplog):
    async def scenario():
        def bad_remember(_obs):
            raise RuntimeError("SECRET_ROOM_CO2_PAYLOAD=999ppm")

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(room_station_context_enabled=True)
        runtime.multimodal = SimpleNamespace(hub=SimpleNamespace(remember_room=bad_remember))
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        runtime.room_context_failures = 0
        runtime._closed = False
        loop = asyncio.get_running_loop()

        for _ in range(105):
            runtime._queue_room_observation(loop, object())
            await asyncio.sleep(0)
        assert runtime.room_context_failures == 105
        assert "SECRET_ROOM_CO2_PAYLOAD" not in caplog.text
        assert "Room context consumer failed (1 total): RuntimeError" in caplog.text
        assert caplog.text.count("Room context consumer failed") == 1

    asyncio.run(scenario())
