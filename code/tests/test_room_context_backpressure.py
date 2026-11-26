"""Latest-only shared room context cannot monopolize the realtime Mac loop."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from desk_robot.multimodal import CameraFrameHub
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


def test_pending_room_report_is_not_regranted_after_consent_cycle(settings):
    """The async USB handoff carries the grant that admitted each report."""
    runtime, delivered = make_runtime()
    runtime.settings = settings
    loop = QueuedLoop()

    settings.room_station_context_enabled = True
    first_generation = settings.room_station_consent_generation
    runtime._queue_room_observation(loop, room(1))
    settings.room_station_context_enabled = False
    settings.room_station_context_enabled = True
    assert settings.room_station_consent_generation == first_generation + 1
    loop.callbacks.pop()()
    assert delivered == []

    # A new real report under the new grant is still accepted normally.
    runtime._queue_room_observation(loop, room(2))
    loop.callbacks.pop()()
    assert [observation.seq for observation in delivered] == [2]

    # Sampling the USB feed while context is OFF cannot pre-authorize delivery
    # when a human grants sharing later.
    settings.room_station_context_enabled = False
    runtime._queue_room_observation(loop, room(3))
    assert not loop.callbacks
    settings.room_station_context_enabled = True
    assert [observation.seq for observation in delivered] == [2]

    runtime._queue_room_observation(loop, room(4))
    loop.callbacks.pop()()
    assert [observation.seq for observation in delivered] == [2, 4]
    assert runtime._room_dispatch_pending is None


def test_room_grant_changes_mid_usb_queue_snapshot_are_rejected():
    """Consent cannot flip while a serial thread samples its grant identity."""
    runtime, delivered = make_runtime()
    loop = QueuedLoop()

    class Settings:
        generation = 0
        switched = False

        @property
        def room_station_consent_generation(self):
            return self.generation

        @property
        def room_station_context_enabled(self):
            if not self.switched:
                # Deterministically simulate ON -> OFF -> ON after the
                # first generation read and before the permission read.
                self.switched = True
                self.generation += 1
            return True

    runtime.settings = Settings()
    runtime._queue_room_observation(loop, room(1))
    assert not loop.callbacks
    assert delivered == []

    # A subsequent sample captured entirely under the new grant is valid.
    runtime._queue_room_observation(loop, room(2))
    loop.callbacks.pop()()
    assert [observation.seq for observation in delivered] == [2]


@pytest.mark.parametrize("boundary", ["runtime", "hub"])
@pytest.mark.parametrize("change", ["consent", "disconnect"])
def test_room_delivery_preserves_original_epochs(monkeypatch, boundary, change):
    runtime, _ = make_runtime()
    runtime.settings = SimpleNamespace(
        mode="hardware", room_station_context_enabled=True,
        room_station_consent_generation=0,
    )
    hub = CameraFrameHub(["robot-01", "robot-02"], room_settings=runtime.settings)
    runtime.multimodal = SimpleNamespace(hub=hub)
    loop = QueuedLoop()

    runtime._queue_room_observation(loop, room(1))
    target, name = (
        (runtime, "_on_room_observation") if boundary == "runtime"
        else (hub, "remember_room")
    )
    original = getattr(target, name)

    def interrupt_delivery(observation, **kwargs):
        if change == "consent":
            runtime.settings.room_station_context_enabled = False
            runtime.settings.room_station_consent_generation += 1
            runtime.settings.room_station_context_enabled = True
        else:
            runtime._on_room_disconnect()
        original(observation, **kwargs)

    monkeypatch.setattr(target, name, interrupt_delivery)
    loop.callbacks.pop()()
    assert hub.shared_room is None
    monkeypatch.setattr(target, name, original)
    runtime._queue_room_observation(loop, room(2))
    loop.callbacks.pop()()
    assert hub.shared_room.seq == 2


def test_room_disabled_flood_never_schedules_dispatch():
    runtime, delivered = make_runtime()
    loop = QueuedLoop()
    runtime.settings.room_station_context_enabled = False
    for seq in range(1000):
        runtime._queue_room_observation(loop, room(seq))
        assert not loop.callbacks
    assert runtime._room_dispatch_pending is None
    assert runtime._room_dispatch_enqueued is False

    runtime.settings.room_station_context_enabled = True
    runtime._queue_room_observation(loop, room(1000))
    assert len(loop.callbacks) == 1
    runtime.settings.room_station_context_enabled = False
    runtime._queue_room_observation(loop, room(1001))
    assert runtime._room_dispatch_pending is None
    runtime.settings.room_station_context_enabled = True
    runtime._queue_room_observation(loop, room(1002))
    assert len(loop.callbacks) == 1
    loop.callbacks.pop()()
    assert [item.seq for item in delivered] == [1002]
