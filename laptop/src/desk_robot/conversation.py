from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from typing import Protocol

import httpx

from .config import RobotConfig, Settings, secret


class Chat(Protocol):
    async def reply(self, history: list[dict]) -> str: ...


class Speaker(Protocol):
    def session(self, robots: list[RobotConfig]): ...
    async def say(self, robot: RobotConfig, text: str): ...


class OllamaChat:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def reply(self, history: list[dict]) -> str:
        response = await self.client.post(
            self.settings.ollama_url.rstrip("/") + "/api/chat",
            json={
                "model": self.settings.ollama_model,
                "messages": history,
                "stream": False,
                "think": False,
                "options": {"num_predict": 100},
            },
            timeout=60,
        )
        response.raise_for_status()
        text = response.json()["message"]["content"].strip()
        if not text or len(text) > 2000:
            raise RuntimeError("Ollama returned empty or oversized speech")
        return text


class KokoroHeadSpeaker:
    """Native Kokoro HTTP -> upstream Xiaozhi audio conversion -> the chosen physical head."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def _bridge(self, route: str, payload: dict):
        response = await self.client.post(
            self.settings.speech_bridge_url.rstrip("/") + route,
            headers={"Authorization": f"Bearer {secret(self.settings.speech_bridge_token_env)}"},
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        return response.json()

    @asynccontextmanager
    async def session(self, robots):
        ids = [r.device_id for r in robots]
        if not all(ids):
            raise RuntimeError(
                "Configure each robot's Xiaozhi device_id before physical conversation"
            )
        await self._bridge("/session", {"device_ids": ids, "enabled": True})
        try:
            yield
        finally:
            await self._bridge("/session", {"device_ids": ids, "enabled": False})

    async def say(self, robot: RobotConfig, text: str):
        response = await self.client.post(
            self.settings.kokoro_url.rstrip("/") + "/v1/audio/speech",
            json={
                "model": "kokoro",
                "input": text,
                "voice": robot.voice,
                "response_format": "wav",
                "speed": 1,
                "stream": False,
            },
            timeout=60,
        )
        response.raise_for_status()
        if not response.content.startswith(b"RIFF") or len(response.content) > 10_000_000:
            raise RuntimeError("Kokoro did not return bounded WAV audio")
        result = await self._bridge(
            "/speak",
            {
                "device_id": robot.device_id,
                "text": text,
                "wav_base64": base64.b64encode(response.content).decode(),
            },
        )
        if result.get("transmitted") is not True:
            raise RuntimeError("Speech transmission to head failed")


class Conversation:
    def __init__(self, settings: Settings, chat: Chat, speaker: Speaker):
        self.settings, self.chat, self.speaker = settings, chat, speaker
        self.speaker_lock = asyncio.Lock()
        self.active: asyncio.Task | None = None
        self.histories: dict[str, list[dict]] = {}

    async def run(self, robot_ids: list[str], topic: str, utterances: int = 6) -> list[dict]:
        if len(robot_ids) != 2 or len(set(robot_ids)) != 2 or not 1 <= utterances <= 6:
            raise ValueError("Choose two distinct robots and 1..6 total utterances")
        if self.active is not None and not self.active.done():
            raise RuntimeError("A conversation is already active")
        robots = [self.settings.robot(i) for i in robot_ids]
        self.active = asyncio.current_task()
        self.histories = {
            r.id: [
                {"role": "system", "content": r.persona},
                {"role": "user", "content": f"Discuss this with your robot peer: {topic}"},
            ]
            for r in robots
        }
        transcript = []
        try:
            async with asyncio.timeout(300):
                async with self.speaker.session(robots):
                    for index in range(utterances):
                        robot, peer = robots[index % 2], robots[(index + 1) % 2]
                        text = await self.chat.reply(list(self.histories[robot.id]))
                        async with self.speaker_lock:
                            await self.speaker.say(
                                robot, text
                            )  # await actual transmission + playback tail
                        self.histories[robot.id].append({"role": "assistant", "content": text})
                        self.histories[peer.id].append(
                            {"role": "user", "content": f"{robot.name} said: {text}"}
                        )
                        transcript.append({"robot_id": robot.id, "text": text})
            return transcript
        finally:
            self.active = None

    async def stop(self):
        if self.active and self.active is not asyncio.current_task():
            self.active.cancel()
            await asyncio.gather(self.active, return_exceptions=True)
