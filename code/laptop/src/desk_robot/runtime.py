from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx

from .attention import AttentionLedger
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
from .soil_calibration import SoilCalibration
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
        # This shared client carries head, voice and model credentials.
        # Ambient system proxies must not intercept private Mac/LAN traffic.
        self.client = httpx.AsyncClient(trust_env=False)
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
        self.attention = AttentionLedger([r.id for r in settings.robots])
        self.coordinator = Coordinator(settings, heads, vision)
        self.conversation = Conversation(settings, chat, speaker, memory=self.memory)
        self.conversation.coordinator_jobs = self.coordinator.jobs
        self.conversation.attention = self.attention
        self.pet = PetController(
            settings, heads, self.conversation, self.memory, scene,
            on_local_fault=self.coordinator.stop,
        )
        # Shared read-only activity context for the pet; the Coordinator
        # still exclusively owns the job, permits and physical commands.
        self.pet.coordinator_jobs = self.coordinator.jobs
        self.pet.attention = self.attention
        self.multimodal: MultimodalOrchestrator | None = None
        if settings.mode == "hardware":
            # One lock serves background visual comparison and user question
            # inference across ALL five pets; no second camera transport.
            self.multimodal = MultimodalOrchestrator(
                settings, heads, scene, self.pet._vision_lock
            )
            self.pet.multimodal = self.multimodal
            self.conversation.multimodal = self.multimodal
            # Qualified hardware exploration shares this SAME stream.
            # Never start a second capture loop when the body is driving.
            self.coordinator.multimodal = self.multimodal
            self.multimodal.preempt_background_vision = (
                self.pet.preempt_background_vision
            )
            # A human's look is higher priority for its ENTIRE camera +
            # inference lifetime, not just the instant preemption is sent.
            self.multimodal.begin_direct_vision = self.pet.begin_direct_vision
            self.multimodal.end_direct_vision = self.pet.end_direct_vision
        self.voice_events: VoiceEventListener | None = None
        # Authenticated Xiaozhi tool receipt owner, distinct from Mac turn epoch.
        # None means disconnected or untrusted; absent robot IDs have no owner.
        self._voice_turn_generations: dict[str, int] | None = None
        self._voice_task: asyncio.Task | None = None
        self._room_stop = asyncio.Event()
        self._room_task: asyncio.Task | None = None
        self.room_feed: RoomSerialFeed | None = None
        # The USB thread may emit faster than the Mac can consume room context.
        # One coalesced, latest-only callback cannot crowd out live human VAD.
        self._room_dispatch_lock = threading.Lock()
        # Queue provenance belongs to the original sharing grant, not a later ON.
        self._room_dispatch_pending: tuple[RoomObservation, int | None, bool] | None = None
        self._room_dispatch_enqueued = False
        self.room_context_failures = 0
        self._closed = False
        self._voice_stop_attempt = 0
        self._voice_stop_unconfirmed = False

    def _on_room_observation(self, observation: RoomObservation) -> None:
        """One Mac owner shares only opt-in, ephemeral environmental facts."""
        if (not self._closed and self.settings.room_station_context_enabled
                and self.multimodal is not None):
            self.multimodal.hub.remember_room(observation)

    def _deliver_room_observation(self) -> None:
        """Consume the latest room measurement, not every intermediate sample.

        Only the event-loop thread calls this method. The serial reader never
        waits for environmental prompt assembly, inference or other UI work.
        """
        with self._room_dispatch_lock:
            queued = self._room_dispatch_pending
            self._room_dispatch_pending = None
            self._room_dispatch_enqueued = False
        if queued is not None:
            observation, grant_generation, granted_at_queue = queued
            if (
                not granted_at_queue
                or not self.settings.room_station_context_enabled
                or getattr(self.settings, "room_station_consent_generation", None)
                != grant_generation
            ):
                return
            try:
                self._on_room_observation(observation)
            except Exception:
                # An optional context consumer must never fault the event-loop
                # callback or prevent the next fresh USB observation arriving.
                self.room_context_failures = getattr(self, "room_context_failures", 0) + 1
                if self.room_context_failures == 1 or self.room_context_failures % 100 == 0:
                    logging.getLogger(__name__).exception(
                        "Room context consumer failed (%d total)",
                        self.room_context_failures,
                    )

    def _queue_room_observation(self, loop, observation: RoomObservation) -> None:
        """Bound the USB-to-Mac handoff to one scheduled callback per runtime.

        The station provides replaceable read-only environmental snapshots,
        not discrete safety or motor events. Under a burst, the latest valid
        observation wins, so a noisy USB producer cannot queue thousands of
        callbacks ahead of human voice and camera tasks. A closing event loop
        must not silently schedule into a new connection epoch.
        """
        with self._room_dispatch_lock:
            if self._closed:
                return
            # Serial callbacks and operator consent updates run on different
            # threads. Both values must belong to the SAME permission epoch.
            # Otherwise an old ON sample could be tagged with a new grant.
            grant_before = getattr(
                self.settings, "room_station_consent_generation", None
            )
            granted = self.settings.room_station_context_enabled
            grant_after = getattr(
                self.settings, "room_station_consent_generation", None
            )
            self._room_dispatch_pending = (
                observation, grant_after, granted and grant_before == grant_after,
            )
            if self._room_dispatch_enqueued:
                return
            self._room_dispatch_enqueued = True
        try:
            loop.call_soon_threadsafe(self._deliver_room_observation)
        except RuntimeError:
            with self._room_dispatch_lock:
                self._room_dispatch_pending = None
                self._room_dispatch_enqueued = False
            if not self._closed:
                raise

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
            dry = self.settings.room_station_soil_dry_adc
            soil_calibration = (
                SoilCalibration(dry, self.settings.room_station_soil_wet_adc)
                if dry is not None else None
            )
            self.room_feed = RoomSerialFeed(
                self.settings.room_station_port,
                lambda observation: self._queue_room_observation(
                    loop, observation
                ),
                soil_calibration=soil_calibration,
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
            on_voice_generations=self._on_voice_generations,
            require_snapshot=True,
            require_turn_generations=True,
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


    def _on_voice_generations(self, generations: dict[str, int] | None) -> None:
        """Keep only current authenticated Xiaozhi source turn ownership.

        The voice listener calls this before awaiting a slow human speaker
        STOP. It is not a Mac turn counter, motor grant or tool execution.
        """
        if getattr(self, "_closed", False):
            return
        self._voice_turn_generations = (
            None if generations is None else dict(generations)
        )

    def _begin_voice_stop(self) -> int:
        """Keep a separate pending STOP receipt while cameras mark human VAD."""
        attempt = getattr(self, "_voice_stop_attempt", 0) + 1
        self._voice_stop_attempt = attempt
        # Set before any await so cancellation and newer callbacks fail closed.
        self._voice_stop_unconfirmed = True
        return attempt

    def _confirm_voice_stop(self, attempt: int) -> None:
        # A slower older STOP cannot clear a newer unresolved preemption.
        if getattr(self, "_voice_stop_attempt", None) == attempt:
            self._voice_stop_unconfirmed = False

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

    async def _stop_autonomous_roaming_for_voice(self) -> None:
        """Human VAD or monitor loss stops active exploration, not manual jobs.

        The coordinator already owns WROOM STOP and local watchdog recovery.
        It must be dispatched alongside the urgent speaker stop, never
        serially behind a slow audio or camera task.
        """
        coordinator = getattr(self, "coordinator", None)
        stop = getattr(coordinator, "stop_active_exploration", None)
        if callable(stop):
            await stop()

    async def _on_voice_snapshot(self, active: frozenset[str]) -> None:
        if getattr(self, "_closed", False):
            return
        visual = getattr(self, "multimodal", None)
        if visual is None:
            if getattr(self, "_voice_stop_unconfirmed", False):
                raise RuntimeError("Unconfirmed speaker STOP without voice owner")
            return
        # The authenticated snapshot describes the server state before
        # asynchronous decoder STOP. Later live VAD edges supersede it.
        voice_edges_at_snapshot = getattr(self, "_voice_edge_generation", 0)
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
        # Reconnect must also reconcile the volatile conversation turn
        # clock, so a delayed transmitted sentence cannot revive after barge.
        # This is read-only state, independent of the urgent physical STOP.
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
        prepared_epochs: dict[str, int] = {}
        # Camera preparation already set voice_until=inf on a failed STOP.
        # A matching retry snapshot must still retry the unresolved speaker
        # abort instead of publishing a healthy monitor and cursor.
        retry_unconfirmed_stop = getattr(self, "_voice_stop_unconfirmed", False)
        if missing_starts or retry_unconfirmed_stop:
            attention = getattr(self, "attention", None)
            if attention is not None:
                for robot_id in missing_starts:
                    attention.human_started(robot_id, time.monotonic())
            prepare = getattr(visual, "prepare_human_turn", None)
            # Mark authenticated VAD NOW. A slow Xiaozhi STOP cannot keep
            # old camera or VLM activity alive during speaker teardown.
            if callable(prepare):
                for robot_id in sorted(missing_starts):
                    prepare(robot_id, end_expected=True)
                # Preparing a second active pet invalidates all peers' prior
                # visual generations. Read tokens only after the whole fleet
                # snapshot has been prepared, before the slow speaker STOP.
                read_epoch = getattr(visual, "prepared_turn_epoch", None)
                if callable(read_epoch):
                    for robot_id in missing_starts:
                        token = read_epoch(robot_id)
                        if type(token) is int:
                            prepared_epochs[robot_id] = token
            # A recovered VAD snapshot can be the FIRST evidence of a
            # speaking human. Both speech and roaming stop concurrently.
            stop_attempt = self._begin_voice_stop()
            outcomes = await asyncio.gather(
                self._preempt_audio_floor(),
                self._stop_autonomous_roaming_for_voice(),
                return_exceptions=True,
            )
            failures = [
                result for result in outcomes
                if isinstance(result, BaseException)
            ]
            if failures:
                # Unconfirmed audio or body STOP remains visible; camera
                # VAD reconciliation still occurs below.
                preempt_error = failures[0]
            else:
                self._confirm_voice_stop(stop_attempt)
            if getattr(self, "_closed", False):
                return
            if getattr(self, "_voice_edge_generation", 0) != voice_edges_at_snapshot:
                # A newer start/end supersedes the entire recovered snapshot.
                # Do not rearm its camera, release a newer human speech floor,
                # or resurrect an already ended VAD via stale reconciliation.
                # A fresh authenticated snapshot can reconcile other peers.
                if preempt_error is not None:
                    raise preempt_error
                return
            for robot_id in sorted(missing_starts):
                if callable(prepare):
                    token = prepared_epochs.get(robot_id)
                    if type(token) is int:
                        visual.start_speech_frames(
                            robot_id, prepared_epoch=token,
                        )
                    else:
                        visual.start_speech_frames(robot_id)
                else:
                    visual.voice_started(robot_id)
        # A lost speech_end must stop that head's optional 1 FPS sampler,
        # not just clear the speaker lease in the hub.
        for robot_id in sorted(missing_ends):
            attention = getattr(self, "attention", None)
            if attention is not None:
                attention.human_ended(robot_id, time.monotonic())
            visual.voice_ended(robot_id)
        visual.hub.reconcile_speech_snapshot(active, time.monotonic())
        # A transport outage cancels optional camera workers without
        # pretending a still-active human stopped speaking. Resume their
        # sampler ONLY after the authenticated monitor is healthy again.
        recovering = getattr(visual, "_reconnect_needs_sampler", None)
        if (recovering and getattr(self.pet, "voice_monitor_ready", False)
                and preempt_error is None
                and not getattr(self, "_voice_stop_unconfirmed", False)):
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
        if not ready:
            # A dead VAD monitor cannot certify a current signed tool turn.
            self._voice_turn_generations = None
        self.pet.set_voice_monitor_ready(ready)
        if not ready:
            # A robot cannot keep autonomous roaming when the user has lost
            # the ability to interrupt it through the voice monitor.
            await self._stop_autonomous_roaming_for_voice()

    async def _on_voice_global(self, reason: str) -> None:
        if getattr(self, "_closed", False):
            return  # Shutdown owns the final physical STOP and teardown.
        if reason not in ("gap", "reset", "stream_unavailable"):
            raise ValueError("Unsupported global voice transport fault")
        self._voice_turn_generations = None
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
        stop_attempt = self._begin_voice_stop()
        outcomes = await asyncio.gather(
            self._preempt_audio_floor(),
            self._stop_autonomous_roaming_for_voice(),
            *native_stops,
            return_exceptions=True,
        )
        failures = [result for result in outcomes
                    if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError("Voice monitor lost; physical speaker stop unconfirmed") from failures[0]
        self._confirm_voice_stop(stop_attempt)

    async def _on_voice_interrupt(self, robot_id: str, kind: str) -> None:
        if getattr(self, "_closed", False):
            return
        if robot_id not in {robot.id for robot in self.settings.robots}:
            raise KeyError(f"Unknown voice source: {robot_id}")
        # The listener validated this real VAD edge. Fence any earlier
        # asynchronously recovering server snapshot before changing leases.
        self._voice_edge_generation = getattr(self, "_voice_edge_generation", 0) + 1
        attention = getattr(self, "attention", None)
        if attention is not None and kind in ("speech_start", "normal", "group"):
            attention.human_started(robot_id, time.monotonic())
        if kind == "speech_end":
            if attention is not None:
                attention.human_ended(robot_id, time.monotonic())
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
        prepared_epoch = None
        if callable(prepare) and kind in ("speech_start", "normal", "group"):
            prepared_epoch = prepare(robot_id, end_expected=kind == "speech_start")
        # Human speech cancels one shared five-pet speech floor once. The
        # authenticated human camera must still start if audio STOP fails,
        # without treating the unresolved speaker lease as a success.
        stop_attempt = self._begin_voice_stop()
        outcomes = await asyncio.gather(
            self._preempt_audio_floor(),
            self._stop_autonomous_roaming_for_voice(),
            return_exceptions=True,
        )
        failures = [
            result for result in outcomes if isinstance(result, BaseException)
        ]
        preempt_error = failures[0] if failures else None
        if preempt_error is None:
            self._confirm_voice_stop(stop_attempt)
        if getattr(self, "_closed", False):
            return  # A late STOP completion must not reopen camera workers.
        if visual is not None:
            if callable(prepare):
                if kind in ("speech_start", "normal", "group"):
                    if type(prepared_epoch) is int:
                        visual.start_speech_frames(
                            robot_id, prepared_epoch=prepared_epoch,
                        )
                    else:
                        # Older test adapters have no turn token; the real
                        # multimodal owner always provides one.
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
        with self._room_dispatch_lock:
            self._room_dispatch_pending = None
        errors: list[Exception] = []

        async def step(label: str, operation, deadline: float) -> None:
            task = asyncio.create_task(operation)
            try:
                done, _ = await asyncio.wait({task}, timeout=deadline)
                if not done:
                    raise TimeoutError(f"{label} shutdown unconfirmed")
                await task
            except asyncio.CancelledError:
                # A child owner may cancel itself independently of shutdown.
                # Never let that skip STOP attempts for the other four pets,
                # camera, speech and HTTP. An externally cancelled shutdown
                # still propagates, rather than masquerading as cleanup.
                if asyncio.current_task().cancelling():
                    raise
                errors.append(RuntimeError(
                    f"{label} shutdown task cancelled without confirmation"
                ))
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
        # Cancelling a Coordinator job never terminates native CPU inference.
        # Report an unconfirmed shutdown rather than abandoning a live worker.
        vision_close = getattr(
            getattr(self.coordinator, "vision", None), "close", None
        )
        if callable(vision_close):
            await step("YOLO native inference", vision_close(), 2.0)
        # The process-global AprilTag C worker also outlives canceled
        # asyncio requests. Do not silently leave a hung detector reusable
        # by another Runtime instance or any of the five robots.
        if self.settings.mode == "hardware":
            from .dock_runtime import close_detector_pool
            await step("AprilTag native detector", close_detector_pool(), 2.0)
        # Stop the one read-only USB producer after the urgent WROOM STOP and
        # before tearing down per-pet camera and context owners.
        room_stop = getattr(self, "_room_stop", None)
        if room_stop is not None:
            room_stop.set()
        room_task = getattr(self, "_room_task", None)
        if room_task is not None:
            async def wait_room_shutdown():
                # The generic shutdown deadline cancels its OWN waiter.
                # Shield the real USB reader so timeout does not cancel its
                # still-running OS worker or disguise unfinished ownership.
                await asyncio.shield(room_task)
            await step("Shared room USB", wait_room_shutdown(), 1.0)
            # A stalled callback or serial worker may outlive the deadline.
            # Retain ownership until the actual reader task has terminated;
            # never turn an unconfirmed USB shutdown into an absent reader.
            if room_task.done():
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
                    for robot, result in zip(robots, outcomes, strict=True):
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
        camera = getattr(self, "multimodal", None)
        if camera is not None:
            await step("Camera orchestration", camera.close(), 3.0)
        await step("Conversation", self.conversation.stop(), 3.0)
        await step("Mac HTTP client", self.client.aclose(), 3.0)
        if errors:
            raise errors[0]
