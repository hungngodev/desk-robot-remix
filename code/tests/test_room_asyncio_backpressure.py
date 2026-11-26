"""Exercise the real asyncio wakeup path with a synthetic 100 Hz room burst."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from desk_robot.room_station import SENSORS, RoomObservation, fresh_room_summary
from desk_robot.runtime import Runtime


@pytest.mark.parametrize("retire", [False, True])
def test_room_thread_burst_real_asyncio_loop(monkeypatch, retire):
    async def scenario():
        runtime = Runtime.__new__(Runtime)
        runtime._closed = False
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        runtime._room_connection_epoch = 0
        runtime.settings = SimpleNamespace(
            room_station_context_enabled=True, room_station_consent_generation=1,
        )
        delivered = []
        runtime.multimodal = SimpleNamespace(
            hub=SimpleNamespace(remember_room=delivered.append),
        )
        loop = asyncio.get_running_loop()
        schedule = loop.call_soon_threadsafe
        wakeups = []

        def count_wakeup(callback, *args, **kwargs):
            wakeups.append(callback)
            return schedule(callback, *args, **kwargs)

        monkeypatch.setattr(loop, "call_soon_threadsafe", count_wakeup)
        errors = []

        def produce():
            try:
                for seq in range(1, 1001):
                    readings = {sensor: {"valid": False} for sensor in SENSORS}
                    readings["soil"] = {"valid": True, "raw_adc": seq}
                    runtime._queue_room_observation(loop, RoomObservation(
                        seq=seq, at_ms=seq * 10, received_at=100 + seq / 100,
                        readings=readings, summary=f"Station soil probe raw ADC {seq}",
                        sensor_ages_ms={"soil": 0},
                    ))
            except Exception as exc:
                errors.append(exc)

        # Freeze consumption, not the producer. The logical sensor clock advances
        # by 10 ms per report; no wall-clock sleeps or scheduler luck are required.
        worker = threading.Thread(target=produce, daemon=True)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert not errors
        assert len(wakeups) == 1
        assert delivered == []
        assert runtime._room_dispatch_pending[0].seq == 1000
        if retire:
            runtime._closed = True
            runtime._on_room_disconnect()
        await asyncio.sleep(0)
        assert runtime._room_dispatch_pending is None
        assert runtime._room_dispatch_enqueued is False
        if retire:
            assert delivered == []
            runtime._queue_room_observation(loop, RoomObservation(
                seq=1001, at_ms=10010, received_at=110.01, readings={}, summary="late",
            ))
            assert len(wakeups) == 1
        else:
            assert [item.seq for item in delivered] == [1000]
            latest = delivered[0]
            assert fresh_room_summary(latest, now=113) == "Station soil probe raw ADC 1000"
            assert fresh_room_summary(latest, now=113.001) is None

    asyncio.run(scenario())
