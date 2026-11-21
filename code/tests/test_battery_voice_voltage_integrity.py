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
from fastapi import FastAPI
from fastapi.routing import APIRoute


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
    register_readonly_context_routes(
        app, SimpleNamespace(mode="hardware"), authorize=lambda: None,
        coordinator=lambda: coordinator,
        requested_tool_context=lambda request, robot_id: "current-human-turn",
        remember_tool_context=lambda owner, robot_id, kind, summary:
            recorded.append((owner, robot_id, kind, summary)),
        native_pet_speech_policy=lambda *args: False,
    )
    endpoint = next(
        route.endpoint for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/power-status"
    )
    if not 2500 <= cell_mv <= 4500:
        with pytest.raises(OperationError, match="Malformed WROOM auxiliary fuel"):
            await endpoint("robot-01", None)
        assert recorded == []
        return
    result = await endpoint("robot-01", None)
    assert result["gauge_available"] is True
    assert result["reported_cell_mv"] == cell_mv
    assert result["reported_soc_centi"] == 6275
    assert result["charging_verified"] is False
    assert recorded == [
        ("current-human-turn", "robot-01", "robot_status",
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
