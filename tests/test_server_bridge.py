import base64
import importlib.util
import json
import time
import wave
from io import BytesIO
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "test_desk_bridge", ROOT / "laptop/server/overlay/desk_robot_bridge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", "s" * 40)
    monkeypatch.setenv(
        "DESK_ROBOT_DEVICE_MAP", json.dumps({"robot-01": "mac-01", "robot-02": "mac-02"})
    )
    return module


def conn(device):
    return SimpleNamespace(
        device_id=device,
        client_is_speaking=False,
        calling=False,
        tts=SimpleNamespace(tts_text_queue=Queue(), tts_audio_queue=Queue()),
        client_abort=False,
    )


def test_device_registry_and_expiring_mute(bridge):
    first, second = conn("mac-01"), conn("mac-02")
    bridge.register(first)
    with pytest.raises(RuntimeError, match="Duplicate"):
        bridge.register(conn("mac-01"))
    bridge.lease_ids = frozenset(["mac-01"])
    bridge.lease_until = time.monotonic() + 10
    assert bridge.suppress_message(first, b"microphone")
    assert not bridge.suppress_message(second, b"microphone")
    assert bridge.suppress_message(first, '{"type":"listen"}')
    assert not bridge.suppress_message(first, '{"type":"abort"}')
    assert not bridge.suppress_message(first, '{"type":"mcp"}')
    bridge.lease_until = time.monotonic() - 1
    assert not bridge.suppress_message(first, b"microphone")
    bridge.unregister(second)
    assert "mac-01" in bridge.connections
    bridge.unregister(first)
    assert not bridge.connections


def test_wav_bounded_and_real_pcm(bridge):
    with pytest.raises(ValueError):
        bridge.wav_audio("!notbase64")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0" * 3200)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    assert bridge.wav_audio(encoded).startswith(b"RIFF")


async def test_bridge_auth_identity_and_lease_cleanup(bridge):
    bridge.register(conn("mac-01"))
    bridge.register(conn("mac-02"))
    async with TestClient(TestServer(bridge.create_app())) as client:
        assert (await client.post("/session", json={})).status == 401
        headers = {"Authorization": "Bearer " + "s" * 40}
        request = {"device_ids": ["mac-01", "mac-02"], "enabled": True}
        assert (await client.post("/session", headers=headers, json=request)).status == 200
        assert bridge.muted("mac-01") and bridge.muted("mac-02")
        assert (await client.post("/session", headers=headers, json=request)).status == 409
        assert (
            await client.post(
                "/speak", headers=headers, json={"device_id": "wrong", "text": "hello"}
            )
        ).status == 409
        request["enabled"] = False
        assert (await client.post("/session", headers=headers, json=request)).status == 200
        assert not bridge.muted("mac-01")


def test_overlay_targets_pinned_server_and_compiles():
    spec = importlib.util.spec_from_file_location(
        "server_overlay", ROOT / "laptop/server/install_overlay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    changes = module.files(ROOT / "upstream/xiaozhi-esp32-server/main/xiaozhi-server")
    assert len(changes) == 6
    assert "desk_robot_bridge.register(self)" in changes["core/connection.py"]
    assert "desk_robot_bridge.unregister(handler)" in changes["core/websocket_server.py"]
    for path, source in changes.items():
        compile(source, path, "exec")
