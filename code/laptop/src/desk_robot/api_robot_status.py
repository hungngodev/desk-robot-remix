"""Source preserving robot inventory and raw telemetry API route group.

These routes keep existing shared authorization and the exact human turn
receipt handoff. Robot telemetry is read only, never motion authority.
"""
from __future__ import annotations

import math
from time import monotonic_ns

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .aux import _aux_boot_epoch, _fresh_aux_acquisition, ina226_monitor_warning
from .config import Settings
from .transport import HeadError


def _json_safe_telemetry(value: object) -> object:
    """Keep invalid legacy diagnostics readable, never promote them to facts."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe_telemetry(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_telemetry(v) for v in value]
    return value


def _failed_status_components(exc: HeadError | TimeoutError, robot_id: str) -> tuple[str, str]:
    """Use the authenticated bridge's exact error envelope, not exception text."""
    cause = exc.__cause__
    if isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "unreachable", "unconfirmed"
    if isinstance(cause, httpx.HTTPStatusError):
        try:
            packet = cause.response.json()
        except ValueError:
            packet = None
        if (isinstance(packet, dict) and packet.get("robot_id") == robot_id
                and packet.get("ok") is False):
            if (cause.response.status_code == 504
                    and packet.get("reply") == "body ACK timeout; command outcome uncertain"):
                return "responded", "serial_timeout"
            if cause.response.status_code == 503:
                return "responded", "unavailable"
    return "unconfirmed", "unconfirmed"


def _room_status(settings: Settings, request: Request) -> str:
    if not getattr(settings, "room_station_enabled", False):
        return "disabled"
    runtime = getattr(request.app.state, "runtime", None)
    feed = getattr(runtime, "room_feed", None)
    if feed is None:
        return "not_started"
    error = getattr(feed, "last_error", None)
    if isinstance(error, str) and error.startswith("Room observation callback failed:"):
        return "callback_error"
    if error:
        return "unavailable"
    # A cleared error or a historical frame count is not a fresh USB receipt.
    return "unverified"


def _status_health(settings: Settings, request: Request, head: str, body: str) -> dict:
    room = _room_status(settings, request)
    return {
        "head": head,
        "body": body,
        "room_station": room,
        "state": ("degraded" if body not in ("status_received", "simulated")
                  or room not in ("disabled", "unverified") else "reported"),
        "physical_acceptance_pass": False,
    }


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
        owner = coordinator()
        owner.robot(robot_id)
        context = requested_tool_context(request, robot_id)
        require_current_voice_tool(request, robot_id, context)
        head = owner.heads.get(robot_id)
        getter = getattr(head, "status", None)
        if not callable(getter):
            detail = "Telemetry head unavailable" if head is None else "Status adapter unavailable"
            health = _status_health(settings, request, "adapter_unavailable", "unconfirmed")
            return JSONResponse(
                {"robot_id": robot_id, "detail": detail, "health": health}, status_code=503,
            )
        try:
            data = await getter()
        except (HeadError, TimeoutError) as exc:
            require_current_voice_tool(request, robot_id, context)
            head_state, body_state = _failed_status_components(exc, robot_id)
            return JSONResponse({
                "robot_id": robot_id, "error": "Robot status unavailable",
                "health": _status_health(settings, request, head_state, body_state),
            }, status_code=503)
        require_current_voice_tool(request, robot_id, context)
        if not isinstance(data, dict) or data.get("robot_id") != robot_id:
            raise HeadError("Head status robot identity mismatch")
        safety = data.get("safety")
        safety = safety if isinstance(safety, dict) else {}
        summary = (
            f"backend={str(data.get('backend', 'unknown'))[:24]}, "
            f"armed={data.get('armed')}, "
            f"safety_fault={str(safety.get('fault', 'unknown'))[:40]}"
        )
        remember_tool_context(context, robot_id, "robot_status", summary)
        simulated = settings.mode == "simulation"
        health = _status_health(
            settings, request, "simulated" if simulated else "responded",
            "simulated" if simulated else "status_received",
        )
        return {**data, "health": health}

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
        started_ns = monotonic_ns()
        data = await getter()
        elapsed_ms = (monotonic_ns() - started_ns) / 1_000_000
        require_current_voice_tool(request, robot_id, owner)
        if not isinstance(data, dict) or data.get("robot_id") != robot_id:
            raise HeadError("Auxiliary telemetry robot identity mismatch")
        power = data.get("power")
        if isinstance(power, dict) and "monitor_fault" in power:
            # Validate adapter diagnostics before admitting any tool receipt.
            try:
                warning = ina226_monitor_warning(power)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=503)
            # Diagnostic only; do not inject a historical fault into speech context.
            data = {**data, "power": {**power, "monitor_warning": warning}}
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
                    max_age_ms=1000, elapsed_ms=elapsed_ms,
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
                    max_age_ms=2000, elapsed_ms=elapsed_ms,
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

