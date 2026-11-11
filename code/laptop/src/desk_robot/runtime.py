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
        self.voice_events: VoiceEventListener | None = None
        self._voice_task: asyncio.Task | None = None

    async def start(self):
        """Bridge Xiaozhi's real voice interruption into Mac speech cancellation."""
        if self.settings.mode != "hardware" or self._voice_task is not None:
            return
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
        )
        self._voice_task = asyncio.create_task(self.voice_events.run())

    async def _preempt_audio_floor(self) -> None:
        """Human and VAD transport failures share one five-pet audio owner."""
        results = await asyncio.gather(
            *(self.pet.interrupt(robot.id) for robot in self.settings.robots),
            return_exceptions=True,
        )
        # Stop the peer audio lease even if an individual pet callback fails.
        await self.conversation.stop()
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
            if not visual.hub.user_active(robot_id, now)
        ]
        if missing_starts:
            await self._preempt_audio_floor()
        visual.hub.reconcile_speech_snapshot(active, time.monotonic())

    async def _on_voice_monitor_ready(self, ready: bool) -> None:
        # Re-enable spontaneous voice only after a successful authenticated
        # event-stream bootstrap or ordered poll, never on a guessed timeout.
        self.pet.set_voice_monitor_ready(ready)

    async def _on_voice_global(self, reason: str) -> None:
        if reason not in ("gap", "reset", "stream_unavailable"):
            raise ValueError("Unsupported global voice transport fault")
        self.pet.set_voice_monitor_ready(False)
        await self._preempt_audio_floor()

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
        # Human speech cancels one shared five-pet speech floor once.
        await self._preempt_audio_floor()
        # VAD event is a signal, never a blocking image request. Schedule
        # camera sampling AFTER the urgent audio cancellation path.
        visual = getattr(self, "multimodal", None)
        if visual is not None:
            if kind == "speech_start":
                visual.voice_started(robot_id)
            elif kind in ("normal", "group"):
                # AEC barge-in can be real without an idle speech_end event;
                # never leave an indefinite speech-start visual lease for it.
                visual.voice_interrupted(robot_id)

    async def close(self):
        if self.settings.mode == "hardware":
            self.pet.set_voice_monitor_ready(False)
        if self._voice_task is not None:
            self._voice_task.cancel()
            await asyncio.gather(self._voice_task, return_exceptions=True)
            self._voice_task = None
        await self.pet.close()
        if self.multimodal is not None:
            await self.multimodal.close()
        await self.conversation.stop()
        await self.coordinator.close()
        await self.client.aclose()
