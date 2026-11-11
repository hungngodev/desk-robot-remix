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
