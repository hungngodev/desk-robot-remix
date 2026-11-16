from __future__ import annotations

import asyncio
import time

import httpx

from .config import Settings, secret
from .controller import Coordinator
from .conversation import Conversation, KokoroHeadSpeaker, OllamaChat
from .live_voice_events import VoiceEventListener
from .memory import MemoryStore
from .multimodal import MultimodalOrchestrator
from .pet import PetController
from .room_station import RoomObservation, RoomSerialFeed
from .simulator import (
    SimulatedChat,
    SimulatedHead,
    SimulatedScene,
    SimulatedSpeaker,
    SimulationVision,
)
from .transport import HttpHead
from .vision import OllamaScene, YoloWorldVision


_MONITOR_STOP_TIMEOUT_S = 0.35
_RUNTIME_VOICE_STOP_TIMEOUT_S = 2.5


async def _bounded_monitor_stop(coro) -> None:
    """One stalled decoder cannot block the five-head monitor outage abort."""
    task = asyncio.create_task(coro)
    try:
        done, _ = await asyncio.wait({task}, timeout=_MONITOR_STOP_TIMEOUT_S)
        if not done:
            raise TimeoutError("Physical XIAO STOP unconfirmed on monitor loss")
        await task
    finally:
        if not task.done():
            task.cancel()
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient()
        if settings.mode == "simulation":
            heads = {r.id: SimulatedHead(r.id) for r in settings.robots}
            vision, chat, speaker = SimulationVision(), SimulatedChat(), SimulatedSpeaker()
            scene = SimulatedScene()
        else:
            heads = {r.id: HttpHead(r, self.client, strict_capture=True) for r in settings.robots}
            vision = YoloWorldVision(settings.vision_weights)
            chat = OllamaChat(settings, self.client)
            speaker = KokoroHeadSpeaker(settings, self.client)
            scene = OllamaScene(self.client, url=settings.ollama_url, model=settings.vision_model)
        self.memory = MemoryStore(settings.memory_dir, [r.id for r in settings.robots])
        self.coordinator = Coordinator(settings, heads, vision)
        self.conversation = Conversation(settings, chat, speaker, memory=self.memory)
        self.pet = PetController(
            settings, heads, self.conversation, self.memory, scene,
            on_local_fault=self.coordinator.stop,
        )
        self.multimodal: MultimodalOrchestrator | None = None
        if settings.mode == "hardware":
            # One lock serves background visual comparison and user question
            # inference across ALL five pets; no second camera transport.
            self.multimodal = MultimodalOrchestrator(
                settings, heads, scene, self.pet._vision_lock
            )
            self.pet.multimodal = self.multimodal
            self.conversation.multimodal = self.multimodal
            self.multimodal.preempt_background_vision = (
                self.pet.preempt_background_vision
            )
            # A human's look is higher priority for its ENTIRE camera +
            # inference lifetime, not just the instant preemption is sent.
            self.multimodal.begin_direct_vision = self.pet.begin_direct_vision
            self.multimodal.end_direct_vision = self.pet.end_direct_vision
        self.voice_events: VoiceEventListener | None = None
        self._voice_task: asyncio.Task | None = None
        self._room_stop = asyncio.Event()
        self._room_task: asyncio.Task | None = None
        self.room_feed: RoomSerialFeed | None = None
        self._closed = False

    def _on_room_observation(self, observation: RoomObservation) -> None:
        """One Mac owner shares only opt-in, ephemeral environmental facts."""
        if (not self._closed and self.settings.room_station_context_enabled
                and self.multimodal is not None):
            self.multimodal.hub.remember_room(observation)

    async def start(self):
        """Bridge Xiaozhi's real voice interruption into Mac speech cancellation."""
        if getattr(self, "_closed", False):
            raise RuntimeError("Closed runtime cannot restart voice listeners")
        if self.settings.mode != "hardware" or self._voice_task is not None:
            return
        # Visual consent enables a persistent feed independently of voice
        # activity or pet autostart. One Mac stream consumer per real head.
        # The pet still needs its separate opt-in to speak proactively.
        if self.multimodal is not None:
            self.multimodal.start_streams()
        if self.settings.room_station_enabled and self._room_task is None:
            try:
                import serial  # noqa: F401, room extra only
            except ImportError as exc:
                raise RuntimeError(
                    "Room station requires pip install '.[room]' for pyserial"
                ) from exc
            loop = asyncio.get_running_loop()
            self.room_feed = RoomSerialFeed(
                self.settings.room_station_port,
                lambda observation: loop.call_soon_threadsafe(
                    self._on_room_observation, observation
                ),
            )
            self._room_task = asyncio.create_task(
                self.room_feed.run(self._room_stop),
            )
        if not any(robot.device_id for robot in self.settings.robots):
            return
        self.voice_events = VoiceEventListener(
            self.client, url=self.settings.speech_bridge_url,
            token=secret(self.settings.speech_bridge_token_env),
            robot_ids={robot.id for robot in self.settings.robots},
            on_interrupt=self._on_voice_interrupt,
            on_global_interrupt=self._on_voice_global,
            on_monitor_ready=self._on_voice_monitor_ready,
            on_speech_snapshot=self._on_voice_snapshot,
            require_snapshot=True,
        )
        self._voice_task = asyncio.create_task(self.voice_events.run())
        if self.settings.pet_autostart_enabled:
            # Boot into autonomous observation only after explicit local
            # operator consent. Current voice monitor is NOT ready yet, so
            # any camera/sensor events remain silent until Xiaozhi's live
            # authenticated VAD snapshot has been established.
            for robot in self.settings.robots:
                if robot.device_id:
                    self.pet.start(robot.id)

    async def _preempt_audio_floor(self) -> None:
        """Human and VAD transport failures share one five-pet audio owner."""
        # Independent five-pet and coordinated social audio owners must be
        # cancelled concurrently. Waiting for a slow pet's Xiaozhi session
        # teardown BEFORE stopping a separate group speaker delays human VAD
        # interruption, especially during a failed network call.
        results = await asyncio.gather(
            *(self.pet.interrupt(robot.id) for robot in self.settings.robots),
            self.conversation.stop(),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError("Unable to preempt one or more pet speakers") from failures[0]

    async def _on_voice_snapshot(self, active: frozenset[str]) -> None:
        if getattr(self, "_closed", False):
            return
        visual = getattr(self, "multimodal", None)
        if visual is None:
            return
        now = time.monotonic()
        # A start may be missing from the replay ring after reconnect.
        # Active VAD from the authenticated server is enough to stop any
        # currently playing unsolicited or group speech before reconciliation.
        missing_starts = [
            robot_id for robot_id in active
            # A finite seven-second AEC barge hold is NOT an explicit VAD
            # start. An authenticated active snapshot must upgrade it to
            # a real turn, preempt old camera work and start speech frames.
            if visual.hub.voice_until[robot_id] != float("inf")
        ]
        # A reconnect snapshot can contain speech edges missed by the
        # ordered event stream. Merely setting hub.voice_until did not cancel
        # other pets' optional JPEGs or prime the speaking head's camera.
        # Reuse the exact live VAD owner after the urgent audio abort.
        missing_ends = [
            robot_id for robot_id in visual.hub.robots
            if robot_id not in active
            and visual.hub.voice_until[robot_id] == float("inf")
        ]
        preempt_error = None
        if missing_starts:
            prepare = getattr(visual, "prepare_human_turn", None)
            # Mark authenticated VAD NOW. A slow Xiaozhi STOP cannot keep
            # old camera or VLM activity alive during speaker teardown.
            if callable(prepare):
                for robot_id in sorted(missing_starts):
                    prepare(robot_id, end_expected=True)
            try:
                await self._preempt_audio_floor()
            except Exception as exc:
                # An unresolved physical STOP must remain an error, but it
                # cannot erase the authenticated human's live camera turn.
                preempt_error = exc
            if getattr(self, "_closed", False):
                return
            for robot_id in sorted(missing_starts):
                if callable(prepare):
                    visual.start_speech_frames(robot_id)
                else:
                    visual.voice_started(robot_id)
        # A lost speech_end must stop that head's optional 1 FPS sampler,
        # not just clear the speaker lease in the hub.
        for robot_id in sorted(missing_ends):
            visual.voice_ended(robot_id)
        visual.hub.reconcile_speech_snapshot(active, time.monotonic())
        # A transport outage cancels optional camera workers without
        # pretending a still-active human stopped speaking. Resume their
        # sampler ONLY after the authenticated monitor is healthy again.
        recovering = getattr(visual, "_reconnect_needs_sampler", None)
        if recovering and getattr(self.pet, "voice_monitor_ready", False):
            for robot_id in sorted(active & recovering):
                if robot_id not in missing_starts:
                    visual.voice_started(robot_id)
            recovering.clear()
        if preempt_error is not None:
            raise preempt_error

    async def _on_voice_monitor_ready(self, ready: bool) -> None:
        if getattr(self, "_closed", False):
            return
        # Re-enable spontaneous voice only after a successful authenticated
        # event-stream bootstrap or ordered poll, never on a guessed timeout.
        self.pet.set_voice_monitor_ready(ready)

    async def _on_voice_global(self, reason: str) -> None:
        if getattr(self, "_closed", False):
            return  # Shutdown owns the final physical STOP and teardown.
        if reason not in ("gap", "reset", "stream_unavailable"):
            raise ValueError("Unsupported global voice transport fault")
        self.pet.set_voice_monitor_ready(False)
        visual = getattr(self, "multimodal", None)
        invalidate = getattr(visual, "voice_transport_unavailable", None)
        if callable(invalidate):
            invalidate()  # Sync cancellation; no camera/network await here.
        # The Mac's pet/group task cancellation does not itself flush an
        # autonomous native MiniCPM response already on the Xiaozhi head.
        # Reuse the bridge's existing ordinary interrupt, never the operator
        # quiet/revoke endpoint. Bound these independent physical STOP
        # requests to the listener's urgent half-second abort window.
        speaker = getattr(self.conversation, "speaker", None)
        stop = getattr(speaker, "monitor_lost", None)
        if not callable(stop):
            stop = getattr(speaker, "interrupt", None)
        native_stops = (
            [_bounded_monitor_stop(stop(robot))
             for robot in self.settings.robots if getattr(robot, "device_id", None)]
            if getattr(self.settings, "mode", None) == "hardware"
            and callable(stop) else []
        )
        outcomes = await asyncio.gather(
            self._preempt_audio_floor(), *native_stops, return_exceptions=True,
        )
        failures = [result for result in outcomes
                    if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError("Voice monitor lost; physical speaker stop unconfirmed") from failures[0]

    async def _on_voice_interrupt(self, robot_id: str, kind: str) -> None:
        if getattr(self, "_closed", False):
            return
        if robot_id not in {robot.id for robot in self.settings.robots}:
            raise KeyError(f"Unknown voice source: {robot_id}")
        if kind == "speech_end":
            # A real VAD-negative transition only slows camera sampling.
            # It MUST NOT stop current Xiaozhi playback or clear the last
            # visual evidence needed by the human's just-finished question.
            visual = getattr(self, "multimodal", None)
            if visual is not None:
                visual.voice_ended(robot_id)
            return
        visual = getattr(self, "multimodal", None)
        prepare = getattr(visual, "prepare_human_turn", None)
        # The VAD producer is authenticated already. Fence old camera/tool
        # work synchronously BEFORE awaiting slow audio STOP. This does not
        # launch another camera HTTP request, inference, or audio owner.
        if callable(prepare) and kind in ("speech_start", "normal", "group"):
            prepare(robot_id, end_expected=kind == "speech_start")
        # Human speech cancels one shared five-pet speech floor once. The
        # authenticated human camera must still start if audio STOP fails,
        # without treating the unresolved speaker lease as a success.
        preempt_error = None
        try:
            await self._preempt_audio_floor()
        except Exception as exc:
            preempt_error = exc
        if getattr(self, "_closed", False):
            return  # A late STOP completion must not reopen camera workers.
        if visual is not None:
            if callable(prepare):
                if kind in ("speech_start", "normal", "group"):
                    visual.start_speech_frames(robot_id)
            elif kind == "speech_start":
                visual.voice_started(robot_id)
            elif kind in ("normal", "group"):
                visual.voice_interrupted(robot_id)
        if preempt_error is not None:
            raise preempt_error

    async def close(self):
        """Attempt every owner cleanup even after one unconfirmed STOP."""
        # A timed out voice monitor might still be alive. Never authorize
        # a second listener on this runtime after shutdown has begun.
        self._closed = True
        errors: list[Exception] = []

        async def step(label: str, operation, deadline: float) -> None:
            task = asyncio.create_task(operation)
            try:
                done, _ = await asyncio.wait({task}, timeout=deadline)
                if not done:
                    raise TimeoutError(f"{label} shutdown unconfirmed")
                await task
            except Exception as exc:
                errors.append(exc)
            finally:
                if not task.done():
                    task.cancel()
                    task.add_done_callback(
                        lambda done: None if done.cancelled() else done.exception()
                    )

        # Physical motor STOP is always attempted before expensive voice
        # and camera teardown. A stuck pet cannot starve its four peers.
        if self.settings.mode == "hardware":
            try:
                self.pet.set_voice_monitor_ready(False)
            except Exception as exc:
                errors.append(exc)
        await step("WROOM motion", self.coordinator.close(), 4.0)
        # Stop the one read-only USB producer after the urgent WROOM STOP and
        # before tearing down per-pet camera and context owners.
        self._room_stop.set()
        if self._room_task is not None:
            await step("Shared room USB", self._room_task, 1.0)
            self._room_task = None
        unconfirmed = getattr(self.coordinator, "shutdown_stop_failures", {})
        if unconfirmed:
            # An idle robot can still have an uncertain prior motor pulse.
            # Surface each failed physical STOP after attempting all cleanup.
            errors.append(RuntimeError(
                "WROOM shutdown STOP unconfirmed for "
                + ", ".join(sorted(unconfirmed))
            ))

        # Shutdown must explicitly stop every native Xiaozhi decoder even
        # when the VAD monitor never emitted its normal loss callback.
        # Send to all heads in parallel; a silent or stalled peer cannot
        # prevent another robot from receiving the urgent bridge request.
        if self.settings.mode == "hardware":
            robots = [r for r in self.settings.robots if r.device_id]
            if robots:
                speaker = getattr(self.conversation, "speaker", None)
                stop = getattr(speaker, "monitor_lost", None)
                if not callable(stop):
                    stop = getattr(speaker, "interrupt", None)
                if not callable(stop):
                    errors.append(RuntimeError("Native speaker shutdown STOP unavailable"))
                else:
                    outcomes = await asyncio.gather(
                        *(_bounded_monitor_stop(stop(robot)) for robot in robots),
                        return_exceptions=True,
                    )
                    for robot, result in zip(robots, outcomes):
                        if isinstance(result, BaseException):
                            errors.append(RuntimeError(
                                f"Native speaker shutdown STOP unconfirmed for {robot.id}"
                            ))

        if self._voice_task is not None:
            task = self._voice_task
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=_RUNTIME_VOICE_STOP_TIMEOUT_S)
            if not done:
                errors.append(TimeoutError("Native voice monitor shutdown unconfirmed"))
                task.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )
            elif not task.cancelled():
                error = task.exception()
                if error is not None:
                    errors.append(error)
            if done:
                self._voice_task = None
            # Otherwise retain the cancelled but still live task as owned.

        await step("Pet observer", self.pet.close(), 5.0)
        if self.multimodal is not None:
            await step("Camera orchestration", self.multimodal.close(), 3.0)
        await step("Conversation", self.conversation.stop(), 3.0)
        await step("Mac HTTP client", self.client.aclose(), 3.0)
        if errors:
            raise errors[0]
