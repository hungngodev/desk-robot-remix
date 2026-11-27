"""Source preserving robot inventory and raw telemetry API route group.

These routes keep existing shared authorization and the exact human turn
receipt handoff. Robot telemetry is read only, never motion authority.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from time import monotonic_ns

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .api_ingress import require_configured_robot
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


def _status_health(
    settings: Settings, request: Request, head: str, body: str,
    *, host_stop: Mapping[str, object] | None = None,
) -> dict:
    room = _room_status(settings, request)
    blocked = isinstance(host_stop, Mapping) and host_stop.get("blocked") is True
    health = {
        "head": head,
        "body": body,
        "room_station": room,
        "state": ("degraded" if blocked or body not in ("status_received", "simulated")
                  or room not in ("disabled", "unverified") else "reported"),
        "physical_acceptance_pass": False,
    }
    if isinstance(host_stop, Mapping) and isinstance(host_stop.get("state"), str):
        health["host_stop"] = host_stop["state"]
    return health


def _require_current_voice_tool(
    request: Request, robot_id: str, owner, current_tool_context,
) -> None:
    """Fence canonical voice tool reads without restricting dashboard polling."""
    if request.headers.get("x-desk-robot-tool-receipt") == "1":
        current_tool_context(
            owner, robot_id, "Voice telemetry tool turn superseded during read"
        )


def _require_telemetry_identity(data, robot_id: str, message: str) -> None:
    if not isinstance(data, dict) or data.get("robot_id") != robot_id:
        raise HeadError(message)


def _status_summary(data: dict, *, host_stop: Mapping[str, object] | None = None) -> str:
    safety = data.get("safety")
    safety = safety if isinstance(safety, dict) else {}
    summary = (
        f"backend={str(data.get('backend', 'unknown'))[:24]}, "
        f"armed={data.get('armed')}, "
        f"safety_fault={str(safety.get('fault', 'unknown'))[:40]}"
    )
    if isinstance(host_stop, Mapping) and host_stop.get("blocked") is True:
        summary += f", host_stop={str(host_stop.get('state', 'unknown'))[:32]}"
    return summary


def _climate_cue(reading, previous_seq, elapsed_ms):
    if not _fresh_aux_acquisition(
        reading, previous_seq=previous_seq, max_age_ms=1000, elapsed_ms=elapsed_ms,
    ):
        return None
    if not (type(reading.get("temp_centi")) is int
            and -4500 <= reading["temp_centi"] <= 13000
            and type(reading.get("rh_centi")) is int
            and 0 <= reading["rh_centi"] <= 10000):
        return None
    return (
        f"SHT41 local temp_centi={reading['temp_centi']}, "
        f"humidity_centi={reading['rh_centi']}, "
        f"seq={reading['seq']}, age_ms={reading['age_ms']}"
    )


def _bmp_cue(reading, previous_seq, elapsed_ms):
    if not _fresh_aux_acquisition(
        reading, previous_seq=previous_seq, max_age_ms=2000, elapsed_ms=elapsed_ms,
    ):
        return None
    if not (reading.get("present") is True
            and type(reading.get("chip_id")) is int
            and reading["chip_id"] == 0x58
            and type(reading.get("temp_centi")) is int
            and -4000 <= reading["temp_centi"] <= 8500
            and type(reading.get("pressure_pa")) is int
            and 30000 <= reading["pressure_pa"] <= 120000):
        return None
    return (
        f"BMP280 local pressure_pa={reading['pressure_pa']}, "
        f"seq={reading['seq']}, age_ms={reading['age_ms']}"
    )


def _power_diagnostics(data: dict) -> dict:
    power = data.get("power")
    if isinstance(power, dict) and "monitor_fault" in power:
        # Diagnostic only; do not inject a historical fault into speech context.
        warning = ina226_monitor_warning(power)
        return {**data, "power": {**power, "monitor_warning": warning}}
    return data


_MAX_RETIRED_AUX_BOOTS = 128


class _AuxReceiptCursor:
    def __init__(self) -> None:
        # Dashboard polling never consumes an acquisition's conversational provenance.
        self.last_aux_context_seq: dict[tuple[str, str], tuple[int, int]] = {}
        self.active_aux_boot: dict[str, int] = {}
        self.retired_aux_boots: dict[str, set[int]] = {}

    def previous_seq(self, key: tuple[str, str], boot: int) -> int | None:
        cursor = self.last_aux_context_seq.get(key)
        return cursor[1] if cursor is not None and cursor[0] == boot else None

    def remember(self, owner, robot_id: str, data: dict, elapsed_ms: float,
                 remember_tool_context) -> None:
        # Only an authenticated, explicit tool request may publish sensor receipts.
        boot = _aux_boot_epoch(data)
        retired = self.retired_aux_boots.get(robot_id, set())
        if owner is None or boot is None or boot in retired:
            return
        prior_boot = self.active_aux_boot.get(robot_id)
        if (
            prior_boot is not None
            and prior_boot != boot
            and len(retired) >= _MAX_RETIRED_AUX_BOOTS
        ):
            # Fail closed when replay-fence capacity is exhausted rather than
            # growing unboundedly or promoting an unfenced new boot epoch.
            return
        cues = []
        pending_seq: dict[tuple[str, str], tuple[int, int]] = {}
        for sensor, make_cue in (("climate", _climate_cue), ("bmp280", _bmp_cue)):
            reading = data.get(sensor)
            key = (robot_id, sensor)
            cue = make_cue(reading, self.previous_seq(key, boot), elapsed_ms)
            if cue is not None:
                pending_seq[key] = (boot, reading["seq"])
                cues.append(cue)
        if not cues:
            return
        admitted = remember_tool_context(
            owner, robot_id, "sensor_telemetry",
            "; ".join(cues)[:180] + "; raw local probe, not calibrated",
        )
        # Advance all source cursors only after admission; no await separates commit.
        if admitted is True:
            if prior_boot is not None and prior_boot != boot:
                self.retired_aux_boots.setdefault(robot_id, set()).add(prior_boot)
            self.active_aux_boot[robot_id] = boot
            self.last_aux_context_seq.update(pending_seq)


def _register_inventory_route(app, settings, authorize) -> None:
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


def _register_status_route(
    app, settings, authorize, coordinator,
    requested_tool_context, remember_tool_context, current_tool_context,
) -> None:
    @app.get("/v1/robots/{robot_id}/status", dependencies=[Depends(authorize)])
    async def status(robot_id: str, request: Request):
        require_configured_robot(settings, robot_id)
        owner = coordinator()
        owner.robot(robot_id)
        context = requested_tool_context(request, robot_id)
        _require_current_voice_tool(request, robot_id, context, current_tool_context)
        head = owner.heads.get(robot_id)
        stop_reader = getattr(owner, "host_stop_state", None)
        host_stop = stop_reader(robot_id) if callable(stop_reader) else None
        getter = getattr(head, "status", None)
        if not callable(getter):
            detail = "Telemetry head unavailable" if head is None else "Status adapter unavailable"
            health = _status_health(
                settings, request, "adapter_unavailable", "unconfirmed",
                host_stop=host_stop,
            )
            payload = {"robot_id": robot_id, "detail": detail, "health": health}
            if host_stop is not None:
                payload["host_stop_state"] = host_stop
            return JSONResponse(payload, status_code=503)
        try:
            data = await getter()
        except (HeadError, TimeoutError) as exc:
            _require_current_voice_tool(request, robot_id, context, current_tool_context)
            head_state, body_state = _failed_status_components(exc, robot_id)
            payload = {
                "robot_id": robot_id, "error": "Robot status unavailable",
                "health": _status_health(
                    settings, request, head_state, body_state, host_stop=host_stop,
                ),
            }
            if host_stop is not None:
                payload["host_stop_state"] = host_stop
            return JSONResponse(payload, status_code=503)
        _require_current_voice_tool(request, robot_id, context, current_tool_context)
        _require_telemetry_identity(data, robot_id, "Head status robot identity mismatch")
        remember_tool_context(
            context, robot_id, "robot_status", _status_summary(data, host_stop=host_stop),
        )
        simulated = settings.mode == "simulation"
        health = _status_health(
            settings, request, "simulated" if simulated else "responded",
            "simulated" if simulated else "status_received",
            host_stop=host_stop,
        )
        result = {**data, "health": health}
        if host_stop is not None:
            result["host_stop_state"] = host_stop
        return result


def _register_aux_route(
    app, settings, authorize, coordinator,
    requested_tool_context, remember_tool_context, current_tool_context,
) -> None:
    cursor = _AuxReceiptCursor()

    @app.get("/v1/robots/{robot_id}/aux", dependencies=[Depends(authorize)])
    async def aux(robot_id: str, request: Request):
        require_configured_robot(settings, robot_id)
        fleet = coordinator()
        fleet.robot(robot_id)
        head = fleet.heads.get(robot_id)
        if head is None:
            raise HTTPException(503, "Telemetry head unavailable")
        # Bind the requesting human turn before slow physical telemetry.
        owner = requested_tool_context(request, robot_id)
        _require_current_voice_tool(request, robot_id, owner, current_tool_context)
        getter = getattr(head, "aux_status", None)
        if not callable(getter):
            return {"robot_id": robot_id, "available": False,
                    "reason": "No physical accessory telemetry adapter"}
        started_ns = monotonic_ns()
        data = await getter()
        elapsed_ms = (monotonic_ns() - started_ns) / 1_000_000
        _require_current_voice_tool(request, robot_id, owner, current_tool_context)
        _require_telemetry_identity(data, robot_id, "Auxiliary telemetry robot identity mismatch")
        # Validate adapter diagnostics before admitting any tool receipt.
        try:
            data = _power_diagnostics(data)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        cursor.remember(owner, robot_id, data, elapsed_ms, remember_tool_context)
        return _json_safe_telemetry(data)


def register_robot_status_routes(
    app: FastAPI, settings: Settings, *, authorize, coordinator,
    requested_tool_context, remember_tool_context, current_tool_context,
) -> None:
    _register_inventory_route(app, settings, authorize)
    _register_status_route(
        app, settings, authorize, coordinator,
        requested_tool_context, remember_tool_context, current_tool_context,
    )
    _register_aux_route(
        app, settings, authorize, coordinator,
        requested_tool_context, remember_tool_context, current_tool_context,
    )
