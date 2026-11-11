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
    ):
        if not robot_ids or len(token) < 24:
            raise ValueError("Known robot IDs and private speech token required")
        self.client, self.url, self.token = client, url.rstrip("/"), token
        self.robot_ids = frozenset(robot_ids)
        self.on_interrupt = on_interrupt
        self.on_global_interrupt = on_global_interrupt
        self.on_monitor_ready = on_monitor_ready
        self.on_speech_snapshot = on_speech_snapshot
        self.monitor_ready = False
        self.cursor: int | None = None
        self.handled = 0
        self.last_error: str | None = None
        self._stream_failed = False

    async def _set_monitor_ready(self, ready: bool) -> None:
        if self.monitor_ready == ready:
            return
        # Record failure before notifying the Mac. A callback cannot make
        # a lost monitor falsely healthy.
        self.monitor_ready = ready
        if self.on_monitor_ready is not None:
            await self.on_monitor_ready(ready)

    async def _preempt_all(self, reason: str) -> None:
        # Loss of the voice event stream means a human interruption could have
        # been missed. Silencing all Mac-owned audio is safer than guessing.
        # The Mac runtime owns a single shared speech floor. Abort it ONCE,
        # rather than executing the same five-pet cancellation five times.
        if self.on_global_interrupt is not None:
            await self.on_global_interrupt(reason)
            return
        # Existing independent consumers preserve their per-device callback.
        for robot_id in sorted(self.robot_ids):
            await self.on_interrupt(robot_id, reason)

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
                    or event.get("robot_id") not in self.robot_ids
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
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
                self.last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
                await self._set_monitor_ready(False)
                # A broken, delayed or malformed event stream is NOT proof
                # that the user is silent. Cancel audio once per outage;
                # a successful authenticated poll rearms event monitoring.
                if not self._stream_failed:
                    self._stream_failed = True
                    try:
                        await self._preempt_all("stream_unavailable")
                    except Exception as cancel_exc:
                        self.last_error += f"; preempt failed: {type(cancel_exc).__name__}"
                await asyncio.sleep(1)
