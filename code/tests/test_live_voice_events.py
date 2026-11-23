"""Mac event consumer keeps only physical Xiaozhi identity and ordered turns."""
import httpx
import pytest
from desk_robot.live_voice_events import VoiceEventListener


async def test_authenticated_turn_generations_precede_slow_vad_and_clear_on_reset():
    observed = []
    request_count = 0

    def mock(request):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(200, json={
                "cursor": 4, "events": [], "reset": False, "lost": False,
                "active_human_robots": [],
                "voice_turn_generations": {"robot-01": 5, "robot-02": 3},
            })
        if request_count == 2:
            return httpx.Response(200, json={
                "cursor": 5, "reset": False, "lost": False,
                "active_human_robots": ["robot-01"],
                "voice_turn_generations": {"robot-01": 6, "robot-02": 3},
                "events": [{
                    "seq": 5, "robot_id": "robot-01", "kind": "speech_start",
                    "source": "xiaozhi_server_vad", "voice_turn_generation": 6,
                }],
            })
        if request_count == 3:
            return httpx.Response(200, json={
                "cursor": 1, "events": [], "reset": True, "lost": False,
                "active_human_robots": [],
                "voice_turn_generations": {"robot-01": 0, "robot-02": 0},
            })
        return httpx.Response(200, json={
            "cursor": 1, "events": [], "reset": False, "lost": False,
            "active_human_robots": [],
            "voice_turn_generations": {"robot-01": 0, "robot-02": 0},
        })

    snapshots = []

    def owner(generations):
        snapshots.append(None if generations is None else dict(generations))

    async def interrupt(robot_id, kind):
        assert snapshots[-1] == {"robot-01": 6, "robot-02": 3}
        observed.append((robot_id, kind))

    async def global_stop(reason):
        assert reason == "reset"
        assert snapshots[-1] is None
        observed.append(("fleet", reason))

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=interrupt,
            on_global_interrupt=global_stop,
            on_voice_generations=owner, require_turn_generations=True,
        )
        assert await listener.poll() == 0
        assert snapshots[-1] == {"robot-01": 5, "robot-02": 3}
        assert await listener.poll() == 1
        assert observed == [("robot-01", "speech_start")]
        assert await listener.poll() == 0 and listener.cursor is None
        assert snapshots[-1] is None
        assert await listener.poll() == 0
        assert snapshots[-1] == {"robot-01": 0, "robot-02": 0}
        assert observed[-1] == ("fleet", "reset")


@pytest.mark.parametrize("generations", [
    None, {"robot-01": True}, {"robot-01": -1},
    {"robot-99": 2}, {"robot-01": 2**63},
])
async def test_strict_turn_generation_bootstrap_rejects_untrusted_provenance(
    generations,
):
    def mock(request):
        return httpx.Response(200, json={
            "cursor": 4, "events": [], "reset": False, "lost": False,
            "active_human_robots": [],
            **({} if generations is None else {"voice_turn_generations": generations}),
        })
    delivered = []

    def owner(snapshot):
        delivered.append(snapshot)

    async def interrupt(robot, kind):
        raise AssertionError("Rejected provenance cannot dispatch VAD")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=interrupt,
            on_voice_generations=owner, require_turn_generations=True,
        )
        with pytest.raises(ValueError, match="generation"):
            await listener.poll()
        assert listener.cursor is None
        assert delivered == []


async def test_runtime_only_retains_authenticated_current_voice_owner_on_healthy_monitor():
    """Mac tool authority stays empty until the signed Xiaozhi VAD feed arrives."""
    from types import SimpleNamespace

    from desk_robot.runtime import Runtime

    states = []
    runtime = Runtime.__new__(Runtime)
    runtime._closed = False
    runtime._voice_turn_generations = None
    runtime.pet = SimpleNamespace(set_voice_monitor_ready=states.append)
    runtime.coordinator = SimpleNamespace(stop_active_exploration=None)
    runtime._on_voice_generations({"robot-01": 8, "robot-02": 4})
    assert runtime._voice_turn_generations == {"robot-01": 8, "robot-02": 4}
    runtime._on_voice_generations({"robot-01": 9})
    assert runtime._voice_turn_generations == {"robot-01": 9}
    await runtime._on_voice_monitor_ready(False)
    assert runtime._voice_turn_generations is None and states == [False]
    runtime._on_voice_generations({"robot-01": 10})
    assert runtime._voice_turn_generations == {"robot-01": 10}
    runtime._closed = True
    runtime._on_voice_generations({"robot-01": 11})
    assert runtime._voice_turn_generations == {"robot-01": 10}


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
    {"seq": 3, "robot_id": ["robot-01"], "kind": "normal",
     "source": "xiaozhi_aec_vad"},
    {"seq": 3, "robot_id": {"id": "robot-01"}, "kind": "normal",
     "source": "xiaozhi_aec_vad"},
    {"seq": 3, "robot_id": None, "kind": "normal",
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
                lambda request, payload=payload: httpx.Response(200, json=payload)
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


async def test_fleet_fallback_interrupts_all_robots_despite_one_offline_head():
    attempted = []

    async def interrupt(robot_id, reason):
        attempted.append((robot_id, reason))
        if robot_id == "robot-01":
            raise OSError("One head disconnected")

    async with httpx.AsyncClient() as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-02", "robot-01"}, on_interrupt=interrupt,
        )
        with pytest.raises(OSError, match="disconnected"):
            await listener._preempt_all("stream_unavailable")
    assert attempted == [
        ("robot-01", "stream_unavailable"),
        ("robot-02", "stream_unavailable"),
    ]


async def test_failed_monitor_false_callback_retries_even_after_local_flag_clears():
    health = []
    first_failure = True

    async def report(ready):
        nonlocal first_failure
        health.append(ready)
        if not ready and first_failure:
            first_failure = False
            raise OSError("Failed to notify pet owner")

    async def interrupted(robot_id, reason):
        raise AssertionError("No audio event expected")

    async with httpx.AsyncClient() as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=interrupted,
            on_monitor_ready=report,
        )
        await listener._set_monitor_ready(True)
        with pytest.raises(OSError, match="notify"):
            await listener._set_monitor_ready(False)
        assert listener.monitor_ready is False
        await listener._set_monitor_ready(False)
        assert listener._monitor_delivered is False
        assert health == [True, False, False]


async def test_voice_callback_failure_silences_fleet_without_terminating_watcher():
    import asyncio

    received = []
    health = []
    preempted = asyncio.Event()

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 1, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 2, "reset": False, "lost": False,
            "events": [{
                "seq": 2, "robot_id": "robot-01", "kind": "normal",
                "source": "xiaozhi_aec_vad",
            }],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def broken_head(robot_id, kind):
            received.append((robot_id, kind))
            raise OSError("Head interrupt transport disconnected")

        async def global_abort(reason):
            assert reason == "stream_unavailable"
            preempted.set()

        async def monitor(ready):
            health.append(ready)

        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=broken_head,
            on_global_interrupt=global_abort, on_monitor_ready=monitor,
        )
        await listener.poll()
        watcher = asyncio.create_task(listener.run())
        try:
            await asyncio.wait_for(preempted.wait(), timeout=2)
            # The callback event fires before the listener finishes reporting
            # stream health. Wait for that state, not a scheduler-dependent tick.
            async def monitor_reported_failure():
                while health != [True, False]:
                    await asyncio.sleep(0)

            await asyncio.wait_for(monitor_reported_failure(), timeout=1)
            assert not watcher.done()
            assert listener.monitor_ready is False
            assert listener.cursor == 1  # failed callback never consumed seq 2
            assert received == [("robot-01", "normal")]
            assert health == [True, False]
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


async def test_failed_global_abort_is_retried_while_voice_stream_is_unavailable():
    import asyncio

    abort_attempts = []
    eventually_aborted = asyncio.Event()

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 1, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(503, json={"error": "offline"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        async def on_event(robot_id, reason):
            raise AssertionError("No event on failed transport")

        async def global_abort(reason):
            abort_attempts.append(reason)
            if len(abort_attempts) == 1:
                raise OSError("Transient audio bridge error")
            eventually_aborted.set()

        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=on_event,
            on_global_interrupt=global_abort,
        )
        await listener.poll()
        task = asyncio.create_task(listener.run())
        try:
            await asyncio.wait_for(eventually_aborted.wait(), timeout=3)
            # The abort callback signals before run() records the stream
            # failure; await that transition explicitly.
            async def stream_failure_recorded():
                while not listener._stream_failed:
                    await asyncio.sleep(0)

            await asyncio.wait_for(stream_failure_recorded(), timeout=1)
            assert not task.done()
            assert abort_attempts == [
                "stream_unavailable", "stream_unavailable",
            ]
            assert listener.monitor_ready is False
            assert listener._stream_failed is True
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_slow_voice_head_cannot_block_other_fleet_interrupts():
    import asyncio

    attempted = []
    fast_done = asyncio.Event()
    never_finishes = asyncio.Event()

    async def interrupt(robot_id, reason):
        attempted.append(robot_id)
        if robot_id == "robot-01":
            await never_finishes.wait()
        else:
            fast_done.set()

    async with httpx.AsyncClient() as client:
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=interrupt,
        )
        with pytest.raises(TimeoutError, match="Fleet interruption incomplete"):
            await asyncio.wait_for(
                watcher._preempt_all("stream_unavailable"), timeout=1
            )
        assert fast_done.is_set()  # second pet interrupted without waiting
        assert sorted(attempted) == ["robot-01", "robot-02"]
        # A timed-out device does not count as a successful physical flush.


async def test_explicit_listener_task_cancellation_propagates_with_hung_head():
    import asyncio

    started = asyncio.Event()
    blocked = asyncio.Event()

    async def interrupt(robot_id, reason):
        started.set()
        await blocked.wait()

    async with httpx.AsyncClient() as client:
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=interrupt,
        )
        task = asyncio.create_task(watcher._preempt_all("reset"))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_hung_shared_audio_owner_times_out_without_claiming_flush():
    import asyncio

    entered = asyncio.Event()
    blocked = asyncio.Event()
    attempts = []

    async def shared_abort(reason):
        attempts.append(reason)
        entered.set()
        await blocked.wait()

    async def per_robot_abort(robot_id, reason):
        raise AssertionError("Shared owner must be the only abort path")

    async with httpx.AsyncClient() as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"},
            on_interrupt=per_robot_abort,
            on_global_interrupt=shared_abort,
        )
        with pytest.raises(TimeoutError, match="Shared fleet interruption incomplete"):
            await asyncio.wait_for(listener._preempt_all("stream_unavailable"), 1)
        assert entered.is_set()
        assert attempts == ["stream_unavailable"]
        assert listener._stream_failed is False
        # Cancellation is a request, not an ACK. Wait for the first task to
        # finish teardown before asserting an independent retry can begin.
        async def previous_abort_finished():
            while (listener._global_abort_task is not None
                   and not listener._global_abort_task.done()):
                await asyncio.sleep(0)

        await asyncio.wait_for(previous_abort_finished(), timeout=1)
        # An abort timeout must remain retryable, never an acoustic ACK.
        with pytest.raises(TimeoutError, match="Shared fleet interruption incomplete"):
            await asyncio.wait_for(listener._preempt_all("stream_unavailable"), 1)
        assert attempts == ["stream_unavailable", "stream_unavailable"]


async def test_failed_bootstrap_snapshot_does_not_consume_cursor():
    requests = []
    snapshots = []
    reject_first = True

    def mock(request):
        requests.append(dict(request.url.params))
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 10, "events": [], "reset": False, "lost": False,
                "active_human_robots": ["robot-01"],
            })
        raise AssertionError("Cannot poll events before bootstrap is accepted")

    async def snapshot(active):
        nonlocal reject_first
        snapshots.append(active)
        if reject_first:
            reject_first = False
            raise OSError("Speech owner unavailable")

    async def interrupt(robot_id, reason):
        raise AssertionError("No replayed event may interrupt")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=interrupt,
            on_speech_snapshot=snapshot, require_snapshot=True,
        )
        with pytest.raises(OSError, match="Speech owner"):
            await listener.poll()
        assert listener.cursor is None and listener.monitor_ready is False
        assert await listener.poll() == 0
        assert listener.cursor == 10 and listener.monitor_ready is True
        assert len(snapshots) == 2
        assert all(request.get("bootstrap") == "1" for request in requests)


async def test_failed_bootstrap_health_notification_retries_bootstrap():
    requests = []
    ready_calls = []

    def mock(request):
        requests.append(dict(request.url.params))
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 7, "events": [], "reset": False, "lost": False,
            })
        raise AssertionError("Failed bootstrap must not switch to event polling")

    async def health(ready):
        ready_calls.append(ready)
        if len(ready_calls) == 1:
            raise OSError("Health consumer unavailable")

    async def interrupt(robot_id, reason):
        raise AssertionError("No events expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=interrupt,
            on_monitor_ready=health,
        )
        with pytest.raises(OSError, match="Health consumer"):
            await listener.poll()
        assert listener.cursor is None
        assert listener._monitor_delivered is None
        assert await listener.poll() == 0
        assert listener.cursor == 7 and ready_calls == [True, True]
        assert len(requests) == 2
        assert all(request.get("bootstrap") == "1" for request in requests)


async def test_cancellation_resistant_shared_abort_is_single_flight():
    """Repeated outage polls cannot overlap two shared audio owner callbacks."""
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    attempts = []

    async def shared_abort(reason):
        attempts.append(reason)
        entered.set()
        # A real transport may ignore cancellation during socket teardown.
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    async def per_robot_abort(robot_id, reason):
        raise AssertionError("Shared owner is the only audio abort path")

    async with httpx.AsyncClient() as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"},
            on_interrupt=per_robot_abort,
            on_global_interrupt=shared_abort,
        )
        try:
            first = asyncio.create_task(listener._preempt_all("stream_unavailable"))
            await asyncio.wait_for(entered.wait(), timeout=1)
            with pytest.raises(TimeoutError, match="Shared fleet interruption incomplete"):
                await asyncio.wait_for(first, timeout=1)
            assert len(attempts) == 1
            with pytest.raises(TimeoutError, match="Shared fleet interruption incomplete"):
                await asyncio.wait_for(
                    listener._preempt_all("stream_unavailable"), timeout=1
                )
            assert attempts == ["stream_unavailable"]
            release.set()
            await asyncio.wait_for(listener._global_abort_task, timeout=1)
            # Completed callback no longer retains the fleet audio slot.
            await listener._preempt_all("stream_unavailable")
            assert attempts == ["stream_unavailable", "stream_unavailable"]
        finally:
            release.set()
            if listener._global_abort_task is not None:
                await asyncio.wait_for(listener._global_abort_task, timeout=1)


async def test_global_audio_abort_owning_task_cancellation_is_not_a_flush():
    """Cancellation of the poller does not free an unresponsive audio owner."""
    import asyncio

    entered = asyncio.Event()
    released = asyncio.Event()
    attempts = 0

    async def resistant(_reason):
        nonlocal attempts
        attempts += 1
        entered.set()
        while not released.is_set():
            try:
                await released.wait()
            except asyncio.CancelledError:
                continue

    async with httpx.AsyncClient() as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"},
            on_interrupt=lambda robot_id, reason: None,
            on_global_interrupt=resistant,
        )
        first = asyncio.create_task(listener._preempt_all("reset"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            with pytest.raises(TimeoutError, match="Shared fleet interruption incomplete"):
                await listener._preempt_all("gap")
            assert attempts == 1
        finally:
            released.set()
            if listener._global_abort_task is not None:
                await asyncio.wait_for(listener._global_abort_task, timeout=1)


@pytest.mark.parametrize("event_name", ["reset", "gap"])
async def test_gap_audio_preempts_before_failed_monitor_notification(event_name):
    """An unhealthy VAD bridge must abort audio despite a dead health sink."""
    calls = []
    requests = 0

    def mock(request):
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(200, json={
                "cursor": 5, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 6, "events": [],
            "reset": event_name == "reset",
            "lost": event_name == "gap",
        })

    async def individual(_robot, _kind):
        raise AssertionError("Shared floor owns interruption")

    async def abort(reason):
        calls.append(("abort", reason))

    async def health(ready):
        calls.append(("health", ready))
        if not ready:
            raise OSError("Monitor health transport unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"},
            on_interrupt=individual,
            on_global_interrupt=abort,
            on_monitor_ready=health,
        )
        await listener.poll()
        with pytest.raises(OSError, match="Monitor health"):
            await listener.poll()
        assert calls == [
            ("health", True), ("abort", event_name), ("health", False),
        ]
        assert listener.monitor_ready is False
        assert listener.cursor == 5  # never accept reset/gap without health


async def test_voice_stream_outage_preempts_while_health_callback_is_stalled():
    """A disconnected health monitor must not delay real shared audio abort."""
    import asyncio

    requests = 0
    aborted = asyncio.Event()
    blocking_health = asyncio.Event()
    health_entered = asyncio.Event()

    def mock(_request):
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(200, json={
                "cursor": 2, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(503, json={"error": "head offline"})

    async def global_abort(_reason):
        aborted.set()

    async def health(ready):
        if not ready:
            health_entered.set()
            await blocking_health.wait()

    async def no_single_robot_abort(_id, _reason):
        raise AssertionError("Shared audio owner must own fleet interruption")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"},
            on_interrupt=no_single_robot_abort,
            on_global_interrupt=global_abort,
            on_monitor_ready=health,
        )
        await listener.poll()
        runner = asyncio.create_task(listener.run())
        try:
            await asyncio.wait_for(health_entered.wait(), timeout=2)
            assert aborted.is_set()
            assert listener.monitor_ready is False
        finally:
            blocking_health.set()
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)


async def test_one_stalled_xiaozhi_event_never_duplicates_its_interrupt():
    """The server can replay an event while the first callback ignores cancel."""
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    dispatched = []

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 9, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 10, "reset": False, "lost": False,
            "events": [{
                "seq": 10, "robot_id": "robot-01",
                "kind": "normal", "source": "xiaozhi_aec_vad",
            }],
        })

    async def stubborn_interrupt(robot_id, kind):
        dispatched.append((robot_id, kind))
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=stubborn_interrupt,
        )
        await watcher.poll()
        try:
            with pytest.raises(TimeoutError, match="Voice interruption incomplete"):
                await watcher.poll()
            assert entered.is_set() and watcher.cursor == 9
            with pytest.raises(TimeoutError, match="Voice interruption incomplete"):
                await watcher.poll()
            assert dispatched == [("robot-01", "normal")]
            release.set()
            assert await watcher.poll() == 1
            assert watcher.cursor == 10 and watcher.handled == 1
            assert dispatched == [("robot-01", "normal")]
        finally:
            release.set()
            if watcher._event_task is not None:
                await asyncio.wait_for(watcher._event_task, timeout=1)


async def test_failed_xiaozhi_event_interrupt_is_retryable_without_cursor_loss():
    calls = 0

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 5, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 6, "reset": False, "lost": False,
            "events": [{
                "seq": 6, "robot_id": "robot-01",
                "kind": "speech_start", "source": "xiaozhi_server_vad",
            }],
        })

    async def unreliable(_robot_id, _kind):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("head temporarily unreachable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=unreliable,
        )
        await watcher.poll()
        with pytest.raises(OSError, match="temporarily unreachable"):
            await watcher.poll()
        assert watcher.cursor == 5
        assert await watcher.poll() == 1
        assert calls == 2 and watcher.cursor == 6


async def test_repeated_fleet_fallback_does_not_duplicate_unresponsive_head():
    """A cancellation-resistant one-pet transport cannot spawn infinite tasks."""
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()
    attempts = []

    async def interrupt(robot_id, reason):
        attempts.append((robot_id, reason))
        if robot_id != "robot-01":
            return
        started.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    async with httpx.AsyncClient() as client:
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=interrupt,
        )
        try:
            with pytest.raises(TimeoutError, match="Fleet interruption incomplete"):
                await watcher._preempt_all("stream_unavailable")
            assert started.is_set()
            with pytest.raises(TimeoutError, match="Fleet interruption incomplete"):
                await watcher._preempt_all("stream_unavailable")
            # The responsive peer can retry; the still active native owner
            # for robot-01 must not be invoked a second time.
            assert attempts.count(("robot-01", "stream_unavailable")) == 1
            assert attempts.count(("robot-02", "stream_unavailable")) == 2
            release.set()
            await asyncio.wait_for(watcher._fallback_abort_tasks["robot-01"], 1)
            await watcher._preempt_all("stream_unavailable")
            assert attempts.count(("robot-01", "stream_unavailable")) == 2
        finally:
            release.set()
            await asyncio.gather(
                *watcher._fallback_abort_tasks.values(),
                return_exceptions=True,
            )


@pytest.mark.parametrize("rebase_kind", ["reset", "gap"])
async def test_reset_or_gap_cannot_reuse_old_vad_callback_ack(rebase_kind):
    """Same numerical seq from a new server epoch must run a NEW callback.

    Also forbid a second physical callback while an old cancelled transport
    still executes, even if it ignores CancelledError.
    """
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    deliveries = []
    ordinary_polls = 0
    aborted = []

    def mock(request):
        nonlocal ordinary_polls
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 0, "events": [], "reset": False, "lost": False,
            })
        ordinary_polls += 1
        if ordinary_polls == 2:
            return httpx.Response(200, json={
                "cursor": 0, "events": [],
                "reset": rebase_kind == "reset",
                "lost": rebase_kind == "gap",
            })
        return httpx.Response(200, json={
            "cursor": 1, "reset": False, "lost": False,
            "events": [{
                "seq": 1, "robot_id": "robot-01",
                "kind": "normal", "source": "xiaozhi_aec_vad",
            }],
        })

    async def on_interrupt(robot, kind):
        deliveries.append((robot, kind))
        if len(deliveries) == 1:
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

    async def on_global(reason):
        aborted.append(reason)

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        watcher = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=on_interrupt,
            on_global_interrupt=on_global,
        )
        await watcher.poll()
        try:
            with pytest.raises(TimeoutError, match="Voice interruption incomplete"):
                await watcher.poll()
            assert entered.is_set() and watcher.cursor == 0
            assert await watcher.poll() == 0
            assert aborted == [rebase_kind]
            if rebase_kind == "reset":
                assert watcher.cursor is None
                assert await watcher.poll() == 0
                assert watcher.cursor == 0

            with pytest.raises(TimeoutError, match="Old VAD generation"):
                await watcher.poll()
            assert len(deliveries) == 1
            assert watcher.cursor == 0

            release.set()
            await asyncio.wait_for(watcher._event_task, timeout=1)
            assert await watcher.poll() == 1
            assert deliveries == [
                ("robot-01", "normal"), ("robot-01", "normal"),
            ]
            assert watcher.cursor == 1 and watcher.handled == 1
        finally:
            release.set()
            if watcher._event_task is not None:
                await asyncio.wait_for(watcher._event_task, timeout=1)


@pytest.mark.parametrize("bad_tail", [
    {"seq": 4, "robot_id": "robot-unknown", "kind": "speech_start",
     "source": "xiaozhi_server_vad"},
    {"seq": 5, "robot_id": "robot-01", "kind": "speech_end",
     "source": "xiaozhi_server_vad"},
    {"seq": 4, "robot_id": "robot-01", "kind": "speech_end",
     "source": "manual"},
])
async def test_invalid_later_voice_event_has_no_partial_interrupt_side_effects(bad_tail):
    calls = []

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 2, "events": [], "reset": False, "lost": False,
            })
        return httpx.Response(200, json={
            "cursor": 4, "reset": False, "lost": False,
            "events": [
                {"seq": 3, "robot_id": "robot-01", "kind": "speech_start",
                 "source": "xiaozhi_server_vad"},
                bad_tail,
            ],
        })

    async def interrupt(robot_id, kind):
        calls.append((robot_id, kind))

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=interrupt,
        )
        await listener.poll()
        for _ in range(2):
            with pytest.raises(ValueError, match="Invalid real voice"):
                await listener.poll()
            assert listener.cursor == 2
            assert listener.handled == 0
        assert calls == []


async def test_failed_speech_snapshot_retries_without_replaying_acked_interrupt():
    """A failed snapshot consumer cannot replay an already acknowledged head STOP."""
    calls = []
    snapshots = 0

    def mock(request):
        if request.url.params.get("bootstrap"):
            return httpx.Response(200, json={
                "cursor": 8, "events": [], "reset": False, "lost": False,
                "active_human_robots": [],
            })
        return httpx.Response(200, json={
            "cursor": 9, "reset": False, "lost": False,
            "events": [{"seq": 9, "robot_id": "robot-01",
                        "kind": "speech_start", "source": "xiaozhi_server_vad"}]
            if request.url.params["after"] == "8" else [],
            "active_human_robots": ["robot-01"],
        })

    async def interrupt(robot, kind):
        calls.append((robot, kind))

    async def snapshot(active):
        nonlocal snapshots
        snapshots += 1
        if snapshots == 2:
            raise OSError("snapshot consumer temporarily offline")
        if snapshots == 1:
            assert active == frozenset()
        else:
            assert active == frozenset({"robot-01"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=interrupt,
            on_speech_snapshot=snapshot, require_snapshot=True,
        )
        await listener.poll()
        with pytest.raises(OSError, match="snapshot consumer"):
            await listener.poll()
        assert listener.cursor == 9 and listener.handled == 1
        assert calls == [("robot-01", "speech_start")]
        assert await listener.poll() == 0
        assert snapshots == 3
        assert calls == [("robot-01", "speech_start")]


async def test_cancelled_shared_audio_abort_does_not_cancel_voice_monitor():
    """A child STOP cancellation is not an instruction to kill VAD polling."""
    import asyncio

    async def cancelled_abort(reason):
        raise asyncio.CancelledError()

    async def unexpected_single(robot, reason):
        raise AssertionError("Unexpected per pet abort")

    async with httpx.AsyncClient() as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=unexpected_single,
            on_global_interrupt=cancelled_abort,
        )
        with pytest.raises(TimeoutError, match="cancelled without ACK"):
            await listener._preempt_all("stream_unavailable")
        assert listener._global_abort_task is not None
        assert listener._global_abort_task.cancelled()
        # A new attempt remains available; a cancelled child is not a
        # successful shared decoder STOP or permanent monitor shutdown.
        with pytest.raises(TimeoutError, match="cancelled without ACK"):
            await listener._preempt_all("stream_unavailable")


async def test_cancelled_per_pet_audio_abort_raises_timeout_error():
    """A cancelled child per-pet abort callback is not a confirmed decoder flush."""
    import asyncio

    async def cancelled_abort(robot_id, reason):
        raise asyncio.CancelledError()

    async with httpx.AsyncClient() as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01", "robot-02"}, on_interrupt=cancelled_abort,
        )
        with pytest.raises(TimeoutError, match="Fleet interruption cancelled without ACK"):
            await listener._preempt_all("stream_unavailable")


async def test_real_runtime_bootstrap_never_accepts_unacknowledged_speaker_stop():
    """A repeated active VAD snapshot must retry an unconfirmed STOP."""
    import time
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub
    from desk_robot.runtime import Runtime

    requests = []
    stops = []
    frames = []
    allowed = False
    hub = CameraFrameHub(["robot-01"])

    def mock(request):
        requests.append(dict(request.url.params))
        if request.url.params.get("bootstrap") != "1":
            raise AssertionError("Cannot accept events until human STOP is acknowledged")
        return httpx.Response(200, json={
            "cursor": 19, "events": [], "reset": False, "lost": False,
            "active_human_robots": ["robot-01"],
        })

    class Pet:
        voice_monitor_ready = False

        async def interrupt(self, robot_id):
            stops.append(robot_id)
            if not allowed:
                raise RuntimeError("head STOP unacknowledged")

        def set_voice_monitor_ready(self, value):
            self.voice_monitor_ready = value

    class Conversation:
        async def stop(self):
            return None

    class Visual:
        def __init__(self):
            self.hub = hub

        def prepare_human_turn(self, robot_id, *, end_expected):
            frames.append(("prepare", robot_id))
            hub.notify(robot_id, "human_voice", time.monotonic())

        def start_speech_frames(self, robot_id):
            frames.append(("start", robot_id))

        def voice_ended(self, robot_id):
            raise AssertionError("Active human speech must never be ended")

    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])
    runtime.pet = Pet()
    runtime.conversation = Conversation()
    runtime.multimodal = Visual()

    async def no_events(_robot_id, _reason):
        raise AssertionError("No ordered voice events before bootstrap")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        listener = VoiceEventListener(
            client, url="http://127.0.0.1:8766", token="s" * 32,
            robot_ids={"robot-01"}, on_interrupt=no_events,
            on_speech_snapshot=runtime._on_voice_snapshot,
            on_monitor_ready=runtime._on_voice_monitor_ready,
            require_snapshot=True,
        )
        for count in (1, 2):
            with pytest.raises(RuntimeError, match="Unable to preempt"):
                await listener.poll()
            assert stops == ["robot-01"] * count
            assert listener.cursor is None
            assert not listener.monitor_ready
            assert not runtime.pet.voice_monitor_ready
            assert hub.voice_until["robot-01"] == float("inf")
        allowed = True
        assert await listener.poll() == 0
        assert stops == ["robot-01"] * 3
        assert listener.cursor == 19
        assert listener.monitor_ready and runtime.pet.voice_monitor_ready
        assert runtime._voice_stop_unconfirmed is False
        assert frames == [("prepare", "robot-01"), ("start", "robot-01")]
        assert all(request["bootstrap"] == "1" for request in requests)
