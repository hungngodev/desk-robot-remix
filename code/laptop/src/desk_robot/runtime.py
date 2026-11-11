from __future__ import annotations

import asyncio

import httpx

from .config import Settings, secret
from .controller import Coordinator
from .conversation import Conversation, KokoroHeadSpeaker, OllamaChat
from .live_voice_events import VoiceEventListener
from .memory import MemoryStore
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
        )
        self._voice_task = asyncio.create_task(self.voice_events.run())

    async def _on_voice_interrupt(self, robot_id: str, kind: str) -> None:
        await self.pet.interrupt(robot_id)
        # The same human speech also preempts any ongoing peer discussion.
        await self.conversation.stop()

    async def close(self):
        if self._voice_task is not None:
            self._voice_task.cancel()
            await asyncio.gather(self._voice_task, return_exceptions=True)
            self._voice_task = None
        await self.pet.close()
        await self.conversation.stop()
        await self.coordinator.close()
        await self.client.aclose()
