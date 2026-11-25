"""Source preserving robot inventory and raw telemetry API route group.

These routes keep existing shared authorization and the exact human turn
receipt handoff. Robot telemetry is read only, never motion authority.
"""
from __future__ import annotations

import math

from fastapi import Depends, FastAPI, HTTPException, Request

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


def _aux_boot_epoch(data: dict) -> int | None:
    """Bind conversational ambient samples to one explicit WROOM boot."""
    force, proximity = data.get("force"), data.get("proximity")
    if not isinstance(force, dict) or not isinstance(proximity, dict):
        return None
    first, second = force.get("boot_id"), proximity.get("boot_id")
    if (type(first) is int and 1 <= first <= 0xffffffff
            and type(second) is int and first == second):
        return first
    return None


def _json_safe_telemetry(value: object) -> object:
    """Keep invalid legacy diagnostics readable, never promote them to facts."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe_telemetry(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_telemetry(v) for v in value]
    return value


def register_robot_status_routes(
    app: FastAPI, settings: Settings, *, authorize, coordinator,
    requested_tool_context, remember_tool_context, current_tool_context,
) -> None:
    # Only accepted human-tool receipts advance this in-process cursor.
    # Dashboard polling still exposes historical raw diagnostics without
    # consuming a newly acquired sample's conversational provenance.
    last_aux_context_seq: dict[tuple[str, str], tuple[int, int]] = {}
    active_aux_boot: dict[str, int] = {}
    retired_aux_boots: dict[str, set[int]] = {}

    def require_current_voice_tool(request: Request, robot_id: str, owner) -> None:
        """Do not return an old head HTTP result to a newer spoken turn.

        Only the canonical Xiaozhi tool marker demands this stricter
        response fence. Unmarked operator/dashboard reads stay read-only,
        and the existing sensor acquisition cursor remains independent.
        """
        if request.headers.get("x-desk-robot-tool-receipt") != "1":
            return
        current_tool_context(
            owner, robot_id, "Voice telemetry tool turn superseded during read"
        )

    def telemetry_head(robot_id: str):
        owner = coordinator()
        owner.robot(robot_id)
        head = owner.heads.get(robot_id)
        if head is None:
            raise HTTPException(503, "Telemetry head unavailable")
        return head

    def previous_seq(key: tuple[str, str], boot: int) -> int | None:
        cursor = last_aux_context_seq.get(key)
        return cursor[1] if cursor is not None and cursor[0] == boot else None

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
        head = telemetry_head(robot_id)
        context = requested_tool_context(request, robot_id)
        require_current_voice_tool(request, robot_id, context)
        getter = getattr(head, "status", None)
        if not callable(getter):
            raise HTTPException(503, "Status adapter unavailable")
        data = await getter()
        require_current_voice_tool(request, robot_id, context)
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
        head = telemetry_head(robot_id)
        # Bind the requesting human turn before slow physical telemetry.
        # A new VAD epoch must not inherit the older tool's receipt.
        owner = requested_tool_context(request, robot_id)
        require_current_voice_tool(request, robot_id, owner)
        getter = getattr(head, "aux_status", None)
        if not callable(getter):
            return {"robot_id": robot_id, "available": False,
                    "reason": "No physical accessory telemetry adapter"}
        data = await getter()
        require_current_voice_tool(request, robot_id, owner)
        if not isinstance(data, dict) or data.get("robot_id") != robot_id:
            raise HeadError("Auxiliary telemetry robot identity mismatch")
        # Only an authenticated, explicit head tool request may add a short
        # physical sensor receipt to the shared multimodal brain timeline.
        # Dashboard polling and failed/invalid measurements never inject it.
        boot = _aux_boot_epoch(data)
        if (owner is not None and boot is not None
                and boot not in retired_aux_boots.get(robot_id, set())):
            cues = []
            pending_seq: dict[tuple[str, str], tuple[int, int]] = {}
            climate = data.get("climate")
            climate_key = (robot_id, "climate")
            if (_fresh_aux_acquisition(
                    climate, previous_seq=previous_seq(climate_key, boot),
                    max_age_ms=1000,
                )
                and type(climate.get("temp_centi")) is int
                and -4500 <= climate["temp_centi"] <= 13000
                and type(climate.get("rh_centi")) is int
                and 0 <= climate["rh_centi"] <= 10000):
                pending_seq[climate_key] = (boot, climate["seq"])
                cues.append(
                    f"SHT41 local temp_centi={climate['temp_centi']}, "
                    f"humidity_centi={climate['rh_centi']}, "
                    f"seq={climate['seq']}, age_ms={climate['age_ms']}"
                )
            bmp = data.get("bmp280")
            bmp_key = (robot_id, "bmp280")
            if (_fresh_aux_acquisition(
                    bmp, previous_seq=previous_seq(bmp_key, boot),
                    max_age_ms=2000,
                )
                and bmp.get("present") is True
                and type(bmp.get("chip_id")) is int
                and bmp["chip_id"] == 0x58
                and type(bmp.get("temp_centi")) is int
                and -4000 <= bmp["temp_centi"] <= 8500
                and type(bmp.get("pressure_pa")) is int
                and 30000 <= bmp["pressure_pa"] <= 120000):
                pending_seq[bmp_key] = (boot, bmp["seq"])
                cues.append(
                    f"BMP280 local pressure_pa={bmp['pressure_pa']}, "
                    f"seq={bmp['seq']}, age_ms={bmp['age_ms']}"
                )
            if cues:
                admitted = remember_tool_context(
                    owner, robot_id, "sensor_telemetry",
                    "; ".join(cues)[:180] + "; raw local probe, not calibrated",
                )
                # Accept all source cursors only after the current human turn
                # admitted this combined receipt. No await separates commit.
                if admitted is True:
                    prior_boot = active_aux_boot.get(robot_id)
                    if prior_boot is not None and prior_boot != boot:
                        retired_aux_boots.setdefault(robot_id, set()).add(prior_boot)
                    active_aux_boot[robot_id] = boot
                    last_aux_context_seq.update(pending_seq)
        return _json_safe_telemetry(data)

