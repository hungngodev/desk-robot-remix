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
from .simulator import (
    SimulatedChat,
    SimulatedHead,
    SimulatedScene,
    SimulatedSpeaker,
    SimulationVision,
)
from .transport import HttpHead
from .vision import OllamaScene, YoloWorldVision


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

    async def start(self):
        """Bridge Xiaozhi's real voice interruption into Mac speech cancellation."""
        if self.settings.mode != "hardware" or self._voice_task is not None:
            return
        # Visual consent enables a persistent feed independently of voice
        # activity or pet autostart. One Mac stream consumer per real head.
        # The pet still needs its separate opt-in to speak proactively.
        if self.multimodal is not None:
            self.multimodal.start_streams()
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
        if missing_starts:
            prepare = getattr(visual, "prepare_human_turn", None)
            # Mark authenticated VAD NOW. A slow Xiaozhi STOP cannot keep
            # old camera or VLM activity alive during speaker teardown.
            if callable(prepare):
                for robot_id in sorted(missing_starts):
                    prepare(robot_id, end_expected=True)
            await self._preempt_audio_floor()
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

    async def _on_voice_monitor_ready(self, ready: bool) -> None:
        # Re-enable spontaneous voice only after a successful authenticated
        # event-stream bootstrap or ordered poll, never on a guessed timeout.
        self.pet.set_voice_monitor_ready(ready)

    async def _on_voice_global(self, reason: str) -> None:
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
            [asyncio.wait_for(stop(robot), timeout=0.35)
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
        # Human speech cancels one shared five-pet speech floor once.
        await self._preempt_audio_floor()
        # Only after the urgent speaker cleanup may the optional JPEG
        # sampler start. Preserve smaller test adapters' prior interface.
        if visual is not None:
            if callable(prepare):
                if kind in ("speech_start", "normal", "group"):
                    visual.start_speech_frames(robot_id)
            elif kind == "speech_start":
                visual.voice_started(robot_id)
            elif kind in ("normal", "group"):
                visual.voice_interrupted(robot_id)

    async def close(self):
        if self.settings.mode == "hardware":
            self.pet.set_voice_monitor_ready(False)
        # Keep network resource cleanup unconditional even if a stuck voice
        # owner reports an unconfirmed shutdown after physical STOP.
        try:
            # Never wait for voice/model teardown before physical STOP.
            await self.coordinator.close()
            if self._voice_task is not None:
                self._voice_task.cancel()
                await asyncio.gather(self._voice_task, return_exceptions=True)
                self._voice_task = None
            await self.pet.close()
            if self.multimodal is not None:
                await self.multimodal.close()
            await self.conversation.stop()
        finally:
            await self.client.aclose()
