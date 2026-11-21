"""Source preserving robot inventory and raw telemetry API route group.

These routes keep existing shared authorization and the exact human turn
receipt handoff. Robot telemetry is read only, never motion authority.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request

from .config import Settings
from .transport import HeadError


def register_robot_status_routes(
    app: FastAPI, settings: Settings, *, authorize, coordinator,
    requested_tool_context, remember_tool_context,
) -> None:
    @app.get("/v1/robots", dependencies=[Depends(authorize)])
    async def robots():
        return {
            "mode": settings.mode,
            "physical_acceptance_pass": False,
            "robots": [
                {"id": r.id, "name": r.name, "motion_enabled": r.motion_enabled}
                for r in settings.robots
            ],
        }

    @app.get("/v1/robots/{robot_id}/status", dependencies=[Depends(authorize)])
    async def status(robot_id: str, request: Request):
        coordinator().robot(robot_id)
        context = requested_tool_context(request, robot_id)
        data = await coordinator().heads[robot_id].status()
        if not isinstance(data, dict) or data.get("robot_id") != robot_id:
            raise HeadError("Head status robot identity mismatch")
        if isinstance(data, dict):
            safety = data.get("safety")
            safety = safety if isinstance(safety, dict) else {}
            summary = (
                f"backend={str(data.get('backend', 'unknown'))[:24]}, "
                f"armed={data.get('armed')}, "
                f"safety_fault={str(safety.get('fault', 'unknown'))[:40]}"
            )
            remember_tool_context(context, robot_id, "robot_status", summary)
        return data

    @app.get("/v1/robots/{robot_id}/aux", dependencies=[Depends(authorize)])
    async def aux(robot_id: str, request: Request):
        coordinator().robot(robot_id)
        # Bind the requesting human turn before slow physical telemetry.
        # A new VAD epoch must not inherit the older tool's receipt.
        owner = requested_tool_context(request, robot_id)
        getter = getattr(coordinator().heads[robot_id], "aux_status", None)
        if not callable(getter):
            return {"robot_id": robot_id, "available": False,
                    "reason": "No physical accessory telemetry adapter"}
        data = await getter()
        if not isinstance(data, dict) or data.get("robot_id") != robot_id:
            raise HeadError("Auxiliary telemetry robot identity mismatch")
        # Only an authenticated, explicit head tool request may add a short
        # physical sensor receipt to the shared multimodal brain timeline.
        # Dashboard polling and failed/invalid measurements never inject it.
        if owner is not None:
            cues = []
            climate = data.get("climate")
            if isinstance(climate, dict) and climate.get("valid") is True:
                cues.append(
                    "SHT41 local temp_centi="
                    + str(climate.get("temp_centi"))[:8]
                    + ", humidity_centi="
                    + str(climate.get("rh_centi"))[:8]
                )
            bmp = data.get("bmp280")
            if isinstance(bmp, dict) and bmp.get("valid") is True:
                cues.append(
                    "BMP280 local pressure_pa="
                    + str(bmp.get("pressure_pa"))[:9]
                )
            if cues:
                remember_tool_context(
                    owner, robot_id, "sensor_telemetry",
                    "; ".join(cues)[:180] + "; raw local probe, not calibrated",
                )
        return data

