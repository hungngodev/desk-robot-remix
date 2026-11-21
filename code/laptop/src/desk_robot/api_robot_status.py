"""Source preserving robot inventory and raw telemetry API route group.

These routes keep existing shared authorization and the exact human turn
receipt handoff. Robot telemetry is read only, never motion authority.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request

from .config import Settings
from .transport import HeadError


def _fresh_aux_acquisition(
    reading: object, *, previous_seq: int | None, max_age_ms: int,
) -> bool:
    """Require a recent, genuinely newer acquisition for spoken tool context.

    Old firmware may omit a clock in its raw read-only diagnostics. That
    compatibility must not turn one indefinitely cached sensor value into a
    succession of new live observations for the model.
    """
    if not isinstance(reading, dict) or reading.get("valid") is not True:
        return False
    seq, age = reading.get("seq"), reading.get("age_ms")
    if (type(seq) is not int or not 1 <= seq <= 0xffffffff
            or type(age) is not int or not 0 <= age < max_age_ms):
        return False
    if previous_seq is None:
        return True
    # Unsigned half-range ordering accepts genuine uint32 sequence rollover,
    # but rejects duplicate and reordered old observations.
    delta = (seq - previous_seq) & 0xffffffff
    return 0 < delta < 0x80000000


def register_robot_status_routes(
    app: FastAPI, settings: Settings, *, authorize, coordinator,
    requested_tool_context, remember_tool_context,
) -> None:
    # Only accepted human-tool receipts advance this in-process cursor.
    # Dashboard polling still exposes historical raw diagnostics without
    # consuming a newly acquired sample's conversational provenance.
    last_aux_context_seq: dict[tuple[str, str], int] = {}

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
            climate_key = (robot_id, "climate")
            if (_fresh_aux_acquisition(
                    climate, previous_seq=last_aux_context_seq.get(climate_key),
                    max_age_ms=1000,
                )
                and type(climate.get("temp_centi")) is int
                and -4500 <= climate["temp_centi"] <= 13000
                and type(climate.get("rh_centi")) is int
                and 0 <= climate["rh_centi"] <= 10000):
                last_aux_context_seq[climate_key] = climate["seq"]
                cues.append(
                    f"SHT41 local temp_centi={climate['temp_centi']}, "
                    f"humidity_centi={climate['rh_centi']}, "
                    f"seq={climate['seq']}, age_ms={climate['age_ms']}"
                )
            bmp = data.get("bmp280")
            bmp_key = (robot_id, "bmp280")
            if (_fresh_aux_acquisition(
                    bmp, previous_seq=last_aux_context_seq.get(bmp_key),
                    max_age_ms=2000,
                )
                and bmp.get("present") is True
                and type(bmp.get("chip_id")) is int
                and bmp["chip_id"] == 0x58
                and type(bmp.get("temp_centi")) is int
                and -4000 <= bmp["temp_centi"] <= 8500
                and type(bmp.get("pressure_pa")) is int
                and 30000 <= bmp["pressure_pa"] <= 120000):
                last_aux_context_seq[bmp_key] = bmp["seq"]
                cues.append(
                    f"BMP280 local pressure_pa={bmp['pressure_pa']}, "
                    f"seq={bmp['seq']}, age_ms={bmp['age_ms']}"
                )
            if cues:
                remember_tool_context(
                    owner, robot_id, "sensor_telemetry",
                    "; ".join(cues)[:180] + "; raw local probe, not calibrated",
                )
        return data

