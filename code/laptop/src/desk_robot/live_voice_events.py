"""Deliver real Xiaozhi server AEC/VAD barge events to Mac speech owners.

This uses the authenticated loopback server's real websocket observation path.
No microphone samples, camera images, commands, or motor permits pass here.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx


def _defer_end_for_active_peer(
    event: dict[str, Any], events: list[dict[str, Any]], active: list[str],
) -> bool:
    """Leave the old lease in place until a newer active peer start is handled."""
    return (
        event["kind"] == "speech_end"
        and type(event.get("voice_turn_generation")) is int
        and any(
            later["seq"] > event["seq"]
            and later["kind"] == "speech_start"
            and later["robot_id"] != event["robot_id"]
            and later["robot_id"] in active
            for later in events
        )
    )


class VoiceEventListener:
    def __init__(
        self, client: httpx.AsyncClient, *, url: str, token: str,
        robot_ids: set[str], on_interrupt: Callable[[str, str], Awaitable[None]],
        on_global_interrupt: Callable[[str], Awaitable[None]] | None = None,
        on_monitor_ready: Callable[[bool], Awaitable[None]] | None = None,
        on_speech_snapshot: Callable[[frozenset[str]], Awaitable[None]] | None = None,
        require_snapshot: bool = False,
        on_voice_generations: Callable[[dict[str, int] | None], None] | None = None,
        require_turn_generations: bool = False,
    ) -> None:
        if (not robot_ids or len(token) < 24 or type(require_snapshot) is not bool
                or type(require_turn_generations) is not bool):
            raise ValueError("Known robot IDs and private speech token required")
        self.client, self.url, self.token = client, url.rstrip("/"), token
        self.robot_ids = frozenset(robot_ids)
        self.on_interrupt = on_interrupt
        self.on_global_interrupt = on_global_interrupt
        self.on_monitor_ready = on_monitor_ready
        self.on_speech_snapshot = on_speech_snapshot
        self.require_snapshot = require_snapshot
        self.on_voice_generations = on_voice_generations
        self.require_turn_generations = require_turn_generations
        self.monitor_ready = False
        # Retry failed health notifications even if local state already fell
        # silent; a failed callback must not permanently retain ready=True.
        self._monitor_delivered: bool | None = None
        self.cursor: int | None = None
        self.handled = 0
        self.last_error: str | None = None
        self._stream_failed = False
        self._stream_abort_pending = False
        # A callback can suppress CancelledError; keep its real task as the
        # ownership token until it finishes instead of launching duplicates.
        self._global_abort_task: asyncio.Task[None] | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._event_sequence: int | None = None
        # Sequence numbers may be reused after an authenticated bridge reset.
        # A completed callback from an old server generation must never be
        # mistaken for a physical interruption ACK in the new generation.
        self._event_generation = 0
        self._event_task_generation: int | None = None
        self._fallback_abort_tasks: dict[str, asyncio.Task[None]] = {}

    async def _set_monitor_ready(self, ready: bool) -> None:
        if self.monitor_ready == ready and self._monitor_delivered == ready:
            return
        # Silence immediately, but do not expose a healthy monitor until
        # the dependent pet owner acknowledges the transition. A callback
        # may change the remote state before raising, so its prior delivery
        # receipt is no longer reliable and FALSE must be sent again.
        self.monitor_ready = False
        self._monitor_delivered = None
        if self.on_monitor_ready is not None:
            await self.on_monitor_ready(ready)
        self._monitor_delivered = ready
        self.monitor_ready = ready

    async def _preempt_all(self, reason: str) -> None:
        # Loss of the voice event stream means a human interruption could have
        # been missed. Silencing all Mac-owned audio is safer than guessing.
        # The Mac runtime owns a single shared speech floor. Abort it ONCE,
        # rather than executing the same five-pet cancellation five times.
        if self.on_global_interrupt is not None:
            # A coroutine that suppresses cancellation can still be flushing
            # a physical audio owner after the listener times out. Keep one
            # shared operation in flight and never launch a second competing
            # abort until the previous task has actually exited.
            task = self._global_abort_task
            if task is None or task.done():
                task = asyncio.create_task(self.on_global_interrupt(reason))
                self._global_abort_task = task

                def observe_result(completed: asyncio.Task[None]) -> None:
                    if not completed.cancelled():
                        completed.exception()  # consume a late callback failure

                task.add_done_callback(observe_result)
            try:
                done, pending = await asyncio.wait({task}, timeout=0.5)
                if pending:
                    raise TimeoutError("Shared fleet interruption incomplete")
                if task.cancelled():
                    # Cancellation of a child speaker callback is not a
                    # confirmed decoder flush and must not terminate the
                    # independent VAD monitor task as if it was cancelled.
                    raise TimeoutError("Shared fleet interruption cancelled without ACK")
                task.result()
            finally:
                if not task.done():
                    task.cancel()  # request cancellation, not physical ACK
            return
        # Existing independent consumers preserve their per-device callback.
        # Launch every independent fallback at once. Serial awaits would
        # delay other pets behind one unavailable or cancellation-resistant
        # head. The production single shared audio owner remains preferred.
        tasks = []
        for robot_id in sorted(self.robot_ids):
            task = self._fallback_abort_tasks.get(robot_id)
            if task is None or task.done():
                task = asyncio.create_task(self.on_interrupt(robot_id, reason))
                self._fallback_abort_tasks[robot_id] = task

                def observe_fallback(completed: asyncio.Task[None]) -> None:
                    if not completed.cancelled():
                        completed.exception()

                task.add_done_callback(observe_fallback)
            tasks.append(task)
        try:
            done, pending = await asyncio.wait(tasks, timeout=0.5)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
        errors = [task.exception() for task in tasks
                  if task in done and not task.cancelled()
                  and task.exception() is not None]
        if pending:
            # Child tasks are cancelled but never presumed physically flushed.
            raise TimeoutError("Fleet interruption incomplete; head unresponsive")
        if any(task in done and task.cancelled() for task in tasks):
            raise TimeoutError("Fleet interruption cancelled without ACK")
        if errors:
            raise errors[0]

    async def _fetch(self, bootstrap: bool = False) -> dict[str, Any]:
        query = {"after": str(self.cursor if self.cursor is not None else 0)}
        if bootstrap:
            query["bootstrap"] = "1"
        response = await self.client.get(
            self.url + "/events", params=query,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=2.0,
        )
        response.raise_for_status()
        data = response.json()
        if (not isinstance(data, dict) or type(data.get("cursor")) is not int
                or not 0 <= data["cursor"] <= 0x7fffffffffffffff
                or type(data.get("reset")) is not bool
                or type(data.get("lost")) is not bool
                or not isinstance(data.get("events"), list)
                or len(data["events"]) > 128):
            raise ValueError("Malformed or oversized voice event stream")
        active = data.get("active_human_robots")
        if self.require_snapshot and active is None:
            # A legacy event-only bridge cannot recover VAD edges missed
            # during reconnect; never treat its empty replay as silence.
            raise ValueError("Live human VAD snapshot required for hardware speech")
        if active is not None and (
            not isinstance(active, list)
            or len(active) > len(self.robot_ids)
            or any(type(robot_id) is not str or robot_id not in self.robot_ids
                   for robot_id in active)
            or len(set(active)) != len(active)
        ):
            raise ValueError("Invalid authenticated live VAD snapshot")
        generations = data.get("voice_turn_generations")
        if self.require_turn_generations and generations is None:
            raise ValueError("Authenticated Xiaozhi turn generations required")
        if generations is not None and (
            not isinstance(generations, dict)
            or len(generations) > len(self.robot_ids)
            or any(
                type(robot_id) is not str or robot_id not in self.robot_ids
                or type(generation) is not int
                or not 0 <= generation <= 0x7fffffffffffffff
                for robot_id, generation in generations.items()
            )
        ):
            raise ValueError("Invalid authenticated voice turn generation snapshot")
        if generations is not None and active is not None and (
            not set(active).issubset(generations)
        ):
            raise ValueError("Active human VAD lacks source turn generation")
        return data

    def _publish_generations(self, data: dict[str, Any] | None) -> None:
        """Atomically fence signed tools before awaiting slow audio callbacks."""
        if self.on_voice_generations is not None:
            self.on_voice_generations(
                None if data is None else data.get("voice_turn_generations")
            )

    async def _reconcile_snapshot(self, data: dict[str, Any]) -> None:
        # Supported by our pinned bridge; legacy fixtures without this field
        # retain the event-only behavior but cannot certify gap recovery.
        if self.on_speech_snapshot is not None and "active_human_robots" in data:
            await self.on_speech_snapshot(frozenset(data["active_human_robots"]))

    async def _abort_unavailable(self) -> None:
        # A recovered HTTP stream does not acknowledge the global audio
        # abort. Retain the obligation through failure or cancellation.
        self._stream_abort_pending = True
        await self._preempt_all("stream_unavailable")
        self._stream_abort_pending = False
        self._stream_failed = True

    def _validate_event_owner(self, events: list[dict[str, Any]]) -> None:
        task = self._event_task
        if task is None:
            return
        # An authenticated reset or gap rebases sequence identity. An old
        # callback must actually exit before even an empty bootstrap or
        # replay can restore readiness; its result is not a new epoch ACK.
        if self._event_task_generation != self._event_generation:
            if not task.done():
                self.monitor_ready = False
                task.cancel()
                raise TimeoutError("Old VAD generation interruption still in flight")
            self._event_task = None
            self._event_sequence = None
            self._event_task_generation = None
        elif not events or self._event_sequence != events[0]["seq"]:
            # The already validated sequence still needs its actual replay
            # before its owned callback can be accepted as a receipt.
            self.monitor_ready = False
            raise TimeoutError("Previous voice interruption still unresolved")

    async def poll(self) -> int:
        if self._stream_abort_pending:
            # Finish the previous outage's shared audio interruption before
            # consuming any new events or advertising monitor recovery.
            await self._abort_unavailable()
        if self.cursor is None:
            data = await self._fetch(bootstrap=True)
            if data["events"]:
                raise ValueError("Bootstrapping must not replay stale audio events")
            self._validate_event_owner(data["events"])
            # Commit bootstrap only after both downstream consumers accept it.
            # Otherwise a failed snapshot/health callback must retry bootstrap,
            # not consume later events with an uninitialized speech owner.
            self._publish_generations(data)
            await self._reconcile_snapshot(data)
            await self._set_monitor_ready(True)
            self.cursor = data["cursor"]
            self._stream_failed = False
            self.last_error = None
            return 0
        data = await self._fetch()
        if data["reset"]:
            self._publish_generations(None)
            self._event_generation += 1
            # Safety first: a slow/failing monitoring callback must not delay
            # stopping obsolete speech after the authenticated bridge resets.
            self.monitor_ready = False
            await self._preempt_all("reset")
            await self._set_monitor_ready(False)
            # Server restart invalidates the old speech generation.
            self.cursor = None
            self._stream_failed = False
            return 0
        if data["cursor"] < self.cursor:
            raise ValueError("Voice event cursor rolled backward without a restart")
        if data["lost"]:
            self._publish_generations(None)
            self._event_generation += 1
            # The audio abort is time critical even when UI/health callbacks
            # are blocked or unavailable. Fail monitor ready immediately.
            self.monitor_ready = False
            await self._preempt_all("gap")
            await self._set_monitor_ready(False)
            self._publish_generations(data)
            await self._reconcile_snapshot(data)
            self.cursor = data["cursor"]
            self._stream_failed = False
            return 0
        # Validate the entire authenticated batch before invoking any physical
        # interruption callback. A malformed later event must not cause an
        # earlier event to execute and then replay on the next poll.
        expected = self.cursor
        for event in data["events"]:
            if (not isinstance(event, dict)
                    or type(event.get("seq")) is not int
                    or event["seq"] != expected + 1
                    or event["seq"] > data["cursor"]
                    or type(event.get("robot_id")) is not str
                    or event["robot_id"] not in self.robot_ids
                    or event.get("kind") not in (
                        "normal", "group", "speech_start", "speech_end"
                    )
                    or (self.require_turn_generations and type(
                        event.get("voice_turn_generation")) is not int)
                    or ("voice_turn_generation" in event and (
                        type(event["voice_turn_generation"]) is not int
                        or not 0 <= event["voice_turn_generation"] <= 0x7fffffffffffffff
                    ))
                    or event.get("source") != (
                        "xiaozhi_server_vad"
                        if event.get("kind") in ("speech_start", "speech_end")
                        else "xiaozhi_aec_vad"
                    )):
                raise ValueError("Invalid real voice source, identity or sequence")
            generations = data.get("voice_turn_generations")
            if (generations is not None and event["robot_id"] in generations
                    and "voice_turn_generation" in event
                    and event["voice_turn_generation"] > generations[event["robot_id"]]):
                raise ValueError("Event generation exceeds authenticated current turn")
            expected = event["seq"]
        if expected != data["cursor"]:
            raise ValueError("Voice server skipped sequence without marking a gap")
        self._validate_event_owner(data["events"])
        # Publish newest authenticated head source generations before a slow
        # decoder STOP for any earlier event in this batch.
        self._publish_generations(data)
        current = self.cursor
        for event in data["events"]:
            # A head may hang after receiving its interrupt command. Keep
            # the exact sequence's task alive across transport retries and
            # refuse a duplicate callback while the first is still running.
            seq = event["seq"]
            task = self._event_task
            # A queued speech_end from an older Xiaozhi human turn must
            # not briefly release the currently active human speech floor.
            # The authenticated latest snapshot is authoritative here.
            # Only skip an end that has never entered the callback owner;
            # an in-flight callback must still finish or fail its own ACK.
            active = data.get("active_human_robots")
            generations = data.get("voice_turn_generations")
            if (
                task is None
                and event["kind"] == "speech_end"
                and isinstance(active, list)
                and isinstance(generations, dict)
                and event["robot_id"] in active
                and type(event.get("voice_turn_generation")) is int
                and event["voice_turn_generation"]
                    < generations.get(event["robot_id"], -1)
            ):
                self.cursor = seq
                self.handled += 1
                continue
            # Another head may already be speaking in this same authenticated
            # batch. Reconcile the old end from the snapshot after the start,
            # rather than briefly dispatching work into the occupied floor.
            if (
                task is None
                and self.on_speech_snapshot is not None
                and isinstance(active, list)
                and _defer_end_for_active_peer(event, data["events"], active)
            ):
                self.cursor = seq
                self.handled += 1
                continue
            if task is None:
                task = asyncio.create_task(
                    self.on_interrupt(event["robot_id"], event["kind"])
                )
                self._event_task = task
                self._event_sequence = seq
                self._event_task_generation = self._event_generation

                def observe_event_result(completed: asyncio.Task[None]) -> None:
                    if not completed.cancelled():
                        completed.exception()

                task.add_done_callback(observe_event_result)
            elif self._event_sequence != seq:
                raise TimeoutError("Previous voice interruption still unresolved")
            try:
                done, pending = await asyncio.wait({task}, timeout=0.5)
                if pending:
                    raise TimeoutError("Voice interruption incomplete; no ACK")
                if task.cancelled():
                    raise TimeoutError("Voice interruption cancelled without ACK")
                task.result()
            finally:
                if task.done():
                    self._event_task = None
                    self._event_sequence = None
                    self._event_task_generation = None
                else:
                    task.cancel()  # best effort; an uncooperative task stays owned
            current = seq
            # Commit only after successful cancellation; failed callbacks replay.
            self.cursor = current
            self.handled += 1
        if self.cursor != data["cursor"]:
            raise ValueError("Voice server skipped sequence without marking a gap")
        self._stream_failed = False
        await self._reconcile_snapshot(data)
        await self._set_monitor_ready(True)
        self.last_error = None
        return len(data["events"])

    async def _shutdown_callbacks(self) -> None:
        # A cancellation request is not task termination. Keep the monitor
        # owner alive until every callback has actually stopped; Runtime's
        # bounded shutdown wait can then report an unconfirmed teardown.
        self.monitor_ready = False
        tasks = {
            task for task in (
                self._event_task, self._global_abort_task,
                *self._fallback_abort_tasks.values(),
            ) if task is not None
        }
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        try:
            try:
                self._publish_generations(None)
            finally:
                await self._set_monitor_ready(False)
        finally:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._event_task = None
            self._event_sequence = None
            self._event_task_generation = None
            self._global_abort_task = None
            self._fallback_abort_tasks.clear()

    async def run(self) -> None:
        try:
            await self._run()
        finally:
            await self._shutdown_callbacks()

    async def _run(self) -> None:
        while True:
            retrying_abort = self._stream_abort_pending
            try:
                await self.poll()
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Callback, parser and transport exceptions are equally
                # unsafe: the realtime human speech monitor cannot stay ready.
                self.last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
                # Stop obsolete audio first. Monitor callbacks may themselves
                # block during a head disconnect, and must never gate the
                # emergency shared audio interruption attempt.
                self.monitor_ready = False
                try:
                    self._publish_generations(None)
                except Exception:
                    self.last_error += "; voice generation invalidation failed"
                # A failed abort must be retried on the next outage tick;
                # do not mark it delivered before the real owner accepts it.
                if retrying_abort and self._stream_abort_pending:
                    # poll() already attempted the outstanding abort.
                    # Do not launch a second attempt in the same tick.
                    self.last_error += f"; preempt failed: {type(exc).__name__}"
                elif not self._stream_failed:
                    try:
                        await self._abort_unavailable()
                    except Exception as cancel_exc:
                        self.last_error += f"; preempt failed: {type(cancel_exc).__name__}"
                try:
                    await self._set_monitor_ready(False)
                except Exception as health_exc:
                    self.last_error += (
                        f"; monitor callback failed: {type(health_exc).__name__}"
                    )
                await asyncio.sleep(1)
