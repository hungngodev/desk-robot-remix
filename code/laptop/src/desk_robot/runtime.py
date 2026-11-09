from __future__ import annotations

import httpx

from .config import Settings
from .memory import MemoryStore
from .controller import Coordinator
from .conversation import Conversation, KokoroHeadSpeaker, OllamaChat
from .simulator import SimulatedChat, SimulatedHead, SimulatedSpeaker, SimulationVision
from .transport import HttpHead
from .vision import YoloWorldVision


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient()
        if settings.mode == "simulation":
            heads = {r.id: SimulatedHead(r.id) for r in settings.robots}
            vision, chat, speaker = SimulationVision(), SimulatedChat(), SimulatedSpeaker()
        else:
            heads = {r.id: HttpHead(r, self.client) for r in settings.robots}
            vision = YoloWorldVision(settings.vision_weights)
            chat = OllamaChat(settings, self.client)
            speaker = KokoroHeadSpeaker(settings, self.client)
        self.memory = MemoryStore(settings.memory_dir, [r.id for r in settings.robots])
        self.coordinator = Coordinator(settings, heads, vision)
        self.conversation = Conversation(settings, chat, speaker, memory=self.memory)

    async def close(self):
        await self.conversation.stop()
        await self.coordinator.close()
        await self.client.aclose()
