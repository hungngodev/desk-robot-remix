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

from .brain_context import compose_brain_context, is_camera_derived_timeline_item
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
        if settings.mode != "hardware":
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
        # Bind Ollama's optional route selection to the human turn that
        # requested it. Consent alone does not keep an old model plan current
        # after a new authenticated VAD, including speech on another pet.
        turn_epochs = getattr(visual, "_turn_epoch", None)
        turn_at_request = (
            turn_epochs.get(robot_id) if isinstance(turn_epochs, dict)
            else None
        )
        timeline = []
        if visual is not None:
            timeline = visual.hub.interaction_timeline(
                robot_id, time.monotonic(), limit=10
            )
            if not settings.voice_vision_tools_enabled:
                timeline = [
                    entry for entry in timeline
                    if not is_camera_derived_timeline_item(entry)
                ]
            if not settings.voice_memory_tools_enabled:
                timeline = [entry for entry in timeline
                            if not (entry.get("channel") == "tool"
                                    and entry.get("kind") == "memory_recall")]
            if not settings.room_station_context_enabled:
                timeline = [
                    entry for entry in timeline
                    if entry.get("channel") != "room_station"
                ]
        camera_context_used = any(
            is_camera_derived_timeline_item(item) for item in timeline
        )
        camera_consent_generation = settings.camera_consent_generation
        camera_granted_at_request = settings.voice_vision_tools_enabled
        room_context_used = any(
            item.get("channel") == "room_station" for item in timeline
        )
        room_consent_generation = settings.room_station_consent_generation
        private_context_used = any(
            item.get("channel") == "tool"
            and item.get("kind") == "memory_recall"
            for item in timeline
        )
        memory_granted_at_request = settings.voice_memory_tools_enabled
        memory_consent_generation = settings.voice_memory_consent_generation
        context = compose_brain_context([], [], timeline).interaction[:280]
        schema = (
            'Return ONLY a JSON object {"tools":[{"route":"look"},'
            '{"route":"status"}]}. Choose 0 to 3 distinct tools for an '
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
        if (type(turn_at_request) is int
                and (getattr(app.state.runtime, "multimodal", None) is not visual
                     or not isinstance(getattr(visual, "_turn_epoch", None), dict)
                     or visual._turn_epoch.get(robot_id) != turn_at_request)):
            raise HTTPException(409, "Read-only plan superseded by a newer human turn")
        # Slow Ollama planning may finish after live consent is withdrawn.
        # Do not return executable selections from an obsolete private prompt.
        if camera_context_used and not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Live observation consent revoked during planning")
        if (camera_context_used
                and settings.camera_consent_generation != camera_consent_generation):
            raise HTTPException(409, "Live observation grant changed during planning")
        if private_context_used and not settings.voice_memory_tools_enabled:
            raise HTTPException(403, "Private memory consent revoked during planning")
        if (private_context_used
                and settings.voice_memory_consent_generation != memory_consent_generation):
            raise HTTPException(409, "Private memory grant changed during planning")
        if room_context_used and not settings.room_station_context_enabled:
            raise HTTPException(403, "Room station consent revoked during planning")
        if (room_context_used
                and settings.room_station_consent_generation != room_consent_generation):
            raise HTTPException(409, "Room station grant changed during planning")
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
        # A noun in a casual statement is not permission for a model-selected
        # fuel-gauge read. Permit a question/imperative about a battery, plus
        # a short coordinated noun phrase ("inspect the desk and battery").
        # Never turn a historical recall question about a battery into a
        # request for its CURRENT WROOM battery telemetry.
        clauses = [
            piece.strip() for piece in re.split(
                r",|\b(?:and|then|also)\b", utterance
            ) if piece.strip()
        ]
        request_intro = re.compile(
            r"^(?:(?:hey [a-z]+[, ]+|please )*)"
            r"(?:what|where|how|can|could|would|do|does|did|is|are|"
            r"check|show|tell me|report|read|inspect|look|give me)\b"
        )
        recall_intro = re.compile(
            r"^(?:what did (?:i|we|you) (?:say|tell|talk|discuss)|"
            r"what do you remember|do you remember|can you recall|"
            r"tell me what (?:i|we|you) (?:said|told)|remind me)\b"
        )
        is_request = [
            bool(request_intro.match(piece) and not recall_intro.match(piece))
            for piece in clauses
        ]
        battery_cue = re.compile(
            r"\b(?:battery|charge level|power level|cell voltage)\b"
        )
        short_battery_clause = re.compile(
            r"^(?:(?:my|your|the|a|this) )?"
            r"(?:battery(?: level| status| charge| percentage| percent)?|"
            r"charge level|power level|cell voltage)\??$"
        )
        battery_question = any(
            bool(battery_cue.search(piece) and is_request[i])
            or bool(i > 0 and any(is_request[:i])
                    and short_battery_clause.fullmatch(piece))
            for i, piece in enumerate(clauses)
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
        # Memory opt-in alone is not a per-request retrieval instruction.
        # A person sharing a story containing "remember" or "memory" must
        # not cause an overeager model to open their private history.
        # Recognize explicit recall questions in compound requests as well.
        if memory_question:
            memory_question = any(
                re.match(
                    r"^(?:hey [a-z]+[, ]+|please )*"
                    r"(?:what (?:do you remember|did (?:i|you|we) "
                    r"(?:say|tell|talk|discuss))|"
                    r"do you (?:remember|recall)|"
                    r"(?:can|could|would) you (?:remember|recall|remind me)|"
                    r"tell me (?:what you remember|about (?:our|my|the) "
                    r"(?:earlier|previous|past) (?:conversation|chat|memory))|"
                    r"remind me|did we (?:talk|discuss)|"
                    r"have we (?:talked|discussed)|recall (?:what|our|my))\b",
                    piece.strip(),
                ) is not None
                for piece in re.split(r"\b(?:and|then|also)\b", utterance)
            )
        # A model-selected camera route needs an EXPLICIT human observation
        # request. Substring-only checks interpreted ordinary "see you later"
        # and "I left a photo on the desk" as permission to look. Keep
        # genuine questions, imperatives and compound camera/battery requests.
        # A natural request may follow a statement in the same ASR turn.
        # Require the observation verb and visual subject in ONE clause;
        # otherwise "I showed a photo, and check your battery" would grant
        # a camera call based on the unrelated preceding photo mention.
        visual_question = False
        for clause in re.split(r",|\b(?:and|then|also)\b", utterance):
            piece = clause.strip()
            if (re.match(
                r"^(?:(?:hey [a-z]+[, ]+|please )*)"
                r"(?:what|where|how|can|could|would|do|does|did|is|are|"
                r"look|inspect|show|describe|count|check|tell me|"
                r"take a look|see if|see whether)\b", piece,
            ) is None or re.match(
                r"^(?:please )?look forward\b", piece
            ) is not None):
                continue
            if any(
                re.search(r"\b" + re.escape(cue) + r"\b", piece)
                for cue in (
                    "see", "look", "inspect", "camera", "picture", "photo",
                    "image", "visible", "on the desk", "on my desk",
                    "on the table", "object", "in front of",
                )
            ) or re.search(
                # A bare quantifier has no visual subject. "How many days
                # until my exam?" is not permission to capture a frame.
                # Deictic requests do point at something in the scene.
                r"\b(?:what (?:colou?r|shape|size) is|how many of) "
                r"(?:this|that|these|those)\b", piece,
            ):
                visual_question = True
                break
        # A camera request may contain no prior camera evidence. The grant
        # that existed before waiting for Ollama still owns any new look:
        # revoking and regranting consent cannot revive the stale plan.
        if (visual_question and isinstance(choices, list) and any(
            isinstance(item, dict) and item.get("route") == "look"
            for item in choices[:8]
        )):
            if camera_granted_at_request and not settings.voice_vision_tools_enabled:
                raise HTTPException(403, "Live observation consent revoked during planning")
            if (camera_granted_at_request != settings.voice_vision_tools_enabled
                    or settings.camera_consent_generation != camera_consent_generation):
                raise HTTPException(409, "Live observation grant changed during planning")
        # A background status or auxiliary poll requires the same actual
        # human question/imperative as vision and fuel telemetry. Do not
        # let an overeager planner turn "my sensors were broken yesterday"
        # into a new live query. Coordinated short clauses remain requests.
        def explicitly_requested(cues: tuple[str, ...],
                                 elliptical: re.Pattern[str]) -> bool:
            return any(
                bool(is_request[i] and any(
                    re.search(r"\b" + re.escape(cue) + r"\b", piece)
                    for cue in cues
                ))
                or bool(i > 0 and any(is_request[:i])
                        and elliptical.fullmatch(piece))
                for i, piece in enumerate(clauses)
            )

        status_question = explicitly_requested(
            ("safety", "fault", "health", "are your sensors working",
             "are you armed", "robot state", "motors running"),
            re.compile(
                r"^(?:(?:your|my|the) )?"
                r"(?:status|safety|safety status|sensor status|"
                r"robot status|faults?|health)\??$"
            ),
        ) or any(
            # 'Check my battery status' asks only for the fuel gauge. The
            # generic word 'status' is not a second body safety request
            # when it modifies battery in the SAME clause.
            is_request[i] and re.search(r"\bstatus\b", piece)
            and battery_cue.search(piece) is None
            for i, piece in enumerate(clauses)
        )
        aux_question = explicitly_requested(
            ("sensor", "sensors", "temperature", "humidity", "pressure", "climate",
             "proximity", "nfc", "sht41", "bmp280", "apds9960", "as5600",
             "touch", "paw", "dock contact"),
            re.compile(
                r"^(?:(?:your|my|the) )?"
                r"(?:sensors?|sensor readings?|temperature|humidity|"
                r"pressure|climate|proximity|nfc|touch|paw|"
                r"dock contacts?)\??$"
            ),
        )
        # Model-selected history is not permission to inspect a pet's recent
        # actions merely because somebody mentions picking up an object or
        # a film titled "What Happened". The cue must be part of the same
        # explicit human request clause, not an unrelated anecdote.
        pickup_verb = re.compile(
            r"\b(?:pick(?:ed|ing)? up|pickup|grasp(?:ed|ing)?)\b"
        )
        pickup_result = re.compile(
            r"\b(?:job|status|done|finish(?:ed)?|complete(?:d)?|"
            r"already|yet|succeed(?:ed)?|success|whether|if)\b"
        )
        pickup_question = any(
            bool(
                (is_request[i] or re.match(r"^(?:have|has)\b", piece))
                and pickup_verb.search(piece)
                and (pickup_result.search(piece)
                     or re.match(r"^(?:did|have|has)\b", piece))
            )
            for i, piece in enumerate(clauses)
        )
        interaction_request = re.compile(
            r"^(?:(?:hey [a-z]+[, ]+|please )*)"
            r"(?:what (?:just )?happened|"
            r"what did (?:you|i|someone) (?:notice|detect|sense|touch|tap)|"
            r"did (?:i|someone) (?:touch|tap)|"
            r"(?:can|could|would) you tell me what (?:just )?happened|"
            r"tell me what (?:just )?happened)\b"
        )
        interaction_question = any(
            interaction_request.match(piece) is not None for piece in clauses
        )
        # Ignore a few malformed or forbidden model suggestions without
        # losing later legitimate observations. The scan is bounded,
        # and at most three approved read-only routes are ever returned.
        for item in choices[:8] if isinstance(choices, list) else []:
            route = item.get("route") if isinstance(item, dict) else None
            if route == "status" and battery_question and not status_question:
                # Ollama can choose a general read-only status tool, but a
                # battery question must use the real WROOM fuel gauge source.
                route = "power-status"
            if not isinstance(route, str) or route not in allowed or route in picked:
                continue
            if recall_only and route != "voice-context":
                continue
            if route == "look" and (
                not settings.voice_vision_tools_enabled or not visual_question
            ):
                continue
            if route == "power-status" and not battery_question:
                continue
            if route == "status" and not status_question:
                continue
            if route == "latest-pickup" and not pickup_question:
                continue
            if route == "interaction-context" and not interaction_question:
                continue
            if route == "aux-status" and not aux_question:
                continue
            if route == "voice-context" and (
                not memory_granted_at_request
                or not settings.voice_memory_tools_enabled
                or settings.voice_memory_consent_generation != memory_consent_generation
                or not memory_question
            ):
                continue
            picked.append(route)
            if len(picked) == 3:
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

