"""Reject impossible MAX17048 gauge voltages before they become spoken facts.

The Mac status endpoint and independent Xiaozhi fact sanitizer must enforce
the same 2500..4500 mV sanity interval as the existing motion preflight.
Raw measurements remain unqualified and are not charging authorization.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from desk_robot.api_readonly_context import register_readonly_context_routes
from desk_robot.controller import OperationError
from fastapi import FastAPI, HTTPException, Request
from fastapi.routing import APIRoute


def _check_fake_current_tool_owner(owner, robot_id, message):
    """The battery route fixture retains its previous synthetic turn fence."""
    if (not isinstance(owner, tuple) or len(owner) != 2
            or getattr(owner[0], "_turn_epoch", {}).get(robot_id) != owner[1]):
        raise HTTPException(409, message)


@pytest.mark.parametrize("cell_mv", [0, 2499, 2500, 3875, 4500, 4501])
async def test_power_status_no_impossible_voltage_enters_current_human_turn(cell_mv):
    recorded = []

    async def aux_status():
        return {"robot_id": "robot-01", "power": {
            "fuel_valid": True, "fuel_seq": 7,
            "cell_mv": cell_mv, "soc_centi": 6275,
        }}

    coordinator = SimpleNamespace(
        robot=lambda robot_id: robot_id,
        heads={"robot-01": SimpleNamespace(aux_status=aux_status)},
    )
    app = FastAPI()
    visual = SimpleNamespace(_turn_epoch={"robot-01": 7})
    owner = (visual, 7)
    app.state.runtime = SimpleNamespace(multimodal=visual)
    request = Request({
        "type": "http", "method": "GET", "path": "/v1/pet/robot-01/power-status",
        "headers": [(b"x-desk-robot-tool-receipt", b"1")],
    })
    register_readonly_context_routes(
        app, SimpleNamespace(
            mode="hardware",
            robot=lambda robot_id: SimpleNamespace(id=robot_id),
        ), authorize=lambda: None,
        coordinator=lambda: coordinator,
        requested_tool_context=lambda request, robot_id: owner,
        remember_tool_context=lambda owner, robot_id, kind, summary:
            recorded.append((owner, robot_id, kind, summary)),
        native_pet_speech_policy=lambda *args: False,
        current_tool_context=_check_fake_current_tool_owner,
    )
    endpoint = next(
        route.endpoint for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/power-status"
    )
    if not 2500 <= cell_mv <= 4500:
        with pytest.raises(OperationError, match="Malformed WROOM auxiliary fuel"):
            await endpoint("robot-01", request)
        assert recorded == []
        return
    result = await endpoint("robot-01", request)
    assert result["gauge_available"] is True
    assert result["reported_cell_mv"] == cell_mv
    assert result["reported_soc_centi"] == 6275
    assert result["charging_verified"] is False
    assert recorded == [
        (owner, "robot-01", "robot_status",
         f"WROOM fuel gauge reports 62.8% estimate and {cell_mv}mV; "
         "sample freshness and charging unverified"),
    ]


@pytest.mark.parametrize("cell_mv", [0, 2499, 2500, 3875, 4500, 4501])
def test_native_both_battery_fact_paths_share_voltage_sanity_range(cell_mv):
    path = (Path(__file__).resolve().parents[1] / "laptop/server/overlay"
            / "desk_robot_voice_intents.py")
    spec = importlib.util.spec_from_file_location("voice_voltage_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    accepted = 2500 <= cell_mv <= 4500
    direct = module.native_grounded_fact("power-status", {
        "source": "wroom_aux_fuel_gauge_raw_unqualified",
        "gauge_available": True, "raw_fuel_acquisition_seq": 7,
        "reported_soc_centi": 6275, "reported_cell_mv": cell_mv,
    })
    assert (direct is not None) is accepted
    if accepted:
        assert direct["cell_mv"] == cell_mv
        assert direct["charging_verified"] is False
    aux = module.native_grounded_fact("aux-status", {
        "climate": {"valid": False},
        "power": {
            "fuel_valid": True, "fuel_seq": 7,
            "soc_centi": 6275, "cell_mv": cell_mv,
        },
    })
    assert aux is not None
    assert ("fuel_gauge" in aux) is accepted
    if accepted:
        assert aux["fuel_gauge"]["reported_cell_mv"] == cell_mv
        assert aux["fuel_gauge"]["qualified"] is False
