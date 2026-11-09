"""Real opt-in proactive camera sessions for the existing Mac/Xiaozhi fleet.

All observation sources are actual head snapshots. Two stable changed frames and
a configured local multimodal Ollama model must agree before an unsolicited
utterance is considered. The scheduler owns only observation and speech, never
robot motion. Vision inferences can be wrong and need real-camera evaluation.

Built on the pinned Xiaozhi server/head transport, Ollama's multimodal chat API,
existing Conversation speaker lease, and local per-robot SQLite persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from .config import Settings
from .conversation import Conversation
from .memory import PetMemory
from .transport import Head


class SceneObserver(Protocol):
    async def observe_change(self, before: bytes, after: bytes) -> dict | None: ...


def _thumbnail(jpeg: bytes) -> bytes:
    if not jpeg.startswith(b"\xff\xd8") or len(jpeg) > 512_000:
        raise ValueError("Expected a bounded camera JPEG")
    with Image.open(io.BytesIO(jpeg)) as im:
        if im.width < 24 or im.height < 18:
            raise ValueError("Camera image resolution unexpectedly small")
        return im.convert("L").resize((24, 18)).tobytes()


def _distance(a: bytes, b: bytes) -> float:
    if len(a) != len(b):
        raise ValueError("Mismatched image grids")
    return sum(abs(x - y) for x, y in zip(a, b)) / (len(a) * 255)


@dataclass
class PetState:
    enabled: bool = False
    quiet: bool = False
    generation: int = 0
    baseline: bytes | None = None
    baseline_thumb: bytes | None = None
    candidate: bytes | None = None
    candidate_thumb: bytes | None = None
    last_observed: float | None = None
    last_event: str | None = None
    last_spoken: str | None = None
    last_error: str | None = None


class PetRuntime:
    """One capture task per robot and one global audio lease for five peers.

    There is no auto-enable after reboot, client reconnect or motion fault.
    Quiet mode cancels pending spontaneous work, not user-requested speech.
    """

    def __init__(
        self,
        settings: Settings,
        heads: dict[str, Head],
        observer: SceneObserver,
        conversation: Conversation,
        memory: PetMemory,
    ):
        self.settings = settings
        self.heads = heads
        self.observer = observer
        self.conversation = conversation
        self.memory = memory
        self.states = {r.id: PetState() for r in settings.robots}
        self.tasks: dict[str, asyncio.Task] = {}
        self.floor = asyncio.Lock()
        self.last_group_speech = -math.inf
        self.recent_group_events: dict[str, float] = {}
        self.closed = False

    def status(self, robot_id: str) -> dict:
        state = self.states[robot_id]
        return {
            "robot_id": robot_id,
            "enabled": state.enabled,
            "quiet": state.quiet,
            "last_event": state.last_event,
            "last_spoken": state.last_spoken,
            "last_error": state.last_error,
            "memories": len(self.memory.recent(robot_id, 20)),
            "physical_conversation_verified": False,
            "motion_permission": False,
        }

    async def start(self, robot_id: str):
        if robot_id not in self.states:
            raise ValueError("Unknown robot")
        if not self.settings.ollama_vision_model and self.settings.mode != "simulation":
            raise ValueError("Set a locally installed ollama_vision_model before enabling")
        if self.closed:
            raise RuntimeError("Pet controller is closed")
        state = self.states[robot_id]
        if state.enabled:
            return self.status(robot_id)
        state.enabled = True
        state.generation += 1
        state.baseline = state.baseline_thumb = None
        state.candidate = state.candidate_thumb = None
        state.last_error = None
        self.tasks[robot_id] = asyncio.create_task(self._run(robot_id))
        return self.status(robot_id)

    async def pause(self, robot_id: str):
        if robot_id not in self.states:
            raise ValueError("Unknown robot")
        state = self.states[robot_id]
        state.enabled = False
        state.generation += 1
        task = self.tasks.pop(robot_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.status(robot_id)

    async def quiet(self, robot_id: str, enabled: bool):
        if robot_id not in self.states:
            raise ValueError("Unknown robot")
        state = self.states[robot_id]
        if state.quiet != enabled:
            state.quiet = enabled
            state.generation += 1
            # Cancel any current spontaneous speech and its session; preserve
            # enabled observation by restarting with a new generation.
            task = self.tasks.pop(robot_id, None)
            if task and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if state.enabled:
                self.tasks[robot_id] = asyncio.create_task(self._run(robot_id))
        return self.status(robot_id)

    async def _run(self, robot_id: str):
        state = self.states[robot_id]
        try:
            while state.enabled and not self.closed:
                try:
                    await self.observe_once(robot_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Error remains visible to operator; never substitute
                    # synthetic scene claims or automatically move on failure.
                    state.last_error = f"{type(exc).__name__}: {exc}"[:240]
                await asyncio.sleep(self.settings.pet_poll_seconds)
        finally:
            state.candidate = state.candidate_thumb = None

    async def observe_once(self, robot_id: str):
        """One real snapshot, possible visual event and fully serialized speech."""
        state = self.states[robot_id]
        generation = state.generation
        if not state.enabled or self.closed:
            return None
        captured = await self.heads[robot_id].snapshot()
        # This is Mac receive time, NOT a device camera exposure timestamp.
        received = time.monotonic()
        thumbnail = _thumbnail(captured)
        state.last_observed = received
        if state.generation != generation or not state.enabled:
            return None
        if state.baseline is None:
            state.baseline = captured
            state.baseline_thumb = thumbnail
            return None
        if _distance(state.baseline_thumb, thumbnail) < 0.095:
            state.candidate = state.candidate_thumb = None
            return None
        if state.candidate is None:
            state.candidate = captured
            state.candidate_thumb = thumbnail
            return None
        if _distance(state.candidate_thumb, thumbnail) >= 0.065:
            state.candidate = captured
            state.candidate_thumb = thumbnail
            return None
        previous = state.baseline
        state.baseline = captured
        state.baseline_thumb = thumbnail
        state.candidate = state.candidate_thumb = None
        # No inference is ever allowed to grant motion permission.
        observation = await self.observer.observe_change(previous, captured)
        if state.generation != generation or not state.enabled or observation is None:
            return None
        if time.monotonic() - received > 10:
            # Model result is old. Do not claim the scene is still present.
            return None
        kind, summary = observation["kind"], observation["summary"]
        event_key = hashlib.sha256(
            f"{kind}:{summary.casefold().strip()}".encode("utf-8")
        ).hexdigest()
        event_id = uuid.uuid4().hex
        self.memory.remember(
            robot_id,
            event_id=event_id,
            observed_by=robot_id,
            kind=kind,
            summary=summary,
            captured_at=time.time(),
            source="camera",
        )
        state.last_event = summary
        if state.quiet:
            return {"observed": summary, "spoken": False, "reason": "quiet"}
        async with self.floor:
            now = time.monotonic()
            for key, timestamp in list(self.recent_group_events.items()):
                if now - timestamp > 5:
                    del self.recent_group_events[key]
            if event_key in self.recent_group_events:
                return {"observed": summary, "spoken": False, "reason": "fleet_duplicate"}
            if now - self.last_group_speech < self.settings.pet_spontaneous_gap_seconds:
                return {"observed": summary, "spoken": False, "reason": "group_cooldown"}
            if self.conversation.active and not self.conversation.active.done():
                return {"observed": summary, "spoken": False, "reason": "conversation_busy"}
            if state.generation != generation or state.quiet or not state.enabled:
                return None
            self.recent_group_events[event_key] = now
            # The group cooldown starts when the floor is granted, including
            # a failure, to avoid retry floods from simultaneous cameras.
            self.last_group_speech = now
            prompt = (
                f"You directly observed: {summary}. React only if this is useful. "
                "Say one short, accurate, natural sentence to the owner. "
                "Do not imply you measured distances, identities or emotions."
            )
            result = await self.conversation.say_one(
                robot_id, prompt, self.memory.context(robot_id)
            )
            if state.generation != generation or state.quiet or not state.enabled:
                return None
            state.last_spoken = result
            return {"observed": summary, "spoken": True, "text": result}

    def share_with_peer(self, *, from_robot: str, to_robot: str, event_id: str) -> bool:
        """Digital hearsay with original witness; never copies into direct memory."""
        source = next(
            (r for r in self.memory.recent(from_robot, 20) if r["event_id"] == event_id), None
        )
        if source is None:
            raise ValueError("Unknown or expired source event")
        if to_robot == from_robot:
            return False
        return self.memory.remember(
            to_robot,
            event_id=f"shared:{from_robot}:{event_id}",
            observed_by=source["observed_by"],
            told_by=from_robot,
            kind=source["kind"],
            summary=source["summary"],
            captured_at=source["captured_at"],
            source="peer",
        )

    async def close(self):
        self.closed = True
        await asyncio.gather(*(self.pause(x) for x in self.states), return_exceptions=True)
        self.memory.close()
