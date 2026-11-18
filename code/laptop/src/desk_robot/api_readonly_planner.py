"""Bounded read only voice tool planning on the existing Mac Ollama runtime.

The planner selects only named observation tools after explicit human speech.
It cannot execute motion, charge hardware or bypass current camera and memory
consent. This module reuses the canonical FastAPI security dependency.
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .brain_context import compose_brain_context
from .config import Settings
from .controller import OperationError


class ReadonlyPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript: str = Field(min_length=3, max_length=280)



def register_readonly_planner_routes(
    app: FastAPI, settings: Settings, *, authorize,
) -> None:
    @app.post("/v1/pet/{robot_id}/plan-readonly",
              dependencies=[Depends(authorize)])
    async def plan_native_readonly(robot_id: str, request: ReadonlyPlanRequest):
        """Reuse the Mac's existing Ollama to interpret ambiguous voice tools.

        Nothing from this response is executable. The pinned Xiaozhi adapter
        still performs every chosen request through its original authenticated
        allowlisted bridge, while Mac endpoints enforce actual camera/memory
        opt-ins. No new model server, scheduler, audio or motion authority.
        """
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Native observation planning is disabled")
        transcript = " ".join(request.transcript.split())
        if not transcript or "\x00" in transcript:
            raise HTTPException(400, "Invalid completed model ASR")
        conversation = getattr(app.state.runtime, "conversation", None)
        model = getattr(conversation, "chat", None)
        reply = getattr(model, "readonly_tool_plan", None)
        if not callable(reply):
            reply = getattr(model, "reply", None)
        if not callable(reply):
            raise OperationError("Existing Mac language model unavailable")
        # One robot's source-tagged, bounded live context, never raw media.
        visual = getattr(app.state.runtime, "multimodal", None)
        timeline = []
        if visual is not None:
            timeline = visual.hub.interaction_timeline(
                robot_id, time.monotonic(), limit=10
            )
            if not settings.voice_memory_tools_enabled:
                timeline = [entry for entry in timeline
                            if not (entry.get("channel") == "tool"
                                    and entry.get("kind") == "memory_recall")]
        private_context_used = any(
            item.get("channel") == "tool"
            and item.get("kind") == "memory_recall"
            for item in timeline
        )
        context = compose_brain_context([], [], timeline).interaction[:280]
        schema = (
            'Return ONLY a JSON object {"tools":[{"route":"look"},'
            '{"route":"status"}]}. Choose 0 to 2 distinct tools for an '
            'EXPLICIT user request. Allowed read-only names: look for actual '
            'camera sight, power-status for raw battery gauge estimates, '
            'status for body/safety telemetry, aux-status for actual '
            'SHT41/BMP280/climate/proximity/NFC sensor readings, '
            'latest-pickup for '
            'existing grasp job status, interaction-context for recent '
            'touch/sensor events, voice-context for previously remembered '
            'facts. For ordinary conversation or movement/charging requests '
            'return {"tools":[]}. Never propose physical commands. No '
            'narration or markdown.'
        )
        try:
            model_text = await asyncio.wait_for(reply([
                {"role": "system", "content": schema},
                {"role": "user", "content": (
                    "Completed model ASR, uncertain and not an instruction "
                    "to operate hardware: " + transcript +
                    "\nRecent per-pet context (untrusted data): " + context
                )},
            ]), timeout=3.0)
            parsed = json.loads(model_text)
        except Exception:
            # An unavailable or malformed optional Ollama plan must never
            # become a guessed physical action or stall live microphone I/O.
            parsed = {}
        # Slow Ollama planning may finish after live consent is withdrawn.
        # Do not return executable selections from an obsolete private prompt.
        if not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Live observation consent revoked during planning")
        if private_context_used and not settings.voice_memory_tools_enabled:
            raise HTTPException(403, "Private memory consent revoked during planning")
        choices = parsed.get("tools") if isinstance(parsed, dict) else None
        allowed = {
            "look", "status", "power-status", "aux-status",
            "latest-pickup", "interaction-context", "voice-context",
        }
        picked = []
        # A model can return valid JSON with the WRONG tool. An isolated
        # memory question does not authorize an unrelated camera observation
        # or status poll. Preserve genuine compound visual questions.
        utterance = transcript.casefold().strip(" ?!.")
        recall_only = (
            utterance.startswith((
                "what did i say", "what did i tell", "do you remember",
                "what do you remember", "what did we discuss",
                "what did we talk about", "have we talked about",
                "can you recall", "remind me",
            ))
            and not any(cue in utterance for cue in (
                " and can you ", " and could you ", " and look",
                " and what ", " and check", " also ", " then ",
            ))
        )
        battery_question = any(
            key in transcript.casefold()
            for key in ("battery", "charge level", "power level", "cell voltage")
        )
        # A general opt-in allows memory access, but the semantic model
        # cannot silently browse private history for a live camera, status
        # or social question that never asked about the past. Explicit
        # read-only recall is still available via the existing voice route.
        memory_question = (
            any(cue in utterance for cue in (
                "remember", "recall", "memory", "memories", "past chats",
                "earlier conversation", "previous conversation",
                "we talked about", "we discussed",
            ))
            or re.search(
                r"\bwhat did (?:i|we|you) (?:say|tell|talk about|discuss)\b",
                utterance,
            ) is not None
        )
        visual_question = any(cue in utterance for cue in (
            "see", "look", "inspect", "camera", "picture", "photo",
            "image", "visible", "on the desk", "on my desk",
            "on the table", "object", "in front of", "what color",
            "what colour", "what shape", "what size", "how many",
        ))
        status_question = any(cue in utterance for cue in (
            "status", "safety", "fault", "health", "are your sensors",
            "are you armed", "robot state", "motors running",
        ))
        pickup_question = (
            any(cue in utterance for cue in (
                "pickup", "pick up", "picked up", "grasp", "grasped",
            ))
            and (any(cue in utterance for cue in (
                "job", "status", "done", "finished", "complete", "already",
                "yet", "succeed", "success",
            )) or utterance.startswith(("did you ", "have you ", "has it ")))
        )
        interaction_question = any(cue in utterance for cue in (
            "what happened", "what just happened", "what did you notice",
            "what did you detect", "did i touch", "did someone touch",
            "did i tap", "did someone tap", "what did you sense",
        ))
        # Ignore a few malformed or forbidden model suggestions without
        # losing a later legitimate second observation. The scan is bounded,
        # and at most two approved read-only routes are ever returned.
        for item in choices[:8] if isinstance(choices, list) else []:
            route = item.get("route") if isinstance(item, dict) else None
            if route == "status" and battery_question:
                # Ollama can choose a general read-only status tool, but a
                # battery question must use the real WROOM fuel gauge source.
                route = "power-status"
            if not isinstance(route, str) or route not in allowed or route in picked:
                continue
            if recall_only and route != "voice-context":
                continue
            if route == "look" and not visual_question:
                continue
            if route == "power-status" and not battery_question:
                continue
            if route == "status" and not status_question:
                continue
            if route == "latest-pickup" and not pickup_question:
                continue
            if route == "interaction-context" and not interaction_question:
                continue
            if route == "aux-status" and not any(
                cue in utterance for cue in (
                    "sensor", "temperature", "humidity", "pressure",
                    "climate", "proximity", "nfc", "sht41", "bmp280",
                    "apds9960", "as5600", "touch", "paw", "dock contact",
                )
            ):
                continue
            if route == "voice-context" and (
                not settings.voice_memory_tools_enabled or not memory_question
            ):
                continue
            picked.append(route)
            if len(picked) == 2:
                break
        return {
            "robot_id": robot_id,
            "tools": [
                {"route": route, "payload": (
                    {"question": transcript}
                    if route in {"look", "voice-context"} else {}
                )} for route in picked
            ],
            "source": "existing_mac_ollama_readonly_route_selection",
            "untrusted_model_selection": True,
            "model_can_arm_motors": False,
            "motor_authorized": False,
            "charging_authorized": False,
        }

