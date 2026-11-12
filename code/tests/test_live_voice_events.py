"""Mac event consumer keeps only physical Xiaozhi identity and ordered turns."""
import httpx
import pytest
from desk_robot.live_voice_events import VoiceEventListener


async def test_mac_preempts_real_human_interruptions_once():
    delivered = []
    def mock(request):
        assert request.headers["Authorization"] == "Bearer " + "s" * 32
        assert request.url.path == "/events"
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 2, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 4, "reset": False, "lost": False,
            "events": [
                {"seq": 3, "robot_id": "robot-01",
                 "kind": "normal", "source": "xiaozhi_aec_vad"},
                {"seq": 4, "robot_id": "robot-02",
                 "kind": "group", "source": "xiaozhi_aec_vad"},
            ],
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def preempt(robot, source):
            delivered.append((robot, source))
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=preempt,
        )
        assert await watcher.poll() == 0
        assert await watcher.poll() == 2
        assert delivered == [("robot-01", "normal"), ("robot-02", "group")]
        assert watcher.cursor == 4 and watcher.handled == 2


async def test_gap_preempts_all_robot_speech_and_rebaselines():
    sent = []
    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 2, "events": [], "lost": False, "reset": False,
            })
        return httpx.Response(200, json={
            "cursor": 140, "events": [], "lost": True, "reset": False,
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def cancel(robot, source):
            sent.append((robot, source))
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=cancel,
        )
        await watcher.poll()
        assert await watcher.poll() == 0
        assert sent == [("robot-01", "gap"), ("robot-02", "gap")]
        assert watcher.cursor == 140


@pytest.mark.parametrize("event", [
    {"seq": 3, "robot_id": "robot-99", "kind": "normal",
     "source": "xiaozhi_aec_vad"},
    {"seq": 4, "robot_id": "robot-01", "kind": "normal",
     "source": "xiaozhi_aec_vad"},
    {"seq": 3, "robot_id": "robot-01", "kind": "normal", "source": "manual"},
    {"seq": 3, "robot_id": "robot-01", "kind": "unknown",
     "source": "xiaozhi_aec_vad"},
])
async def test_bad_event_source_is_not_fabricated_voice(event):
    calls = []
    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 2, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 3, "events": [event], "reset": False, "lost": False,
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def cancel(robot, source):
            calls.append(robot)
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=cancel,
        )
        await watcher.poll()
        with pytest.raises(ValueError):
            await watcher.poll()
        assert calls == [] and watcher.cursor == 2


async def test_restart_never_replays_old_server_voice():
    count = 0
    def mock(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(200, json={
                "cursor": 87, "events": [], "reset": False, "lost": False,
            })
        if count == 2:
            return httpx.Response(200, json={
                "cursor": 1, "events": [], "reset": True, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 1, "events": [], "reset": False, "lost": False,
        })
    delivered = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def cancel(robot, source):
            delivered.append((robot, source))
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=cancel,
        )
        await watcher.poll()
        assert await watcher.poll() == 0 and watcher.cursor is None
        # Cancel potentially obsolete audio on reset, but never replay
        # server events from the old epoch.
        assert delivered == [("robot-01", "reset")]
        assert await watcher.poll() == 0 and watcher.cursor == 1
        assert delivered == [("robot-01", "reset")]


async def test_event_transport_failure_preempts_once_until_recovered():
    import asyncio

    requests = 0
    cancelled = []

    def mock(request):
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(200, json={
                "cursor": 4, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(503, json={"error": "temporarily unavailable"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def cancel(robot, source):
            cancelled.append((robot, source))

        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-02", "robot-01"}, on_interrupt=cancel,
        )
        assert await watcher.poll() == 0
        task = asyncio.create_task(watcher.run())
        try:
            for _ in range(100):
                if cancelled:
                    break
                await asyncio.sleep(0.01)
            assert cancelled == [
                ("robot-01", "stream_unavailable"),
                ("robot-02", "stream_unavailable"),
            ]
            assert watcher.last_error is not None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_idle_speech_start_uses_current_xiaozhi_vad_not_fake_aec():
    delivered = []

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 2, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 3, "reset": False, "lost": False,
            "events": [{
                "seq": 3, "robot_id": "robot-01",
                "kind": "speech_start", "source": "xiaozhi_server_vad",
            }],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def on_voice(robot_id, kind):
            delivered.append((robot_id, kind))
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=on_voice,
        )
        assert await listener.poll() == 0
        assert await listener.poll() == 1
        assert delivered == [("robot-01", "speech_start")]
        assert listener.cursor == 3


async def test_shared_fleet_audio_is_preempted_only_once_on_event_gap():
    called = []

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 1, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 100, "events": [], "reset": False, "lost": True,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def individual(robot, reason):
            called.append(("individual", robot, reason))

        async def global_cancel(reason):
            called.append(("global", reason))

        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={f"robot-0{i}" for i in range(1, 6)},
            on_interrupt=individual,
            on_global_interrupt=global_cancel,
        )
        assert await listener.poll() == 0
        assert await listener.poll() == 0
        assert called == [("global", "gap")]


async def test_monitor_health_is_lost_on_gap_until_authenticated_resumption():
    polls = 0
    health, faults = [], []

    def mock(request):
        nonlocal polls
        polls += 1
        if polls == 1:
            return httpx.Response(200, json={
                "cursor": 5, "events": [], "reset": False, "lost": False,
            })
        if polls == 2:
            return httpx.Response(200, json={
                "cursor": 19, "events": [], "reset": False, "lost": True,
            })
        return httpx.Response(200, json={
            "cursor": 19, "events": [], "reset": False, "lost": False,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def on_event(robot_id, kind):
            raise AssertionError("No fake voice events may be delivered")

        async def global_stop(reason):
            faults.append(reason)

        async def monitor_ready(ready):
            health.append(ready)

        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=on_event,
            on_global_interrupt=global_stop,
            on_monitor_ready=monitor_ready,
        )
        assert not listener.monitor_ready
        await listener.poll()
        assert listener.monitor_ready
        await listener.poll()
        assert not listener.monitor_ready
        assert faults == ["gap"]
        await listener.poll()
        assert listener.monitor_ready
        assert health == [True, False, True]


async def test_hardware_monitor_refuses_legacy_or_null_voice_snapshot():
    for payload in (
        {"cursor": 4, "events": [], "reset": False, "lost": False},
        {"cursor": 4, "events": [], "reset": False, "lost": False,
         "active_human_robots": None},
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            )
        ) as client:
            async def deliver(robot_id, kind):
                raise AssertionError("No unauthenticated voice turn")
            listener = VoiceEventListener(
                client, url="http://127.0.0.1:8766", token="s" * 32,
                robot_ids={"robot-01"}, on_interrupt=deliver,
                require_snapshot=True,
            )
            with pytest.raises(ValueError, match="snapshot required"):
                await listener.poll()
            assert not listener.monitor_ready
            assert listener.cursor is None


async def test_current_vad_snapshot_survives_missed_start_at_bootstrap():
    snapshots = []
    requests = 0

    def mock(request):
        nonlocal requests
        requests += 1
        active = ["robot-02"] if requests == 1 else []
        return httpx.Response(200, json={
            "cursor": 12, "events": [], "reset": False, "lost": False,
            "active_human_robots": active,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def on_event(robot_id, kind):
            raise AssertionError("No synthetic speech event allowed")

        async def snapshot(active):
            snapshots.append(active)

        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=on_event,
            on_speech_snapshot=snapshot,
        )
        assert await listener.poll() == 0
        assert snapshots == [frozenset({"robot-02"})]
        assert await listener.poll() == 0
        assert snapshots[-1] == frozenset()


async def test_rejects_unrecognized_robot_in_live_vad_snapshot():
    def mock(request):
        return httpx.Response(200, json={
            "cursor": 5, "events": [], "reset": False, "lost": False,
            "active_human_robots": ["robot-forged"],
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def on_event(robot_id, kind):
            raise AssertionError("Untrusted snapshot must not generate callbacks")
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=on_event,
        )
        with pytest.raises(ValueError, match="snapshot"):
            await listener.poll()


async def test_idle_speech_end_event_is_authenticated_and_ordered():
    delivered = []
    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 10, "events": [], "reset": False, "lost": False
            })
        return httpx.Response(200, json={
            "cursor": 12, "reset": False, "lost": False,
            "events": [
                {"seq": 11, "robot_id": "robot-01", "kind": "speech_start",
                 "source": "xiaozhi_server_vad"},
                {"seq": 12, "robot_id": "robot-01", "kind": "speech_end",
                 "source": "xiaozhi_server_vad"},
            ]
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def handle(robot, event):
            delivered.append((robot, event))
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=handle,
        )
        await listener.poll()
        assert await listener.poll() == 2
    assert delivered == [
        ("robot-01", "speech_start"), ("robot-01", "speech_end")
    ]
