"""Live Mac camera and vision preflight never issues motor, charger or pickup commands."""
import sys
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.cli import inspect_live_media, request


def configured(*, motor_backend="stepper_28byj48"):
    robot = SimpleNamespace(id="robot-01", device_id="xiaozhi-01",
                            motor_backend=motor_backend)
    return SimpleNamespace(
        mode="hardware", voice_vision_tools_enabled=True,
        coordinator_token_env="DESK_ROBOT_API_TOKEN",
        robot=lambda robot_id: robot if robot_id == robot.id
        else (_ for _ in ()).throw(KeyError(robot_id)),
    )


def simulated_mac(*, wrong_head=False, old_frame=False,
                  raw_context=False, invalid_tool=False,
                  backend="stepper_28byj48"):
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
                "backend": backend,
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


async def test_live_doctor_owned_client_ignores_proxy_environment(monkeypatch):
    import desk_robot.cli as cli

    original_client = httpx.AsyncClient
    transport, calls = simulated_mac()
    options = []
    urls = []

    def factory(*args, **kwargs):
        options.append(kwargs.get("trust_env"))
        urls.append(kwargs.get("base_url"))
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setenv("DESK_ROBOT_TOOL_TOKEN", "t" * 40)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8899")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8899")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8899")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setattr(cli.httpx, "AsyncClient", factory)

    settings = configured()
    settings.tools_token_env = "DESK_ROBOT_TOOL_TOKEN"
    result = await inspect_live_media(
        settings, "robot-01", look=True, base_url="http://127.0.0.1:9876",
    )
    assert result["live_tool_tested"] is True
    assert options == [False]
    assert urls == ["http://127.0.0.1:9876"]
    assert [method for method, _ in calls] == [
        "GET", "GET", "GET", "GET", "POST",
    ]


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
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8899")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8899")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8899")
    monkeypatch.delenv("NO_PROXY", raising=False)
    options = []

    def fake_client(*args, **kwargs):
        options.append(kwargs.get("trust_env"))
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
    assert options == [False] * 5
    args.action = "look"
    with pytest.raises(ValueError, match="consent"):
        await request(args, settings)
    # Even the rejected request must not configure a proxy for the bearer.
    assert options == [False] * 6


@pytest.mark.parametrize(
    ("selected", "reported", "allowed"),
    [
        ("stepper_28byj48", "stepper_28byj48", True),
        ("dc_pwm_guarded", "dc_pwm_guarded", True),
        ("stepper_28byj48", "dc_pwm_guarded", False),
        ("dc_pwm_guarded", "stepper_28byj48", False),
        ("dc_pwm_guarded", "dc_pwm", False),
        (None, "dc_pwm_guarded", False),
    ],
)
async def test_live_doctor_binds_selected_backend_without_motor_commands(
    selected, reported, allowed,
):
    transport, calls = simulated_mac(backend=reported)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8765", transport=transport,
    ) as client:
        if allowed:
            result = await inspect_live_media(
                configured(motor_backend=selected), "robot-01", client=client,
            )
            assert result["xiao_jpeg_received"] is True
            assert result["motor_armed_or_charging_verified"] is False
            assert [method for method, _ in calls] == ["GET"] * 4
        else:
            with pytest.raises(ValueError, match="motor backend"):
                await inspect_live_media(
                    configured(motor_backend=selected), "robot-01", client=client,
                )
            assert calls == ([] if selected is None else [
                ("GET", "/v1/robots/robot-01/status"),
            ])
    assert not any(
        action in path for _, path in calls
        for action in ("/enable", "/move", "/pickup")
    )


def test_cli_missing_config_is_clean_error(monkeypatch, tmp_path, capsys):
    import desk_robot.cli as cli

    missing = tmp_path / "missing.toml"
    monkeypatch.setattr(sys, "argv", ["desk-robot", "--config", str(missing), "doctor"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert str(missing) in capsys.readouterr().err


def test_cli_doctor_uses_custom_url(monkeypatch, tmp_path):
    import desk_robot.cli as cli

    settings = SimpleNamespace(
        mode="hardware", coordinator_token_env="TEST_OPERATOR",
        tools_token_env="TEST_TOOLS", robots=[SimpleNamespace(
            id="robot-01", motion_enabled=False, calibration=None,
        )],
    )
    monkeypatch.setattr(cli, "load_settings", lambda path: settings)
    seen = []

    async def inspect(settings, robot_id, *, look, base_url="http://127.0.0.1:8765"):
        seen.append((robot_id, look, base_url))
        return {}

    monkeypatch.setattr(cli, "inspect_live_media", inspect)
    monkeypatch.setattr(sys, "argv", [
        "desk-robot", "--secrets", str(tmp_path / "none"),
        "--url", "http://127.0.0.1:9876", "doctor", "--live",
    ])
    cli.main()
    assert seen == [("robot-01", False, "http://127.0.0.1:9876")]


@pytest.mark.parametrize("command", [
    ["doctor", "--live", "--robot", "missing"],
    ["look", "missing", "What do you see?"],
    ["situation", "missing"],
    ["vision", "missing"],
    ["power", "missing"],
])
def test_cli_unknown_robot_is_clean_error(command, monkeypatch, capsys):
    import desk_robot.cli as cli

    settings = configured()
    settings.tools_token_env = "DESK_ROBOT_TOOL_TOKEN"
    settings.robots = [SimpleNamespace(
        id="robot-01", motion_enabled=False, calibration=None,
    )]
    monkeypatch.setattr(cli, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli, "load_env", lambda path: None)
    monkeypatch.setenv("DESK_ROBOT_API_TOKEN", "a" * 40)
    transport, calls = simulated_mac()
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(cli.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(sys, "argv", ["desk-robot", *command])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown robot ID" in captured.err
    assert "desk-robot doctor" in captured.err
    assert "Traceback" not in captured.err
    assert not captured.out
    assert calls == []


async def test_live_doctor_unknown_robot_preserves_lookup_cause():
    with pytest.raises(ValueError, match="Unknown robot ID") as exc:
        await inspect_live_media(configured(), "missing")
    assert isinstance(exc.value.__cause__, KeyError)

@pytest.mark.parametrize("explicit_secrets", [False, True])
def test_cli_credentials_follow_selected_config(monkeypatch, tmp_path, capsys, explicit_secrets):
    import json

    import desk_robot.cli as cli

    checkout = tmp_path / "checkout"
    monkeypatch.setattr(cli, "ROOT", checkout)
    config = tmp_path / "builder" / "robot.toml"
    config.parent.mkdir()
    config.write_text(
        'mode = "simulation"\n'
        'coordinator_token_env = "DRX_FIRST_OPERATOR"\n'
        'tools_token_env = "DRX_FIRST_TOOLS"\n'
        'speech_bridge_token_env = "DRX_FIRST_SPEECH"\n'
        '[[robots]]\n'
        'id = "first"\n'
        'name = "First"\n'
        'token_env = "DRX_FIRST_HEAD"\n',
        encoding="utf-8",
    )
    cwd = tmp_path / "unrelated"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    names = ("DRX_FIRST_OPERATOR", "DRX_FIRST_TOOLS", "DRX_FIRST_SPEECH", "DRX_FIRST_HEAD")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    args = ["desk-robot", "--config", str(config)]
    expected = config.with_name("local.env")
    if explicit_secrets:
        expected = tmp_path / "private.env"
        args += ["--secrets", str(expected)]
    monkeypatch.setattr(sys, "argv", [*args, "secrets"])
    cli.main()
    capsys.readouterr()
    assert expected.is_file()
    assert not (checkout / "config" / "local.env").exists()
    assert not (cwd / "local.env").exists()
    if explicit_secrets:
        assert not config.with_name("local.env").exists()

    # The doctor must consume exactly the file created by the secrets command,
    # not credentials inherited from the host environment or the checkout.
    monkeypatch.setattr(sys, "argv", [*args, "doctor"])
    cli.main()
    assert json.loads(capsys.readouterr().out)["credentials_present"] is True


@pytest.mark.parametrize(
    ("command", "diagnostic"),
    [
        ([], "action"),
        (["doctor", "--bogus"], "unrecognized arguments"),
        (["doctor", "--robot"], "expected one argument"),
        (["look", "robot-01"], "question"),
        (["move", "robot-01"], "command"),
        (["pickup", "robot-01", "cup"], "invalid choice"),
        (["chat", "robot-01", "--turns", "0"], "invalid choice"),
        (["chat", "robot-01", "--turns", "11"], "invalid choice"),
        (["chat", "robot-01", "--turns", "nan"], "invalid int value"),
        (["serve", "--port", "bad"], "invalid int value"),
        (["secrets", "--bogus"], "unrecognized arguments"),
    ],
)
def test_cli_malformed_arguments_prevent_side_effects(command, diagnostic, monkeypatch,
                                                      tmp_path, capsys):
    import desk_robot.cli as cli

    credentials = tmp_path / "local.env"
    credentials.write_bytes(b"EXISTING=unchanged\n")
    config = tmp_path / "robot.toml"
    config.write_bytes(b'mode = "simulation"\n')
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    calls = []

    def unexpected(*args, **kwargs):
        calls.append("side effect")
        pytest.fail("Malformed CLI arguments must not reach configuration or execution")

    for name in ("load_settings", "load_env", "write_secrets", "Runtime",
                 "request", "demo", "inspect_live_media"):
        monkeypatch.setattr(cli, name, unexpected)
    monkeypatch.setattr(cli.httpx, "AsyncClient", unexpected)
    monkeypatch.setattr(sys, "argv", [
        "desk-robot", "--config", str(config), "--secrets", str(credentials), *command,
    ])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "usage:" in captured.err
    assert diagnostic in captured.err
    assert "Traceback" not in captured.err
    assert calls == []
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
