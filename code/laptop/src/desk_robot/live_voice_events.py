"""Deliver real Xiaozhi server AEC/VAD barge events to Mac speech owners.

This uses the authenticated loopback server's real websocket observation path.
No microphone samples, camera images, commands, or motor permits pass here.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx


class VoiceEventListener:
    def __init__(
        self, client: httpx.AsyncClient, *, url: str, token: str,
        robot_ids: set[str], on_interrupt: Callable[[str, str], Awaitable[None]],
        on_global_interrupt: Callable[[str], Awaitable[None]] | None = None,
        on_monitor_ready: Callable[[bool], Awaitable[None]] | None = None,
        on_speech_snapshot: Callable[[frozenset[str]], Awaitable[None]] | None = None,
        require_snapshot: bool = False,
    ):
        if not robot_ids or len(token) < 24 or type(require_snapshot) is not bool:
            raise ValueError("Known robot IDs and private speech token required")
        self.client, self.url, self.token = client, url.rstrip("/"), token
        self.robot_ids = frozenset(robot_ids)
        self.on_interrupt = on_interrupt
        self.on_global_interrupt = on_global_interrupt
        self.on_monitor_ready = on_monitor_ready
        self.on_speech_snapshot = on_speech_snapshot
        self.require_snapshot = require_snapshot
        self.monitor_ready = False
        # Retry failed health notifications even if local state already fell
        # silent; a failed callback must not permanently retain ready=True.
        self._monitor_delivered: bool | None = None
        self.cursor: int | None = None
        self.handled = 0
        self.last_error: str | None = None
        self._stream_failed = False

    async def _set_monitor_ready(self, ready: bool) -> None:
        if self.monitor_ready == ready and self._monitor_delivered == ready:
            return
        # Record failure before notifying the Mac. Only record delivery after
        # the dependent pet owner accepts it; retry failed FALSE notifications.
        self.monitor_ready = ready
        if self.on_monitor_ready is not None:
            await self.on_monitor_ready(ready)
        self._monitor_delivered = ready

    async def _preempt_all(self, reason: str) -> None:
        # Loss of the voice event stream means a human interruption could have
        # been missed. Silencing all Mac-owned audio is safer than guessing.
        # The Mac runtime owns a single shared speech floor. Abort it ONCE,
        # rather than executing the same five-pet cancellation five times.
        if self.on_global_interrupt is not None:
            await self.on_global_interrupt(reason)
            return
        # Existing independent consumers preserve their per-device callback.
        # Launch every independent fallback at once. Serial awaits would
        # delay other pets behind one unavailable or cancellation-resistant
        # head. The production single shared audio owner remains preferred.
        tasks = [
            asyncio.create_task(self.on_interrupt(robot_id, reason))
            for robot_id in sorted(self.robot_ids)
        ]
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
        if errors:
            raise errors[0]

    async def _fetch(self, bootstrap: bool = False) -> dict:
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
        return data

    async def _reconcile_snapshot(self, data: dict) -> None:
        # Supported by our pinned bridge; legacy fixtures without this field
        # retain the event-only behavior but cannot certify gap recovery.
        if self.on_speech_snapshot is not None and "active_human_robots" in data:
            await self.on_speech_snapshot(frozenset(data["active_human_robots"]))

    async def poll(self) -> int:
        if self.cursor is None:
            data = await self._fetch(bootstrap=True)
            if data["events"]:
                raise ValueError("Bootstrapping must not replay stale audio events")
            self.cursor = data["cursor"]
            self._stream_failed = False
            await self._reconcile_snapshot(data)
            await self._set_monitor_ready(True)
            return 0
        data = await self._fetch()
        if data["reset"]:
            await self._set_monitor_ready(False)
            # Server restart invalidates the old speech generation. No stale
            # events replay, but old Mac audio must not survive a lost VAD.
            await self._preempt_all("reset")
            self.cursor = None
            self._stream_failed = False
            return 0
        if data["cursor"] < self.cursor:
            raise ValueError("Voice event cursor rolled backward without a restart")
        if data["lost"]:
            await self._set_monitor_ready(False)
            # Any missed interruption could have left obsolete Mac TTS running.
            await self._preempt_all("gap")
            await self._reconcile_snapshot(data)
            self.cursor = data["cursor"]
            self._stream_failed = False
            return 0
        current = self.cursor
        for event in data["events"]:
            if (not isinstance(event, dict)
                    or type(event.get("seq")) is not int
                    or event["seq"] != current + 1
                    or event["seq"] > data["cursor"]
                    or type(event.get("robot_id")) is not str
                    or event["robot_id"] not in self.robot_ids
                    or event.get("kind") not in (
                        "normal", "group", "speech_start", "speech_end"
                    )
                    or event.get("source") != (
                        "xiaozhi_server_vad"
                        if event.get("kind") in ("speech_start", "speech_end")
                        else "xiaozhi_aec_vad"
                    )):
                raise ValueError("Invalid real voice source, identity or sequence")
            await self.on_interrupt(event["robot_id"], event["kind"])
            current = event["seq"]
            # Commit only after successful cancellation; failed callbacks replay.
            self.cursor = current
            self.handled += 1
        if self.cursor != data["cursor"]:
            raise ValueError("Voice server skipped sequence without marking a gap")
        self.last_error = None
        self._stream_failed = False
        await self._reconcile_snapshot(data)
        await self._set_monitor_ready(True)
        return len(data["events"])

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Callback, parser and transport exceptions are equally
                # unsafe: the realtime human speech monitor cannot stay ready.
                self.last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
                try:
                    await self._set_monitor_ready(False)
                except Exception as health_exc:
                    self.last_error += (
                        f"; monitor callback failed: {type(health_exc).__name__}"
                    )
                # A failed abort must be retried on the next outage tick;
                # do not mark it delivered before the real owner accepts it.
                if not self._stream_failed:
                    try:
                        await self._preempt_all("stream_unavailable")
                        self._stream_failed = True
                    except Exception as cancel_exc:
                        self.last_error += f"; preempt failed: {type(cancel_exc).__name__}"
                await asyncio.sleep(1)
