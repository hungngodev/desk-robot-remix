"""Latest-only shared room context cannot monopolize the realtime Mac loop."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from desk_robot.room_station import RoomObservation
from desk_robot.runtime import Runtime


class QueuedLoop:
    def __init__(self):
        self.callbacks = []

    def call_soon_threadsafe(self, callback):
        self.callbacks.append(callback)


def make_runtime():
    runtime = Runtime.__new__(Runtime)
    runtime._room_dispatch_lock = threading.Lock()
    runtime._room_dispatch_pending = None
    runtime._room_dispatch_enqueued = False
    runtime._closed = False
    delivered = []
    runtime.settings = SimpleNamespace(room_station_context_enabled=True)
    runtime.multimodal = SimpleNamespace(
        hub=SimpleNamespace(remember_room=delivered.append)
    )
    return runtime, delivered


def room(seq):
    return RoomObservation(
        seq=seq, at_ms=seq, received_at=float(seq),
        readings={}, summary=f"Room sample {seq}",
    )


def test_room_usb_burst_schedules_one_callback_and_retains_freshest():
    runtime, delivered = make_runtime()
    loop = QueuedLoop()

    def producer():
        for seq in range(1000):
            runtime._queue_room_observation(loop, room(seq))

    worker = threading.Thread(target=producer)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    # Enqueueing 1000 replaceable environmental samples must never enqueue
    # 1000 event loop callbacks ahead of the human voice owner.
    assert len(loop.callbacks) == 1
    assert delivered == []
    loop.callbacks.pop()()
    assert [item.seq for item in delivered] == [999]
    assert runtime._room_dispatch_pending is None
    assert runtime._room_dispatch_enqueued is False

    runtime._queue_room_observation(loop, room(1000))
    assert len(loop.callbacks) == 1
    loop.callbacks.pop()()
    assert [item.seq for item in delivered] == [999, 1000]


def test_room_callback_pending_at_shutdown_cannot_publish_late_evidence():
    runtime, delivered = make_runtime()
    loop = QueuedLoop()
    runtime._queue_room_observation(loop, room(1))
    runtime._closed = True
    runtime._room_dispatch_pending = None  # Runtime.close clears queued data.
    loop.callbacks.pop()()
    runtime._queue_room_observation(loop, room(2))
    assert delivered == []
    assert not loop.callbacks
    assert runtime._room_dispatch_pending is None


def test_closing_loop_clears_pending_usb_observation_and_fails_closed():
    runtime, _ = make_runtime()

    class ClosingLoop:
        def call_soon_threadsafe(self, callback):
            runtime._closed = True
            raise RuntimeError("Event loop is closed")

    runtime._queue_room_observation(ClosingLoop(), room(1))
    assert runtime._room_dispatch_pending is None
    assert runtime._room_dispatch_enqueued is False


def test_unexpected_live_loop_scheduling_failure_is_not_suppressed():
    runtime, _ = make_runtime()

    class BrokenLoop:
        def call_soon_threadsafe(self, callback):
            raise RuntimeError("Not a normal shutdown")

    with pytest.raises(RuntimeError, match="Not a normal shutdown"):
        runtime._queue_room_observation(BrokenLoop(), room(1))
    assert runtime._room_dispatch_pending is None
    assert runtime._room_dispatch_enqueued is False
