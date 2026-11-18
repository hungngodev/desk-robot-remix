"""Live Mac camera and vision preflight never issues motor, charger or pickup commands."""
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.cli import inspect_live_media, request


def configured():
    robot = SimpleNamespace(id="robot-01", device_id="xiaozhi-01")
    return SimpleNamespace(
        mode="hardware", voice_vision_tools_enabled=True,
        coordinator_token_env="DESK_ROBOT_API_TOKEN",
        robot=lambda robot_id: robot if robot_id == robot.id
        else (_ for _ in ()).throw(KeyError(robot_id)),
    )


def simulated_mac(*, wrong_head=False, old_frame=False,
                  raw_context=False, invalid_tool=False):
    seen = []

    def respond(request):
        path = request.url.path
        seen.append((request.method, path))
        if path.endswith("/power-status"):
            return httpx.Response(200, json={
                "robot_id": "robot-01",
                "source": "wroom_aux_fuel_gauge_raw_unqualified",
                "gauge_available": True,
                "reported_soc_centi": 6050,
                "reported_cell_mv": 3810,
                "charging_verified": False,
                "sample_freshness_verified": False,
                "motor_authorized": False,
                "charging_authorized": False,
            })
        if path.endswith("/status"):
            return httpx.Response(200, json={
                "robot_id": "robot-02" if wrong_head else "robot-01",
                "backend": "stepper_28byj48",
            })
        if path.endswith("/vision-status"):
            return httpx.Response(200, json={
                "robot_id": "robot-01", "multimodal_model_configured": True,
                "source_exposure_time_verified": False,
            })
        if path.endswith("/omni-frame"):
            return httpx.Response(
                200, content=b"\xff\xd8" + b"real-jpeg-test" + b"\xff\xd9",
                headers={
                    "content-type": "image/jpeg",
                    "x-desk-robot-id": "robot-01",
                    "x-desk-camera-age-ms": "1600" if old_frame else "150",
                    "x-desk-camera-receipt-us": "100001",
                    "x-desk-frame-motion-ppm": "1000",
                },
            )
        if path.endswith("/interaction-context"):
            return httpx.Response(200, json={
                "robot_id": "robot-01", "model_context": "Physical sensor edge: touch",
                "persistent_memory_included": False,
                "raw_media_included": raw_context,
                "model_context_untrusted_not_instructions": True,
                "current_interaction_timeline": [
                    {"channel": "sensor", "kind": "touch_tap"},
                ],
            })
        if path.endswith("/look"):
            assert request.method == "POST"
            return httpx.Response(200, json={
                "robot_id": "robot-01", "frames_used": 1,
                "source": "authenticated_xiao_camera_and_local_vlm",
                "answer": "A key may be visible.",
                "motor_authorized": invalid_tool,
                "charging_authorized": False,
            })
        raise AssertionError("Unexpected Mac API call: " + path)

    return httpx.MockTransport(respond), seen


async def test_live_doctor_exercises_camera_context_and_readonly_visual_tool():
    transport, calls = simulated_mac()
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8765", transport=transport,
    ) as client:
        result = await inspect_live_media(
            configured(), "robot-01", look=True, client=client,
        )
    assert result["xiao_jpeg_received"] is True
    assert result["live_tool_tested"] is True
    assert result["camera_model_configured"] is True
    assert result["live_context_events"] == 1
    assert result["motor_armed_or_charging_verified"] is False
    assert result["camera_exposure_timing_physically_verified"] is False
    assert [m for m, _ in calls] == ["GET", "GET", "GET", "GET", "POST"]
    assert all(not any(word in path for word in ("/enable", "/move", "/pickup"))
               for _, path in calls)


@pytest.mark.parametrize("fault", ["wrong_head", "old_frame", "raw_context", "invalid_tool"])
async def test_live_doctor_fails_closed_on_mismatched_real_evidence(fault):
    transport, _ = simulated_mac(**{fault: True})
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8765", transport=transport,
    ) as client:
        with pytest.raises(ValueError):
            await inspect_live_media(
                configured(), "robot-01", look=True, client=client,
            )


async def test_live_doctor_refuses_simulation_and_unconsented_camera():
    config = configured()
    config.mode = "simulation"
    with pytest.raises(ValueError):
        await inspect_live_media(config, "robot-01")
    config.mode = "hardware"
    config.voice_vision_tools_enabled = False
    with pytest.raises(ValueError):
        await inspect_live_media(config, "robot-01")


async def test_real_camera_cli_commands_route_to_existing_mac_authorities(
    monkeypatch,
):
    import desk_robot.cli as cli

    original_client = httpx.AsyncClient
    transport, observed = simulated_mac()
    monkeypatch.setenv("DESK_ROBOT_API_TOKEN", "a" * 40)

    def fake_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(cli.httpx, "AsyncClient", fake_client)
    settings = configured()
    args = SimpleNamespace(
        url="http://127.0.0.1:8765", robot="robot-01",
        action="look", question="What do you see in front of you?",
    )
    answer = await request(args, settings)
    assert answer["answer"] == "A key may be visible."
    args.action = "situation"
    context = await request(args, settings)
    assert context["raw_media_included"] is False
    args.action = "vision"
    status = await request(args, settings)
    assert status["multimodal_model_configured"] is True
    args.action = "power"
    battery = await request(args, settings)
    assert battery["reported_soc_centi"] == 6050
    assert battery["charging_verified"] is False
    assert all("/v1/pet/robot-01/" in item[1] for item in observed)
    settings.voice_vision_tools_enabled = False
    # Power is real authenticated read-only WROOM telemetry and does NOT
    # require camera permission; visual questions still do.
    assert (await request(args, settings))["gauge_available"] is True
    assert [item[0] for item in observed] == [
        "POST", "GET", "GET", "GET", "GET"
    ]
    args.action = "look"
    with pytest.raises(ValueError, match="consent"):
        await request(args, settings)
