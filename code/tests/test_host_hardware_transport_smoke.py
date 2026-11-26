"""Real runtime owners with fake USB and HTTP boundaries, not physical acceptance."""

import asyncio
import json
import sys
import threading
import time
from types import SimpleNamespace

import httpx
from desk_robot import room_station, runtime as runtime_module
from desk_robot.api import create_app
from desk_robot.vision import SceneChange


class MockSerial:
    def __init__(self, closed):
        self.closed = closed
        self.lines = []
        self.sent_sample = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed.set()

    def write(self, request):
        assert request.startswith(b"\nSYNC ") and request.endswith(b"\n")
        self.lines.append(b"SYNC_ACK " + request[6:-1] + b"\n")
        if not self.sent_sample:
            readings = {name: {"valid": False} for name in room_station.SENSORS}
            readings["soil"] = {"valid": True, "sample_ms": 1000, "raw_adc": 2250}
            self.lines.append(json.dumps({
                "v": 1, "station": "room-pod-01", "seq": 1,
                "at_ms": 1000, "readings": readings,
            }).encode() + b"\n")
            self.sent_sample = True
        return len(request)

    def read_until(self, expected, size):
        assert expected == b"\n" and size > 0
        if self.lines:
            return self.lines.pop(0)
        time.sleep(0.01)
        return b""


class MockBridge:
    def __init__(self, robot, tokens):
        self.robot = robot
        self.tokens = tokens
        self.commands = []
        self.interrupts = []

    def __call__(self, request):
        if request.url.path == "/events":
            assert request.headers["Authorization"] == "Bearer " + "d" * 40
            return httpx.Response(200, json={
                "cursor": 0, "reset": False, "lost": False, "events": [],
                "active_human_robots": [], "voice_turn_generations": {self.robot.id: 1},
            })
        if request.url.path == "/interrupt":
            assert request.headers["Authorization"] == "Bearer " + "d" * 40
            payload = json.loads(request.content)
            assert payload["device_id"] == self.robot.device_id
            self.interrupts.append(payload)
            return httpx.Response(200, json={
                "device_id": self.robot.device_id, "interrupted": True,
                "head_flush_requested": True,
            })
        assert request.url.path == "/api/command"
        assert request.headers["Authorization"] == (
            "Bearer " + self.tokens["DESK_ROBOT_HEAD_01_TOKEN"]
        )
        command = json.loads(request.content)["command"]
        assert command == "halt"
        self.commands.append(command)
        return httpx.Response(200, json={
            "robot_id": self.robot.id, "ok": True, "reply": "OK halt",
        })


async def test_real_hardware_runtime_usb_voice_and_stop_lifecycle(settings, tokens, monkeypatch):
    settings.robots = settings.robots[:1]
    robot = settings.robots[0]
    robot.device_id = "smoke-head"
    settings.mode = "hardware"
    settings.room_station_port = "/dev/cu.room-smoke"
    settings.room_station_enabled = True
    settings.room_station_context_enabled = True
    settings.voice_vision_tools_enabled = False
    settings.pet_autostart_enabled = False
    monkeypatch.setenv(settings.speech_bridge_token_env, "d" * 40)
    serial_closed = threading.Event()
    serial = MockSerial(serial_closed)
    bridge = MockBridge(robot, tokens)

    def open_serial(port, **kwargs):
        assert port == settings.room_station_port
        assert kwargs == {"baudrate": 115200, "timeout": .25,
                          "write_timeout": .25, "exclusive": True}
        return serial

    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=open_serial))
    monkeypatch.setattr(room_station, "require_local_serial_device", lambda _port: None)
    monkeypatch.setattr(runtime_module, "httpx", SimpleNamespace(
        AsyncClient=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(bridge), **kwargs,
        ),
    ))
    app = create_app(settings)
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        assert runtime.pet.multimodal is runtime.multimodal
        assert runtime.coordinator.multimodal is runtime.multimodal
        voice_task, room_task = runtime._voice_task, runtime._room_task
        assert voice_task is not None and room_task is not None
        hub = runtime.multimodal.hub
        async with asyncio.timeout(2):
            while not (runtime.pet.voice_monitor_ready and any(
                item.get("channel") == "room_station"
                for item in hub.interaction_timeline(robot.id, time.monotonic())
            )):
                await asyncio.sleep(0.01)
        assert runtime._voice_turn_generations == {robot.id: 1}
        change = SceneChange("object", "Synthetic observation", 0.99)
        context = await runtime.pet._load_proactive_context(robot.id, change)
        assert context is not None and context[4] is True
        assert "Station soil probe raw ADC 2250" in context[1].interaction
        assert "not my own sight or person identity" in context[1].interaction
        assert not runtime.coordinator.permits
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            result = await client.post(f"/v1/robots/{robot.id}/stop", headers=tool)
            assert result.status_code == 200, result.text
        assert bridge.commands == ["halt"]
        assert any(item.get("revoke_initiative") is True for item in bridge.interrupts)

    assert app.state.runtime_started is False
    assert runtime.client.is_closed and runtime.coordinator.closed and runtime.pet._closed
    assert voice_task.done() and room_task.done() and serial_closed.is_set()
    assert bridge.commands == ["halt", "halt"]
    assert any(item.get("monitor_unavailable") is True for item in bridge.interrupts)
    assert not runtime.coordinator.permits
