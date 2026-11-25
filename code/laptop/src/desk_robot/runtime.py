from __future__ import annotations

import asyncio
import inspect
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
from .spatial_runtime import SpatialRuntime
from .transport import HttpHead
from .vision import OllamaScene, YoloWorldVision

_MONITOR_STOP_TIMEOUT_S = 0.35
_RUNTIME_VOICE_STOP_TIMEOUT_S = 2.5
_RUNTIME_PET_STOP_TIMEOUT_S = 5.0


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
            on_low_battery_dock=self._on_low_battery_dock,
            on_dock_inhibit_changed=self._on_dock_inhibit_changed,
        )
        self.spatial = SpatialRuntime(settings, self.memory)
        self.coordinator.spatial = self.spatial
        self.pet.spatial = self.spatial
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
        self._room_dispatch_pending = None
        self._room_dispatch_enqueued = False
        self._room_connection_epoch = 0
        self.room_context_failures = 0
        self._closed = False
        self._close_task: asyncio.Task | None = None
        self._shutdown_step_tasks: dict[str, asyncio.Task] = {}
        self._fatal_service_error: RuntimeError | None = None
        self._voice_stop_attempt = 0
        self._voice_stop_unconfirmed = False
        self._voice_speech_active: set[str] = set()

    def _on_room_observation(self, observation: RoomObservation) -> None:
        """One Mac owner shares only opt-in, ephemeral environmental facts."""
        if (not self._closed and self.settings.room_station_context_enabled
                and self.multimodal is not None):
            remember = self.multimodal.hub.remember_room
            try:
                params = inspect.signature(remember).parameters
                accepts_epoch = "epoch" in params or any(
                    p.kind is inspect.Parameter.VAR_KEYWORD
                    for p in params.values()
                )
            except (TypeError, ValueError):
                accepts_epoch = False
            if accepts_epoch:
                remember(
                    observation,
                    epoch=getattr(self, "_room_connection_epoch", 0),
                )
            else:
                remember(observation)

    def _on_room_disconnect(self) -> None:
        """Invalidate pending and cached room state when USB disconnects."""
        with self._room_dispatch_lock:
            self._room_connection_epoch = getattr(self, "_room_connection_epoch", 0) + 1
            epoch = self._room_connection_epoch
            self._room_dispatch_pending = None
        multimodal = getattr(self, "multimodal", None)
        hub = getattr(multimodal, "hub", None)
        if hub is not None and hasattr(hub, "invalidate_room"):
            hub.invalidate_room(epoch=epoch)

    def _deliver_room_observation(self) -> None:
        """Consume the latest room measurement, not every intermediate sample.

        Only the event-loop thread calls this method. The serial reader never
        waits for environmental prompt assembly, inference or other UI work.
        """
        with self._room_dispatch_lock:
            queued = self._room_dispatch_pending
            self._room_dispatch_pending = None
            self._room_dispatch_enqueued = False
            current_conn_epoch = getattr(self, "_room_connection_epoch", 0)
        if queued is not None:
            if len(queued) == 4:
                observation, grant_generation, granted_at_queue, conn_epoch = queued
            else:
                observation, grant_generation, granted_at_queue = queued
                conn_epoch = current_conn_epoch
            if (
                not granted_at_queue
                or conn_epoch != current_conn_epoch
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
            conn_epoch = getattr(self, "_room_connection_epoch", 0)
            self._room_dispatch_pending = (
                observation, grant_after, granted and grant_before == grant_after,
                conn_epoch,
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

    def _on_dock_inhibit_changed(self, robot_id: str, inhibited: bool) -> None:
        if getattr(self, "_closed", False):
            return
        setter = getattr(getattr(self, "coordinator", None), "set_dock_charge_inhibition", None)
        if callable(setter):
            setter(robot_id, inhibited)

    async def _on_low_battery_dock(self, robot_id: str, initial_low: bool) -> None:
        if getattr(self, "_closed", False):
            return
        requester = getattr(
            getattr(self, "coordinator", None),
            "request_autonomous_low_battery_dock",
            None,
        )
        if callable(requester):
            await requester(robot_id, initial_low=initial_low)

    async def start(self):
        """Bridge Xiaozhi's real voice interruption into Mac speech cancellation."""
        if getattr(self, "_closed", False):
            raise RuntimeError("Closed runtime cannot restart voice listeners")
        if self.settings.mode != "hardware" or self._voice_task is not None:
            return
        if any(robot.dock_calibration is not None for robot in self.settings.robots):
            from .dock_runtime import prewarm_detector_pool

            await prewarm_detector_pool()
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
                on_disconnect=self._on_room_disconnect,
            )
            self._room_task = asyncio.create_task(
                self.room_feed.run(self._room_stop),
            )
            self._room_task.add_done_callback(
                lambda task: self._on_service_done("Shared room USB", task)
            )
        if not any(robot.device_id for robot in self.settings.robots):
            return
        sync_voice = getattr(getattr(self, "coordinator", None), "set_voice_state", None)
        if callable(sync_voice):
            sync_voice(monitor_enforced=True, monitor_ready=False, voice_stop_unconfirmed=False)
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
        self._voice_task.add_done_callback(
            lambda task: self._on_service_done("Native voice monitor", task)
        )
        if self.settings.pet_autostart_enabled:
            self.pet.on_low_battery_dock = self._on_low_battery_dock
            self.pet.on_dock_inhibit_changed = self._on_dock_inhibit_changed
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
                if callable(read_epoch) and missing_starts:
                    # Preparing any new start also retired the fallback
                    # samplers of peers whose human VAD is still active.
                    for robot_id in active:
                        token = read_epoch(robot_id)
                        if type(token) is int:
                            prepared_epochs[robot_id] = token
            # A recovered VAD snapshot can be the FIRST evidence of a
            # speaking human. Both speech and roaming stop concurrently.
            stop_attempt = self._begin_voice_stop()
            sync_voice = getattr(getattr(self, "coordinator", None), "set_voice_state", None)
            if callable(sync_voice):
                sync_voice(
                    active_robots=set(active) | set(getattr(self, "_voice_speech_active", ())),
                    voice_stop_unconfirmed=True,
                )
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
            for robot_id in sorted(set(missing_starts) | prepared_epochs.keys()):
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
            read_epoch = getattr(visual, "prepared_turn_epoch", None)
            for robot_id in sorted(active & recovering):
                if robot_id not in missing_starts and robot_id not in prepared_epochs:
                    if callable(read_epoch):
                        # The outage already fenced every old visual turn.
                        # Preparing another start here would cancel the
                        # recovered sampler of every previously resumed peer.
                        visual.start_speech_frames(
                            robot_id, prepared_epoch=read_epoch(robot_id),
                        )
                    else:
                        visual.voice_started(robot_id)
            recovering.clear()
        self._voice_speech_active = set(active)
        coord = getattr(self, "coordinator", None)
        sync_voice = getattr(coord, "set_voice_state", None)
        if callable(sync_voice):
            sync_voice(
                active_robots=self._voice_speech_active,
                voice_stop_unconfirmed=getattr(self, "_voice_stop_unconfirmed", False),
            )
        if preempt_error is not None:
            raise preempt_error
        if (
            not self._voice_speech_active
            and not getattr(self, "_voice_stop_unconfirmed", False)
            and callable(getattr(coord, "dispatch_next_deferred", None))
        ):
            await coord.dispatch_next_deferred()

    async def _on_voice_monitor_ready(self, ready: bool) -> None:
        if getattr(self, "_closed", False):
            return
        # Re-enable spontaneous voice only after a successful authenticated
        # event-stream bootstrap or ordered poll, never on a guessed timeout.
        coord = getattr(self, "coordinator", None)
        sync_voice = getattr(coord, "set_voice_state", None)
        if ready:
            if getattr(self, "_voice_stop_unconfirmed", False):
                raise RuntimeError("Voice monitor recovery requires confirmed STOP")
            self.pet.set_voice_monitor_ready(True)
            if callable(sync_voice):
                sync_voice(
                    monitor_enforced=True,
                    monitor_ready=True,
                    voice_stop_unconfirmed=False,
                )
            dispatch = getattr(coord, "dispatch_next_deferred", None)
            if callable(dispatch) and not getattr(self, "_voice_speech_active", ()):
                await dispatch()
            return
        # A dead VAD monitor cannot certify a current signed tool turn.
        self._voice_turn_generations = None
        if callable(sync_voice):
            sync_voice(monitor_enforced=True, monitor_ready=False)
        try:
            self.pet.set_voice_monitor_ready(False)
        finally:
            # A failed health notification must not skip stopping roaming.
            await self._stop_autonomous_roaming_for_voice()

    async def _on_voice_global(self, reason: str) -> None:
        if getattr(self, "_closed", False):
            return  # Shutdown owns the final physical STOP and teardown.
        if reason not in ("gap", "reset", "stream_unavailable"):
            raise ValueError("Unsupported global voice transport fault")
        self._voice_turn_generations = None
        stop_attempt = self._begin_voice_stop()
        coord = getattr(self, "coordinator", None)
        sync_voice = getattr(coord, "set_voice_state", None)
        if callable(sync_voice):
            sync_voice(
                monitor_enforced=True,
                monitor_ready=False,
                voice_stop_unconfirmed=True,
            )
        failures: list[BaseException] = []
        # Neither synchronous callback may skip the independent native
        # decoder, group audio, or roaming STOP owners.
        try:
            self.pet.set_voice_monitor_ready(False)
        except Exception as exc:
            failures.append(exc)
        visual = getattr(self, "multimodal", None)
        invalidate = getattr(visual, "voice_transport_unavailable", None)
        if callable(invalidate):
            try:
                invalidate()  # Sync cancellation; no camera/network await here.
            except Exception as exc:
                failures.append(exc)
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
            self._preempt_audio_floor(),
            self._stop_autonomous_roaming_for_voice(),
            *native_stops,
            return_exceptions=True,
        )
        failures.extend(result for result in outcomes
                        if isinstance(result, BaseException))
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
        speech_active = getattr(self, "_voice_speech_active", None)
        if speech_active is None:
            speech_active = set()
            self._voice_speech_active = speech_active
        coord = getattr(self, "coordinator", None)
        sync_voice = getattr(coord, "set_voice_state", None)
        if attention is not None and kind in ("speech_start", "normal", "group"):
            attention.human_started(robot_id, time.monotonic())
        if kind == "speech_end":
            speech_active.discard(robot_id)
            if callable(sync_voice):
                sync_voice(active_robots=speech_active)
            if attention is not None:
                attention.human_ended(robot_id, time.monotonic())
            # A real VAD-negative transition only slows camera sampling.
            # It MUST NOT stop current Xiaozhi playback or clear the last
            # visual evidence needed by the human's just-finished question.
            visual = getattr(self, "multimodal", None)
            if visual is not None:
                visual.voice_ended(robot_id)
            dispatch = getattr(coord, "dispatch_next_deferred", None)
            if (
                callable(dispatch)
                and not speech_active
                and not getattr(self, "_voice_stop_unconfirmed", False)
            ):
                await dispatch()
            return
        if kind == "speech_start":
            speech_active.add(robot_id)
        visual = getattr(self, "multimodal", None)
        prepare = getattr(visual, "prepare_human_turn", None)
        # The VAD producer is authenticated already. Fence old camera/tool
        # work synchronously BEFORE awaiting slow audio STOP. This does not
        # launch another camera HTTP request, inference, or audio owner.
        prepared_epoch = None
        prepared_peers: dict[str, int] = {}
        if callable(prepare) and kind in ("speech_start", "normal", "group"):
            prepared_epoch = prepare(robot_id, end_expected=kind == "speech_start")
            read_epoch = getattr(visual, "prepared_turn_epoch", None)
            if type(prepared_epoch) is int and callable(read_epoch):
                # The new turn invalidates every peer's old fallback sampler,
                # not just the initiating head. Save their new epochs before
                # awaiting STOP; newer speech edges must fence this restart.
                now = time.monotonic()
                for peer in visual.hub.robots:
                    if peer != robot_id and visual.hub.user_active(peer, now):
                        prepared_peers[peer] = read_epoch(peer)
        # Human speech cancels one shared five-pet speech floor once. The
        # authenticated human camera must still start if audio STOP fails,
        # without treating the unresolved speaker lease as a success.
        stop_attempt = self._begin_voice_stop()
        if callable(sync_voice):
            sync_voice(
                active_robots=speech_active,
                voice_stop_unconfirmed=True,
            )
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
            if callable(sync_voice):
                sync_voice(
                    voice_stop_unconfirmed=getattr(self, "_voice_stop_unconfirmed", False),
                )
        if getattr(self, "_closed", False):
            return  # A late STOP completion must not reopen camera workers.
        if visual is not None:
            if callable(prepare):
                if kind in ("speech_start", "normal", "group"):
                    if type(prepared_epoch) is int:
                        visual.start_speech_frames(
                            robot_id, prepared_epoch=prepared_epoch,
                        )
                        for peer, epoch in sorted(prepared_peers.items()):
                            visual.start_speech_frames(peer, prepared_epoch=epoch)
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

    def _on_service_done(self, label: str, task: asyncio.Task) -> None:
        """An unexpected permanent service exit closes every runtime owner."""
        if getattr(self, "_closed", False):
            return  # Normal shutdown collects the existing task itself.
        cause = None if task.cancelled() else task.exception()
        failure = RuntimeError(f"{label} stopped unexpectedly")
        if cause is not None:
            failure.__cause__ = cause
        self._fatal_service_error = failure
        logging.getLogger(__name__).error(str(failure), exc_info=cause)
        # Fence late voice receipts before dispatching the one cleanup owner.
        # Ordinary serial/voice reconnect errors are handled by their loops
        # and do not reach this permanent-exit callback.
        shutdown = self._begin_shutdown()
        shutdown.add_done_callback(self._observe_fatal_shutdown)

    @staticmethod
    def _observe_fatal_shutdown(task: asyncio.Task) -> None:
        # The service failure may happen without an API lifespan waiter.
        # Consume the cleanup result, but retain it for the next close().
        logger = logging.getLogger(__name__)
        if task.cancelled():
            logger.error("Fatal runtime shutdown cancelled without confirmation")
        elif (error := task.exception()) is not None:
            logger.error("Fatal runtime shutdown failed", exc_info=error)

    def _begin_shutdown(self) -> asyncio.Task:
        self._closed = True
        self._voice_turn_generations = None
        task = getattr(self, "_close_task", None)
        fatal = getattr(self, "_fatal_service_error", None)
        if task is None or (task.done() and fatal is None):
            task = asyncio.create_task(self._close_owners())
            self._close_task = task
        return task

    async def close(self):
        """Finish bounded owner cleanup before propagating caller cancellation."""
        task = self._begin_shutdown()
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # A cancelled lifespan waiter must not cancel the physical STOP
            # owner or skip the remaining USB, audio, camera and HTTP cleanup.
            # Repeated caller cancellation must not detach the cleanup either.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                error = task.exception()
                if error is not None:
                    logging.getLogger(__name__).error(
                        "Runtime shutdown failed during caller cancellation",
                        exc_info=error,
                    )
            raise
        except Exception as error:
            fatal = getattr(self, "_fatal_service_error", None)
            if fatal is not None:
                raise fatal from error
            raise
        finally:
            if (task.done() and self._close_task is task
                    and getattr(self, "_fatal_service_error", None) is None):
                self._close_task = None
        fatal = getattr(self, "_fatal_service_error", None)
        if fatal is not None:
            raise fatal

    def _retire_shutdown_step(self, label: str, task: asyncio.Task) -> None:
        """Keep ownership until the task, not just its waiter, is terminal."""
        if not task.cancelled():
            error = task.exception()
            if task.cancelling() and error is not None:
                logging.getLogger(__name__).error(
                    "Late %s shutdown failure", label, exc_info=error,
                )
        if self._shutdown_step_tasks.get(label) is task:
            self._shutdown_step_tasks.pop(label)

    async def _close_owners(self):
        """Attempt every owner cleanup even after one unconfirmed STOP."""
        with self._room_dispatch_lock:
            self._room_dispatch_pending = None
        errors: list[Exception] = []
        pending = getattr(self, "_shutdown_step_tasks", None)
        if pending is None:
            pending = self._shutdown_step_tasks = {}

        async def step(label: str, operation, deadline: float) -> None:
            task = pending.get(label)
            try:
                # The previous close may have timed out without terminating
                # this owner. Join it again rather than launching a duplicate.
                if task is None or task.done():
                    task = asyncio.create_task(operation())
                    pending[label] = task
                    task.add_done_callback(
                        lambda done: self._retire_shutdown_step(label, done)
                    )
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
                if task is not None and not task.done() and not task.cancelling():
                    task.cancel()
                    # The registry and terminal callback retain and observe it.

        # Physical motor STOP is always attempted before expensive voice
        # and camera teardown. A stuck pet cannot starve its four peers.
        if self.settings.mode == "hardware":
            try:
                self.pet.set_voice_monitor_ready(False)
            except Exception as exc:
                errors.append(exc)
        await step("WROOM motion", self.coordinator.close, 4.0)
        spatial = getattr(self, "spatial", None)
        if spatial is not None:
            for robot in self.settings.robots:
                spatial.invalidate_robot(robot.id, reason="runtime_closed")
        unconfirmed = getattr(self.coordinator, "shutdown_stop_failures", {})
        if unconfirmed:
            # An idle robot can still have an uncertain prior motor pulse.
            # Surface each failed physical STOP after attempting all cleanup.
            errors.append(RuntimeError(
                "WROOM shutdown STOP unconfirmed for "
                + ", ".join(sorted(unconfirmed))
            ))

        # Signal the independent USB producer promptly after WROOM STOP.
        # Its real thread may need time to drain; joining it must not delay
        # an urgent native decoder STOP.
        room_stop = getattr(self, "_room_stop", None)
        if room_stop is not None:
            room_stop.set()

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
            # A repeated close must not interrupt an owner's ongoing cleanup.
            if not task.done() and not task.cancelling():
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

        # Slow optional inference and USB joins cannot delay speaker STOP.
        # Cancelling a Coordinator job never terminates native CPU inference.
        # Report an unconfirmed shutdown rather than abandoning a live worker.
        vision_close = getattr(
            getattr(self.coordinator, "vision", None), "close", None
        )
        if callable(vision_close):
            await step("YOLO native inference", vision_close, 2.0)
        # Kill/reap the shared AprilTag processes only after physical STOP.
        # An unconfirmed reap keeps the old owner closed to every robot.
        if self.settings.mode == "hardware":
            from .dock_runtime import close_detector_pool
            await step("AprilTag native detector", close_detector_pool, 2.0)
        room_task = getattr(self, "_room_task", None)
        if room_task is not None:
            async def wait_room_shutdown():
                # The generic shutdown deadline cancels its OWN waiter.
                # Shield the real USB reader so timeout does not cancel its
                # still-running OS worker or disguise unfinished ownership.
                await asyncio.shield(room_task)
            await step("Shared room USB", wait_room_shutdown, 1.0)
            # A stalled callback or serial worker may outlive the deadline.
            # Retain ownership until the actual reader task has terminated;
            # never turn an unconfirmed USB shutdown into an absent reader.
            if room_task.done():
                self._room_task = None
        await step("Pet observer", self.pet.close, _RUNTIME_PET_STOP_TIMEOUT_S)
        camera = getattr(self, "multimodal", None)
        if camera is not None:
            await step("Camera orchestration", camera.close, 3.0)
        await step("Conversation", self.conversation.stop, 3.0)
        await step("Mac HTTP client", self.client.aclose, 3.0)
        if errors:
            raise errors[0]
