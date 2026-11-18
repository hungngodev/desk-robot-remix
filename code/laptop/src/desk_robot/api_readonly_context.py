"""Read-only pet battery and live situation routes for the existing Mac API.

Registration consumes the same operator/tool authorizer, human-turn epoch
and Mac pet speech policy as api.create_app. This is source organization,
not a second API or a new sensor, memory or motion owner.
"""
from __future__ import annotations

import time

from fastapi import Depends, FastAPI, HTTPException, Request

from .brain_context import compose_brain_context
from .config import Settings
from .controller import OperationError
from .transport import HeadError


def register_readonly_context_routes(
    app: FastAPI, settings: Settings, *, authorize, coordinator,
    requested_tool_context, remember_tool_context, native_pet_speech_policy,
) -> None:
    @app.get("/v1/pet/{robot_id}/power-status",
             dependencies=[Depends(authorize)])
    async def read_only_power_status(robot_id: str, request: Request):
        """Only validated actual WROOM AUX fuel-gauge readings, if present.

        Raw gauge estimates have no independently verified sample age or
        pack-current calibration. They NEVER certify charge, safe voltage,
        a working battery, battery capacity, or an actuator permit.
        """
        coordinator().robot(robot_id)
        if settings.mode != "hardware":
            raise HTTPException(403, "Only a real WROOM fuel gauge is reported")
        # Capture the exact Mac human epoch BEFORE slow WROOM HTTP. A new
        # voice turn during the read must not inherit this old fuel gauge.
        owner = requested_tool_context(request, robot_id)
        data = await coordinator().heads[robot_id].aux_status()
        if (not isinstance(data, dict)
                or data.get("robot_id") != robot_id
                or not isinstance(data.get("power"), dict)):
            raise HeadError("WROOM fuel-gauge robot identity mismatch")
        power = data["power"]
        # A valid flag with no independent completed MAX17048 acquisition
        # identity can be a stale/replayed optional telemetry payload.
        fuel_seq = power.get("fuel_seq")
        valid = (power.get("fuel_valid") is True
                 and type(fuel_seq) is int and 0 < fuel_seq <= 0xffffffff)
        cell = power.get("cell_mv")
        soc = power.get("soc_centi")
        if (valid and (type(cell) is not int or not 0 <= cell <= 4500
                       or type(soc) is not int or not 0 <= soc <= 10000)):
            raise OperationError("Malformed WROOM auxiliary fuel gauge values")
        result = {
            "robot_id": robot_id,
            "gauge_available": valid,
            "reported_cell_mv": cell if valid else None,
            "reported_soc_centi": soc if valid else None,
            "raw_fuel_acquisition_seq": fuel_seq if valid else None,
            "sample_freshness_verified": False,
            "charging_verified": False,
            "battery_capacity_verified": False,
            "motor_authorized": False,
            "charging_authorized": False,
            "source": "wroom_aux_fuel_gauge_raw_unqualified",
        }
        if valid:
            summary = (
                f"WROOM fuel gauge reports {soc / 100:.1f}% estimate and "
                f"{cell}mV; sample freshness and charging unverified"
            )
        else:
            summary = "WROOM fuel gauge unavailable; no verified charge or battery percentage"
        remember_tool_context(owner, robot_id, "robot_status", summary)
        return result

    @app.get("/v1/pet/{robot_id}/interaction-context",
             dependencies=[Depends(authorize)])
    async def pet_live_situation(robot_id: str):
        """Live context is distinct from durable history permission.

        A person may opt into present camera/sensor interaction without
        granting the model permission to inspect persistent SQLite memories.
        No raw JPEG/PCM, camera exposure claim or actuator permit is returned.
        """
        try:
            settings.robot(robot_id)
        except KeyError as exc:
            raise HTTPException(404, "Robot not found") from exc
        if not settings.voice_vision_tools_enabled:
            raise HTTPException(403, "Opt in to live camera/sensor context first")
        visual = getattr(app.state.runtime, "multimodal", None)
        if visual is None:
            raise OperationError("No current multimodal camera/sensor owner")
        now = time.monotonic()
        timeline = visual.hub.interaction_timeline(robot_id, now, limit=10)
        if not settings.voice_memory_tools_enabled:
            # Revoking memory consent also revokes the transient retrieval
            # result. A still-active camera permit is not permission to read
            # yesterday's private text through a native model prompt.
            timeline = [
                entry for entry in timeline
                if not (entry.get("channel") == "tool"
                        and entry.get("kind") == "memory_recall")
            ]
        # The native audio session receives a compact source-labeled text
        # summary through its existing authenticated Mac context endpoint.
        # Neither raw media nor historical SQLite memory enters this view.
        model_context = compose_brain_context([], [], timeline).interaction
        return {
            "robot_id": robot_id,
            "current_interaction_timeline": timeline,
            "model_context": model_context,
            "model_context_untrusted_not_instructions": True,
            **native_pet_speech_policy(robot_id),
            # Live revocation of model-private memory access must also
            # invalidate an older native startup persona containing facts.
            "memory_tools_enabled": settings.voice_memory_tools_enabled,
            "transcript_memory_enabled": settings.voice_transcript_memory_enabled,
            "persistent_memory_included": False,
            "raw_media_included": False,
            "source_exposure_timestamp_verified": False,
            "motor_authorized": False,
            "charging_authorized": False,
        }

