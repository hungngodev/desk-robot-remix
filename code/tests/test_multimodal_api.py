"""Native Mac vision endpoints can be called by Xiaozhi, not used to mint motion."""
import hashlib
import hmac
import json
import secrets
import time

import pytest
from desk_robot.api import create_app
from fastapi.testclient import TestClient


def _signed_tool_headers(settings, tokens, robot_id, path, generation, monkeypatch):
    """Mint an independent, one-use Xiaozhi receipt for a real Mac route."""
    robot = settings.robot(robot_id)
    if not robot.device_id:
        robot.device_id = f"test-{robot_id}-head"
    speech_token = "s" * 40
    monkeypatch.setenv(settings.speech_bridge_token_env, speech_token)
    path = path.partition("?")[0]
    issued_us = time.time_ns() // 1000
    receipt_id = secrets.token_hex(16)
    message = json.dumps(
        [1, robot_id, robot.device_id, generation, "GET", path,
         issued_us, receipt_id],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    signature = hmac.new(
        speech_token.encode(), message, hashlib.sha256,
    ).hexdigest()
    return {
        "Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"],
        "X-Desk-Robot-Tool-Receipt": "1",
        "X-Desk-Robot-Tool-Receipt-Id": receipt_id,
        "X-Desk-Robot-Tool-Receipt-At-Us": str(issued_us),
        "X-Desk-Robot-Tool-Receipt-Device": robot.device_id,
        "X-Desk-Robot-Tool-Receipt-Generation": str(generation),
        "X-Desk-Robot-Tool-Receipt-Signature": signature,
    }


def test_manual_raw_camera_requires_operator_token(settings, tokens):
    """Xiaozhi can request bounded model observations, not raw JPEG access."""
    from types import SimpleNamespace

    jpeg = bytes.fromhex("ffd8") + b"private-image" + bytes.fromhex("ffd9")
    calls = []

    class Head:
        async def snapshot(self):
            calls.append("operator_snapshot")
            return jpeg

    async def noop():
        pass

    robot_id = settings.robots[0].id
    coordinator = SimpleNamespace(
        robot=lambda robot: settings.robot(robot),
        heads={robot_id: Head()},
    )
    runtime = SimpleNamespace(
        coordinator=coordinator, start=noop, close=noop,
    )
    route = f"/v1/robots/{robot_id}/camera.jpg"
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        assert client.get(route, headers=tool).status_code == 403
        assert client.get(route).status_code == 401
        assert calls == []
        response = client.get(route, headers=operator)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == jpeg
        assert calls == ["operator_snapshot"]


def test_mac_existing_ollama_selects_only_consented_readonly_tools(
    settings, tokens,
):
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    robot = settings.robots[0].id

    class Model:
        def __init__(self):
            self.calls = []

        async def reply(self, history):
            self.calls.append(history)
            return json.dumps({"tools": [
                {"route": "move"}, {"route": "look"}, {"route": "status"},
                {"route": "voice-context"}, {"route": "charge"},
            ]})

    model = Model()

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=model),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        request = {"transcript": "Could you inspect the desk and battery?"}
        response = client.post(url, headers=headers, json=request)
        assert response.status_code == 200
        body = response.json()
        assert body["robot_id"] == robot
        assert [tool["route"] for tool in body["tools"]] == [
            "look", "power-status",
        ]
        assert body["tools"][0]["payload"] == {
            "question": request["transcript"]
        }
        assert body["tools"][1]["payload"] == {}
        # Model emitted generic status, but the user asked about battery.
        # The Mac must select real WROOM fuel telemetry rather than guess.
        assert body["model_can_arm_motors"] is False
        assert body["motor_authorized"] is False
        assert body["charging_authorized"] is False
        assert body["untrusted_model_selection"] is True
        assert model.calls
        assert "Never propose physical commands" in model.calls[0][0]["content"]
        assert request["transcript"] in model.calls[0][1]["content"]
        assert client.post(url, json=request).status_code == 401
        assert client.post(
            "/v1/pet/unknown-head/plan-readonly", headers=headers,
            json=request,
        ).status_code == 404
        settings.voice_vision_tools_enabled = False
        cam_off = client.post(url, headers=headers, json=request)
        assert cam_off.status_code == 200
        assert [tool["route"] for tool in cam_off.json()["tools"]] == [
            "power-status",
        ]
        visual_only = {"transcript": "Could you inspect the desk?"}
        visual_resp = client.post(url, headers=headers, json=visual_only)
        assert visual_resp.status_code == 200
        assert visual_resp.json()["tools"] == []



def test_semantic_planner_preserves_three_explicit_observation_intents(
    settings, tokens,
):
    """Mac may select all three native-supported read-only observations."""
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id
    question = "Could you inspect the desk and battery level and temperature?"

    class Model:
        async def reply(self, history):
            return json.dumps({"tools": [
                {"route": "look"}, {"route": "power-status"},
                {"route": "aux-status"},
            ]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        reply = client.post(
            f"/v1/pet/{robot}/plan-readonly", headers=headers,
            json={"transcript": question},
        )
        assert reply.status_code == 200
        result = reply.json()
        assert [item["route"] for item in result["tools"]] == [
            "look", "power-status", "aux-status",
        ]
        assert result["tools"][0]["payload"] == {"question": question}
        assert result["motor_authorized"] is False
        assert result["charging_authorized"] is False



def test_semantic_planner_keeps_explicit_safety_status_with_battery(
    settings, tokens,
):
    """An explicit safety request is not a second battery estimate."""
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id

    class Model:
        async def reply(self, history):
            return json.dumps({"tools": [
                {"route": "status"}, {"route": "power-status"},
            ]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        both = client.post(url, headers=headers, json={
            "transcript": "Check your battery and check your safety status",
        })
        assert both.status_code == 200
        assert [tool["route"] for tool in both.json()["tools"]] == [
            "status", "power-status",
        ]
        battery_only = client.post(url, headers=headers, json={
            "transcript": "Check your battery level",
        })
        assert battery_only.status_code == 200
        assert [tool["route"] for tool in battery_only.json()["tools"]] == [
            "power-status",
        ]
        battery_status = client.post(url, headers=headers, json={
            "transcript": "Check your battery status",
        })
        assert battery_status.status_code == 200
        assert [tool["route"] for tool in battery_status.json()["tools"]] == [
            "power-status",
        ]
        assert both.json()["motor_authorized"] is False



def test_native_context_and_ollama_planner_exclude_revoked_visual_tool_text(
    settings, tokens,
):
    """Camera opt-out revokes a completed visual_look while WROOM faults stay."""
    import json
    import time
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    ids = [robot.id for robot in settings.robots]
    hub = CameraFrameHub(ids)
    hub.remember_tool(
        ids[0], "visual_look", "PRIVATE_RED_KEY_BESIDE_MUG",
        time.monotonic(),
    )
    hub.notify(ids[0], "safety_fault", time.monotonic())

    class Model:
        def __init__(self):
            self.prompts = []

        async def reply(self, history):
            self.prompts.append(str(history))
            return json.dumps({"tools": [{"route": "status"}]})

    async def noop():
        pass

    model = Model()
    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot, jobs={}),
        conversation=SimpleNamespace(chat=model),
        multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    live_url = f"/v1/pet/{ids[0]}/interaction-context"
    plan_url = f"/v1/pet/{ids[0]}/plan-readonly"
    req = {"transcript": "What is your safety status?"}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        on = client.get(live_url, headers=headers)
        assert on.status_code == 200
        assert "PRIVATE_RED_KEY_BESIDE_MUG" in on.json()["model_context"]
        assert any(item["kind"] == "safety_fault"
                   for item in on.json()["current_interaction_timeline"])
        plan_on = client.post(plan_url, headers=headers, json=req)
        assert plan_on.status_code == 200
        assert "PRIVATE_RED_KEY_BESIDE_MUG" in model.prompts[-1]

        settings.voice_vision_tools_enabled = False
        off = client.get(live_url, headers=headers)
        assert off.status_code == 200
        assert "PRIVATE_RED_KEY_BESIDE_MUG" not in str(off.json())
        assert any(item["kind"] == "safety_fault"
                   for item in off.json()["current_interaction_timeline"])
        peer = client.get(
            f"/v1/pet/{ids[1]}/interaction-context", headers=headers,
        )
        assert peer.status_code == 200
        assert "PRIVATE_RED_KEY_BESIDE_MUG" not in str(peer.json())
        plan_off = client.post(plan_url, headers=headers, json=req)
        assert plan_off.status_code == 200
        assert [tool["route"] for tool in plan_off.json()["tools"]] == ["status"]
        assert "PRIVATE_RED_KEY_BESIDE_MUG" not in model.prompts[-1]
        # Preserve the bounded WROOM safety warning even after camera opt-out.
        assert "WROOM reported latched safety fault" in model.prompts[-1]
        assert "do not drive" in model.prompts[-1]


@pytest.mark.parametrize("revocation", [
    "live", "memory", "derived_live", "derived_reenabled",
])
def test_mac_semantic_planner_discards_revoked_context_during_model_decision(
    settings, tokens, revocation,
):
    """An in-flight Ollama reply cannot publish an opt-out tool plan."""
    import json
    import time
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraEvidence, CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    robot = settings.robots[0].id
    hub = CameraFrameHub([item.id for item in settings.robots])
    if revocation == "memory":
        hub.remember_tool(
            robot, "memory_recall", "A private historical personal preference",
            time.monotonic(),
        )
    elif revocation in ("derived_live", "derived_reenabled"):
        hub.remember_tool(
            robot, "visual_look", "PRIVATE_RED_KEY_DERIVED_FROM_CAMERA",
            time.monotonic(),
        )
    else:
        hub.frames[robot].append(
            CameraEvidence(b"\xff\xd8fake", time.monotonic(), 0.05, "proactive"),
        )

    class Model:
        def __init__(self):
            self.calls = 0

        async def reply(self, history):
            self.calls += 1
            if revocation == "memory":
                assert "private historical" not in str(history)
                settings.voice_memory_tools_enabled = False
            else:
                if revocation in ("derived_live", "derived_reenabled"):
                    assert "PRIVATE_RED_KEY_DERIVED_FROM_CAMERA" in str(history)
                settings.voice_vision_tools_enabled = False
                if revocation == "derived_reenabled":
                    settings.voice_vision_tools_enabled = True
            return json.dumps({"tools": [{"route": "status"}]})

    async def noop():
        pass

    model = Model()
    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=model),
        multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.post(
            f"/v1/pet/{robot}/plan-readonly", headers=headers,
            json={"transcript": "What is your safety status?"},
        )
    assert model.calls == 1
    if revocation == "memory":
        # No private receipt was admitted to this unrelated safety plan.
        assert response.status_code == 200
        assert [item["route"] for item in response.json()["tools"]] == ["status"]
    elif revocation == "derived_reenabled":
        assert settings.voice_vision_tools_enabled is True
        assert settings.camera_consent_generation == 1
        assert response.status_code == 409
        assert "grant changed during planning" in response.json()["detail"]
    else:
        assert response.status_code == 403
        assert "revoked during planning" in response.json()["detail"]


@pytest.mark.parametrize("grant_change,expected_status", [
    ("unchanged", 200), ("revoked", 403), ("regranted", 409),
])
def test_room_station_context_plan_uses_original_permission_epoch(
    settings, tokens, grant_change, expected_status,
):
    """Old room data cannot authorize a plan after operator opt out/in."""
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.room_station_enabled = True
    settings.room_station_port = "/dev/tty.usbmodem-room"
    settings.room_station_context_enabled = True
    initial_epoch = settings.room_station_consent_generation
    robot = settings.robots[0].id
    timeline = [{
        "channel": "room_station",
        "kind": "climate",
        "content": "ROOM_SENSOR_PRIVATE_TEST_READING",
        "shared_not_robot_eyewitness": True,
        "identity_verified": False,
    }]
    seen = []

    class Model:
        async def reply(self, history):
            seen.append(history)
            assert "ROOM_SENSOR_PRIVATE_TEST_READING" in str(history)
            if grant_change != "unchanged":
                settings.room_station_context_enabled = False
                if grant_change == "regranted":
                    settings.room_station_context_enabled = True
            return json.dumps({"tools": [{"route": "status"}]})

    async def noop():
        pass

    hub = SimpleNamespace(interaction_timeline=lambda *args, **kwargs: timeline)
    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.post(
            f"/v1/pet/{robot}/plan-readonly", headers=headers,
            json={"transcript": "What is your safety status?"},
        )
    assert len(seen) == 1
    assert response.status_code == expected_status
    assert settings.room_station_consent_generation == (
        initial_epoch + (grant_change != "unchanged")
    )
    if grant_change == "unchanged":
        assert [item["route"] for item in response.json()["tools"]] == ["status"]
    else:
        assert "room station" in response.json()["detail"].lower()


@pytest.mark.parametrize("grant_change,expected_status", [
    ("unchanged", 200), ("revoked", 403), ("regranted", 409),
])
def test_semantic_planner_private_memory_grant_survives_no_revoke(
    settings, tokens, grant_change, expected_status,
):
    """Fresh recall planning is grant-fenced without cached private text."""
    import json
    import time
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    original_generation = settings.voice_memory_consent_generation
    robot = settings.robots[0].id
    hub = CameraFrameHub([r.id for r in settings.robots])
    hub.remember_tool(
        robot, "memory_recall", "PRIVATE_PRE_REVOKE_RECALL",
        time.monotonic(),
    )

    class Model:
        async def reply(self, history):
            assert "PRIVATE_PRE_REVOKE_RECALL" not in str(history)
            if grant_change != "unchanged":
                settings.voice_memory_tools_enabled = False
                if grant_change == "regranted":
                    settings.voice_memory_tools_enabled = True
            return json.dumps({"tools": [{"route": "voice-context"}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.post(
            f"/v1/pet/{robot}/plan-readonly", headers=headers,
            json={"transcript": "What do you remember about our earlier conversation?"},
        )
    assert response.status_code == expected_status
    assert settings.voice_memory_consent_generation == (
        original_generation + (grant_change != "unchanged")
    )
    if expected_status == 200:
        assert [item["route"] for item in response.json()["tools"]] == [
            "voice-context",
        ]
    else:
        assert "private memory" in response.json()["detail"].lower()


def test_semantic_planner_cannot_gain_memory_permission_mid_inference(
    settings, tokens,
):
    """Enabling private memory while a plan waits is a new authorization."""
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = False
    robot = settings.robots[0].id

    class Model:
        async def reply(self, history):
            settings.voice_memory_tools_enabled = True
            return '{"tools":[{"route":"voice-context"}]}'

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.post(
            f"/v1/pet/{robot}/plan-readonly", headers=headers,
            json={"transcript": "What do you remember about our earlier conversation?"},
        )
    assert response.status_code == 200
    assert response.json()["tools"] == []


def test_mac_semantic_planner_rejects_late_plan_after_new_human_vad(
    settings, tokens,
):
    """A delayed Ollama selection cannot cross the live Mac turn epoch."""
    import asyncio
    import json
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id
    ids = [item.id for item in settings.robots]
    visual = SimpleNamespace(
        hub=CameraFrameHub(ids), _turn_epoch={rid: 5 for rid in ids},
    )

    class Model:
        calls = 0

        async def reply(self, history):
            self.calls += 1
            await asyncio.sleep(0)
            if self.calls == 1:
                # New authenticated VAD on another pet also advances the
                # fleet turn epoch of this robot in the real orchestrator.
                visual._turn_epoch[robot] += 1
            return json.dumps({"tools": [{"route": "look"}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=visual, start=noop, close=noop,
    )
    headers = {
        "Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"],
    }
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        body = {"transcript": "What do you see on my desk?"}
        stale = client.post(url, headers=headers, json=body)
        assert stale.status_code == 409
        assert "superseded" in stale.json()["detail"]
        current = client.post(url, headers=headers, json=body)
        assert current.status_code == 200
        assert current.json()["tools"] == [{
            "route": "look", "payload": {"question": body["transcript"]},
        }]
        assert current.json()["motor_authorized"] is False


def test_mac_semantic_planner_ignores_nonstring_tool_names_without_500(
    settings, tokens,
):
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    robot = settings.robots[0].id

    class Model:
        async def reply(self, history):
            return json.dumps({"tools": [
                {"route": ["move"]},
                {"route": {"name": "stop"}},
                {"route": "status"},
            ]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        result = client.post(
            f"/v1/pet/{robot}/plan-readonly",
            headers=headers, json={"transcript": "Check my battery status"},
        )
    assert result.status_code == 200
    assert result.json()["tools"] == [
        {"route": "power-status", "payload": {}},
    ]
    assert result.json()["motor_authorized"] is False
    assert result.json()["charging_authorized"] is False


def test_mac_semantic_tool_plan_fail_closed_without_ollama_or_memory_consent(
    settings, tokens,
):
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    robot = settings.robots[0].id

    class Model:
        async def reply(self, history):
            return '{"tools":[{"route":"voice-context"},' \
                '{"route":"stop"},{"route":"charging"},{"route":"look"}]}'

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        result = client.post(url, headers=headers, json={
            "transcript": "What did I say earlier?"
        })
        assert result.status_code == 200
        assert result.json()["tools"] == []
        # Without durable-memory consent, an incorrect Ollama suggestion
        # cannot turn a recall question into a camera request.
        settings.voice_memory_tools_enabled = True
        allowed = client.post(url, headers=headers, json={
            "transcript": "What did I say earlier?"
        })
        assert [tool["route"] for tool in allowed.json()["tools"]] == [
            "voice-context",
        ]
        photo_memory = client.post(url, headers=headers, json={
            "transcript": "What did I tell you about the photo?"
        })
        assert [tool["route"] for tool in photo_memory.json()["tools"]] == [
            "voice-context",
        ]
        compound = client.post(url, headers=headers, json={
            "transcript": "What did I say earlier and can you look at the desk?"
        })
        assert [tool["route"] for tool in compound.json()["tools"]] == [
            "voice-context", "look",
        ]
        # Memory permission alone is neither camera permission nor movement.
        assert result.json()["model_can_arm_motors"] is False
        assert client.post(url, headers=headers, json={
            "transcript": "a" * 281
        }).status_code == 422



def test_semantic_planner_memory_consent_does_not_authorize_unrelated_recall(
    settings, tokens,
):
    """Opted-in private history still needs an actual user recall request."""
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    robot = settings.robots[0].id

    class OvereagerModel:
        async def reply(self, history):
            return json.dumps({"tools": [{"route": "voice-context"}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=OvereagerModel()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        for question in (
            "Can you check how your battery is doing?",
            "What happened just now on your desk?",
            "How are your sensors?",
            "What is in your camera right now?",
        ):
            reply = client.post(
                url, headers=headers, json={"transcript": question},
            )
            assert reply.status_code == 200
            assert reply.json()["tools"] == []
            assert reply.json()["motor_authorized"] is False
        for question in (
            "What did I tell you about that key?",
            "Can you recall what we discussed?",
            "Tell me about our previous conversation",
        ):
            reply = client.post(
                url, headers=headers, json={"transcript": question},
            )
            assert reply.status_code == 200
            assert reply.json()["tools"] == [{
                "route": "voice-context", "payload": {"question": question}
            }]



def test_semantic_planner_does_not_expand_user_request_into_other_hardware_reads(
    settings, tokens,
):
    """Ollama's tool suggestion is not permission to capture unrelated sensors."""
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id

    class OvereagerModel:
        async def reply(self, history):
            return json.dumps({"tools": [
                {"route": "look"}, {"route": "power-status"},
                {"route": "aux-status"},
            ]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=OvereagerModel()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        cases = (
            ("What is your temperature reading?", ["aux-status"]),
            ("What do you see in the camera?", ["look"]),
            ("What is your battery level?", ["power-status"]),
            ("Show your sensor readings", ["aux-status"]),
            ("What is on the desk and my battery level?",
             ["look", "power-status"]),
        )
        for transcript, expected in cases:
            reply = client.post(
                url, headers=headers, json={"transcript": transcript},
            )
            assert reply.status_code == 200
            assert [x["route"] for x in reply.json()["tools"]] == expected
            assert reply.json()["motor_authorized"] is False
            assert reply.json()["charging_authorized"] is False



def test_semantic_planner_requires_explicit_body_pickup_and_interaction_intent(
    settings, tokens,
):
    """Read-only access is scoped to the user's actual requested evidence."""
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id

    class Model:
        async def reply(self, history):
            return json.dumps({"tools": [
                {"route": "latest-pickup"}, {"route": "interaction-context"},
                {"route": "status"},
            ]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    cases = (
        ("How is your day?", []),
        ("Can you pick up this key?", []),
        ("What is your safety status?", ["status"]),
        ("Is the pickup job done?", ["latest-pickup"]),
        ("Did you pick up that key already?", ["latest-pickup"]),
        ("What just happened?", ["interaction-context"]),
        ("Did I touch you?", ["interaction-context"]),
    )
    with TestClient(create_app(settings, runtime=runtime)) as client:
        for transcript, expected in cases:
            answer = client.post(
                f"/v1/pet/{robot}/plan-readonly", headers=headers,
                json={"transcript": transcript},
            )
            assert answer.status_code == 200
            assert [x["route"] for x in answer.json()["tools"]] == expected
            assert answer.json()["motor_authorized"] is False


async def test_existing_ollama_semantic_planner_uses_strict_json_schema(
    settings,
):
    import json

    import httpx
    from desk_robot.conversation import OllamaChat

    captured = []

    def reply(request):
        captured.append(request)
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content":
                        '{"tools":[{"route":"look"},{"route":"status"}]}'},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        planner = OllamaChat(settings, http)
        result = await planner.readonly_tool_plan([
            {"role": "system", "content": "Choose only read-only tools."},
            {"role": "user", "content": "Can you check the camera and battery?"},
        ])
    assert json.loads(result)["tools"] == [
        {"route": "look"}, {"route": "status"},
    ]
    assert len(captured) == 1
    data = json.loads(captured[0].content)
    assert data["stream"] is False
    assert data["think"] is False
    assert data["options"]["temperature"] == 0
    assert data["format"]["type"] == "object"
    assert data["format"]["properties"]["tools"]["maxItems"] == 3
    routes = data["format"]["properties"]["tools"]["items"]["properties"]["route"]["enum"]
    assert set(routes) == {
        "look", "status", "power-status", "aux-status", "latest-pickup",
        "interaction-context", "voice-context",
    }
    assert not {"move", "stop", "pickup", "enable", "charge"} & set(routes)


def test_real_wroom_power_tool_reports_raw_gauge_only_without_charging_claim(
    settings, tokens,
):
    from types import SimpleNamespace

    settings.mode = "hardware"
    robot = settings.robots[0].id

    class RealAux:
        def __init__(self):
            self.raw = {
                "robot_id": robot,
                "power": {
                    "fuel_valid": True, "fuel_seq": 7, "cell_mv": 3875,
                    "soc_centi": 6275, "current_calibrated": False,
                },
            }

        async def aux_status(self):
            return self.raw

    head = RealAux()

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid),
            heads={robot: head},
        ),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/power-status"
        body = client.get(url, headers=headers)
        assert body.status_code == 200
        data = body.json()
        assert data["robot_id"] == robot
        assert data["gauge_available"] is True
        assert data["reported_cell_mv"] == 3875
        assert data["reported_soc_centi"] == 6275
        assert data["raw_fuel_acquisition_seq"] == 7
        assert data["sample_freshness_verified"] is False
        assert data["charging_verified"] is False
        assert data["battery_capacity_verified"] is False
        assert data["motor_authorized"] is False
        assert data["charging_authorized"] is False
        assert client.get(url).status_code == 401
        # Legacy read-only payloads lacking a completed acquisition identity
        # cannot claim a current numeric battery estimate.
        head.raw["power"].pop("fuel_seq")
        unsequenced = client.get(url, headers=headers).json()
        assert unsequenced["gauge_available"] is False
        assert unsequenced["reported_cell_mv"] is None
        assert unsequenced["raw_fuel_acquisition_seq"] is None
        head.raw = {
            "robot_id": robot,
            "power": {
                "fuel_valid": False, "cell_mv": 0,
                "soc_centi": 0,
            },
        }
        absent = client.get(url, headers=headers).json()
        assert absent["gauge_available"] is False
        assert absent["reported_cell_mv"] is None
        assert absent["reported_soc_centi"] is None
        head.raw = {"robot_id": "robot-02", "power": {
            "fuel_valid": True, "cell_mv": 3800, "soc_centi": 6000
        }}
        invalid = client.get(url, headers=headers)
        # A foreign WROOM reading is a hardware source failure, not a valid
        # current robot measurement nor a request-level motor conflict.
        assert invalid.status_code == 503
        assert "robot identity mismatch" in invalid.json()["error"]
        settings.mode = "simulation"
        assert client.get(url, headers=headers).status_code == 403


def test_power_tool_does_not_write_old_sensor_receipt_into_new_human_turn(
    settings, tokens, monkeypatch,
):
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    robot = settings.robots[0].id
    hub = CameraFrameHub([robot])
    visual = SimpleNamespace(_turn_epoch={robot: 10}, hub=hub)

    class SlowSource:
        async def aux_status(self):
            # Simulate the next authenticated VAD occurring while a WROOM
            # auxiliary read is in flight. The old receipt must be dropped.
            visual._turn_epoch[robot] = 11
            return {
                "robot_id": robot,
                "power": {
                    "fuel_valid": True, "fuel_seq": 11,
                    "cell_mv": 3820, "soc_centi": 5400,
                },
            }

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid),
            heads={robot: SlowSource()},
        ),
        multimodal=visual, start=noop, close=noop,
        _voice_turn_generations={robot: 10},
        voice_events=SimpleNamespace(monitor_ready=True, _event_generation=0),
        pet=SimpleNamespace(voice_monitor_ready=True),
    )
    url = f"/v1/pet/{robot}/power-status"
    headers = _signed_tool_headers(
        settings, tokens, robot, url, 10, monkeypatch,
    )
    with TestClient(create_app(settings, runtime=runtime)) as client:
        result = client.get(url, headers=headers)
        assert result.status_code == 409
        assert "superseded" in result.json()["detail"]
        assert visual._turn_epoch[robot] == 11
        assert hub.recent_tool_context(robot, __import__("time").monotonic()) == []


@pytest.mark.parametrize("lost", [False, True])
def test_xiaozhi_readonly_status_and_job_receipts_share_live_context_only(
    settings, tokens, monkeypatch, lost,
):
    import time
    from types import SimpleNamespace

    from desk_robot.brain_context import compose_brain_context
    from desk_robot.multimodal import CameraFrameHub

    ids = [robot.id for robot in settings.robots]
    hub = CameraFrameHub(ids)

    class Head:
        reported_id = ids[0]

        async def status(self):
            return {
                "robot_id": self.reported_id, "backend": "stepper_28byj48",
                "armed": False, "safety": {"fault": "none"},
            }

    job_id = "pickup123" * 4
    state = "failed" if lost else "running"
    job = SimpleNamespace(
        id=job_id, robot_id=ids[0], kind="pickup", state=state,
        events=["object_lost: jaw contact below threshold; hold unverified"] if lost else [],
        data=lambda: {
            "id": job_id, "robot_id": ids[0],
            "kind": "pickup", "state": state,
            "physical_grasp_verified": False,
        },
    )
    head = Head()
    coord = SimpleNamespace(
        robot=lambda rid: settings.robot(rid),
        heads={ids[0]: head},
        jobs={job_id: job},
    )
    runtime = SimpleNamespace(
        coordinator=coord,
        multimodal=SimpleNamespace(hub=hub, _turn_epoch={rid: 0 for rid in ids}),
        _voice_turn_generations={rid: 0 for rid in ids},
        voice_events=SimpleNamespace(monitor_ready=True, _event_generation=0),
        pet=SimpleNamespace(voice_monitor_ready=True),
    )

    async def start():
        pass

    async def close():
        pass

    runtime.start, runtime.close = start, close
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        status_url = f"/v1/robots/{ids[0]}/status"
        job_url = f"/v1/robots/{ids[0]}/jobs/latest-pickup"
        assert client.get(status_url, headers=tool).status_code == 200
        assert hub.recent_tool_context(ids[0], time.monotonic()) == []
        assert client.get(status_url, headers=_signed_tool_headers(
            settings, tokens, ids[0], status_url, 0, monkeypatch,
        )).status_code == 200
        result = client.get(job_url, headers=_signed_tool_headers(
            settings, tokens, ids[0], job_url, 0, monkeypatch,
        ))
        assert result.status_code == 200
        assert result.json()["state"] == state
        cues = hub.recent_tool_context(ids[0], time.monotonic())
        assert {x["kind"] for x in cues} == {"robot_status", "pickup_status"}
        assert all(x["motor_authorized"] is False for x in cues)
        context = compose_brain_context(
            [], [], hub.interaction_timeline(ids[0], time.monotonic())
        )
        assert "Recent head telemetry" in context.interaction
        loss_phrase = "object_lost: fresh jaw contact low; hold unverified; no retry;"
        assert (loss_phrase in context.interaction) is lost
        hub.tool_history[ids[0]].clear()
        head.reported_id = ids[1]
        assert client.get(status_url, headers=_signed_tool_headers(
            settings, tokens, ids[0], status_url, 0, monkeypatch,
        )).status_code == 503
        assert not hub.tool_history[ids[0]]  # Foreign head is never evidence.
        assert "Mac pickup job receipt, not verified grasp" in context.interaction
        assert hub.recent_tool_context(ids[1], time.monotonic()) == []
        assert client.post(
            f"/v1/robots/{ids[0]}/enable", headers=tool
        ).status_code == 403


def test_tool_token_can_request_visual_evidence_but_not_enable_motors(settings, tokens):
    app = create_app(settings)
    with TestClient(app) as client:
        calls = []

        class Vision:
            async def close(self):
                pass

            def status(self, robot_id):
                return {"robot_id": robot_id, "frames_in_ram": 0,
                        "motor_authorized": False}

            async def look(self, robot_id, question):
                calls.append((robot_id, question))
                return {
                    "robot_id": robot_id,
                    "answer": "I can see a simulated object.",
                    "motor_authorized": False,
                    "charging_authorized": False,
                }

        app.state.runtime.multimodal = Vision()
        path = "/v1/pet/robot-01/look"
        operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
        tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
        assert client.post(path, json={"question": "What do you see?"}).status_code == 401
        result = client.post(path, headers=tool, json={
            "question": "What do you see?"
        })
        assert result.status_code == 200
        assert result.json()["answer"] == "I can see a simulated object."
        assert calls == [("robot-01", "What do you see?")]
        assert client.get("/v1/pet/robot-01/vision-status",
                          headers=operator).status_code == 200
        assert client.post("/v1/robots/robot-01/enable",
                           headers=tool).status_code == 403
        assert client.post(path, headers=tool,
                           json={"question": "x" * 300}).status_code == 422
        assert client.post("/v1/pet/not-a-robot/look", headers=tool,
                           json={"question": "What is there?"}).status_code == 409


def test_native_omni_frame_requires_consent_real_hardware_and_tool_token(settings, tokens):
    import time
    from types import SimpleNamespace

    jpeg = b"\xff\xd8" + b"actualjpeg" + b"\xff\xd9"

    class FakeCamera:
        async def capture(self, robot_id, *, source):
            assert robot_id == "robot-01" and source == "speech"
            return SimpleNamespace(jpeg=jpeg, received_at=time.monotonic())

    class FakeRuntime:
        coordinator = SimpleNamespace(robot=lambda robot_id: (
            SimpleNamespace(id=robot_id) if robot_id == "robot-01"
            else (_ for _ in ()).throw(KeyError(robot_id))
        ))
        multimodal = FakeCamera()

        async def start(self):
            pass

        async def close(self):
            pass

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    app = create_app(settings, runtime=FakeRuntime())
    url = "/v1/pet/robot-01/omni-frame"
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        result = client.get(url, headers=tool)
        assert result.status_code == 200
        assert result.content == jpeg
        assert result.headers["content-type"].startswith("image/jpeg")
        assert result.headers["x-desk-robot-id"] == "robot-01"
        assert int(result.headers["x-desk-camera-receipt-us"]) > 0
        assert result.headers["x-desk-frame-motion-ppm"] == "0"
        assert result.headers["cache-control"] == "no-store"
    settings.voice_vision_tools_enabled = False
    with TestClient(create_app(settings, runtime=FakeRuntime())) as client:
        assert client.get(url, headers=tool).status_code == 403




def test_native_single_frame_rechecks_camera_consent_after_await(settings, tokens):
    import time
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True

    class Camera:
        async def capture(self, robot_id, *, source):
            assert robot_id == "robot-01" and source == "speech"
            settings.voice_vision_tools_enabled = False
            return SimpleNamespace(
                jpeg=b"private frame", received_at=time.monotonic(),
            )

    class Runtime:
        coordinator = SimpleNamespace(robot=lambda rid: settings.robot(rid))
        multimodal = Camera()

        async def start(self):
            pass

        async def close(self):
            pass

    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=Runtime())) as client:
        response = client.get("/v1/pet/robot-01/omni-frame", headers=headers)
    assert response.status_code == 403
    assert b"private frame" not in response.content



def test_native_model_receives_continuous_visual_evidence_without_request_or_vad(
    settings, tokens,
):
    import base64
    import json
    import time
    from types import SimpleNamespace

    class LiveVideo:
        def __init__(self):
            self.subscriptions = 0

        async def native_live_frames(self, robot_id):
            assert robot_id == "robot-01"
            self.subscriptions += 1
            now = time.monotonic()
            yield SimpleNamespace(
                jpeg=b"\xff\xd8" + b"quiet desk" + b"\xff\xd9",
                received_at=now - 0.9, motion_fraction=0.0,
                source="proactive",
            )
            yield SimpleNamespace(
                jpeg=b"\xff\xd8" + b"object moved" + b"\xff\xd9",
                received_at=now, motion_fraction=0.04,
                source="proactive",
            )

    class Runtime:
        coordinator = SimpleNamespace(robot=lambda rid: (
            settings.robot(rid)
        ))
        multimodal = LiveVideo()

        async def start(self):
            pass

        async def close(self):
            pass

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    runtime = Runtime()
    path = "/v1/pet/robot-01/omni-stream"
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        assert client.get(path).status_code == 401
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        lines = [json.loads(x) for x in response.text.splitlines()]
        assert len(lines) == 2
        assert [x["source"] for x in lines] == ["proactive", "proactive"]
        assert [base64.b64decode(x["jpeg_base64"]) for x in lines] == [
            b"\xff\xd8quiet desk\xff\xd9",
            b"\xff\xd8object moved\xff\xd9",
        ]
        assert all(x["motor_authorized"] is False and
                   x["charging_authorized"] is False for x in lines)
        assert lines[0]["camera_receipt_us"] < lines[1]["camera_receipt_us"]
    assert runtime.multimodal.subscriptions == 1
    settings.voice_vision_tools_enabled = False
    with TestClient(create_app(settings, runtime=Runtime())) as client:
        assert client.get(path, headers=headers).status_code == 403



def test_native_visual_stream_cannot_emit_frame_after_consent_revoke_during_socket_check(
    settings, tokens, monkeypatch,
):
    import time
    from types import SimpleNamespace

    from starlette.requests import Request

    class Video:
        async def native_live_frames(self, robot_id):
            assert robot_id == "robot-01"
            yield SimpleNamespace(
                jpeg=b"\xff\xd8" + b"private desk image" + b"\xff\xd9",
                received_at=time.monotonic(), motion_fraction=0.1,
                source="proactive",
            )

    class Runtime:
        coordinator = SimpleNamespace(robot=lambda rid: settings.robot(rid))
        multimodal = Video()

        async def start(self):
            pass

        async def close(self):
            pass

    async def revoke_while_waiting_for_client(_request):
        settings.voice_vision_tools_enabled = False
        return False

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    monkeypatch.setattr(Request, "is_disconnected", revoke_while_waiting_for_client)
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=Runtime())) as client:
        response = client.get("/v1/pet/robot-01/omni-stream", headers=headers)
        assert response.status_code == 200
        assert response.content == b""
    assert settings.voice_vision_tools_enabled is False



def test_native_model_instructions_contain_only_own_pet_persona_without_unapproved_memory(
    settings, tokens,
):
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    pet = settings.robots[0]

    class StubRuntime:
        coordinator = SimpleNamespace(robot=lambda rid: (
            pet if rid == pet.id else (_ for _ in ()).throw(KeyError(rid))
        ))

        async def start(self):
            pass

        async def close(self):
            pass

    with TestClient(create_app(settings, runtime=StubRuntime())) as client:
        tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
        result = client.get(f"/v1/pet/{pet.id}/omni-context", headers=tool)
        assert result.status_code == 200
        body = result.json()
        assert body["robot_id"] == pet.id
        assert pet.persona in body["instructions"]
        assert body["persona"] == pet.persona[:900]
        assert body["memory_enabled"] is False
        assert body["transcript_memory_enabled"] is False
        assert body["model_can_arm_motors"] is False
        assert len(body["instructions"]) <= 2000
        assert client.get(f"/v1/pet/{pet.id}/omni-context").status_code == 401



def test_native_private_memory_revoke_during_sqlite_read_returns_no_secret(
    settings, tokens,
):
    """Startup persona and history tool both recheck consent after awaited I/O."""
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id

    class RevokingMemory:
        def recent(self, robot_id, *, limit):
            assert robot_id == robot
            settings.voice_memory_tools_enabled = False
            return []

        def core_facts(self, robot_id, *, limit):
            assert robot_id == robot
            return []

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=RevokingMemory(), multimodal=None,
        conversation=SimpleNamespace(_private_memory_generation={robot: 0}),
        start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        for endpoint in ("omni-context", "voice-context"):
            settings.voice_memory_tools_enabled = True
            response = client.get(
                f"/v1/pet/{robot}/{endpoint}", headers=headers,
            )
            assert response.status_code == 403
            assert "instructions" not in response.text
            assert "core_facts" not in response.text
            assert settings.voice_memory_tools_enabled is False


def test_native_asr_memory_requires_independent_consent_and_deduplicates(
    settings, tokens, tmp_path,
):
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore

    pet = settings.robots[0]
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    memory = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])

    class StubRuntime:
        coordinator = SimpleNamespace(robot=lambda robot_id: (
            pet if robot_id == pet.id
            else (_ for _ in ()).throw(KeyError(robot_id))
        ))

        async def start(self):
            pass

        async def close(self):
            pass

    runtime = StubRuntime()
    runtime.memory = memory
    url = f"/v1/pet/{pet.id}/omni-heard"
    source_stamp_us = time.monotonic_ns() // 1000
    request = {
        "event_id": "omni_" + "a" * 12 + "_" + "b" * 20,
        "transcript": "I put a key beside the robot",
        "accepted_at_us": source_stamp_us,
        "audio_committed_at_us": source_stamp_us,
    }
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        assert client.post(url, json=request).status_code == 401
        first = client.post(url, headers=tool, json=request)
        assert first.status_code == 200
        assert first.json()["stored"] is True
        assert first.json()["retention_consent_enabled"] is True
        assert first.json()["episode_persisted"] is True
        assert first.json()["retained_on_disk"] is True
        assert first.json()["motor_authorized"] is False
        assert first.json()["speaker_identity_verified"] is False
        second = client.post(url, headers=tool, json=request)
        assert second.status_code == 200
        assert second.json()["stored"] is False
        assert second.json()["retention_consent_enabled"] is True
        assert second.json()["retained_on_disk"] is True
        altered = client.post(url, headers=tool, json={
            **request, "transcript": "A different unrecoverable transcript",
        })
        assert altered.status_code == 200
        assert altered.json()["stored"] is False
        assert altered.json()["retention_consent_enabled"] is True
        assert altered.json()["retained_on_disk"] is False
        assert client.post(url, headers=tool, json={
            "event_id": "../bad", "transcript": "Move the robot"
        }).status_code == 422
        assert len(memory.recent(pet.id)) == 1
        heard = memory.recent(pet.id)[0]
        assert heard.kind == "heard_human"
        assert heard.witnessed is True
        assert heard.confidence == 0.6
        assert "key beside the robot" in heard.summary
        settings.voice_transcript_memory_enabled = False
        assert client.post(url, headers=tool, json=request).status_code == 403


def test_native_asr_tombstone_and_immediate_eviction_do_not_claim_persistence(
    settings, tokens, tmp_path,
):
    import time
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = False
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot = settings.robots[0].id
    memory = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=memory, multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    url = f"/v1/pet/{robot}/omni-heard"
    event_id = "omni_" + "a" * 12 + "_" + "c" * 20
    source_stamp_us = time.monotonic_ns() // 1000
    payload = {"event_id": event_id, "transcript": "The red key is on the desk",
               "accepted_at_us": source_stamp_us,
               "audio_committed_at_us": source_stamp_us}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        stored = client.post(url, headers=headers, json=payload)
        assert stored.status_code == 200
        assert stored.json()["retained_on_disk"] is True
        assert memory.forget_episode(robot, event_id)
        replay = client.post(url, headers=headers, json=payload)
        assert replay.status_code == 200
        assert replay.json()["stored"] is False
        assert replay.json()["retention_consent_enabled"] is True
        assert replay.json()["retained_on_disk"] is False
        assert replay.json()["episode_persisted"] is False
        assert memory.get_episode(robot, event_id) is None

        now = time.time()
        for index in range(250):
            assert memory.remember(
                robot, f"seed_{index:03d}", f"Recent event {index}",
                kind="heard_human", source_robot=robot, witnessed=True,
                observed_at=now,
            )
        old_id = "omni_" + "d" * 12 + "_" + "e" * 20
        original_remember = memory.remember

        def immediately_old(*args, **kwargs):
            return original_remember(
                *args, **{**kwargs, "observed_at": now - 3600}
            )

        memory.remember = immediately_old
        eviction_source_us = time.monotonic_ns() // 1000
        evicted = client.post(url, headers=headers, json={
            "event_id": old_id, "transcript": "An old discarded observation",
            "accepted_at_us": eviction_source_us,
            "audio_committed_at_us": eviction_source_us,
        })
        assert evicted.status_code == 200
        assert evicted.json()["stored"] is False
        assert evicted.json()["retention_consent_enabled"] is True
        assert evicted.json()["retained_on_disk"] is False
        assert evicted.json()["episode_persisted"] is False
        assert memory.get_episode(robot, old_id) is None


def test_native_queued_asr_cannot_impersonate_a_newer_human_vad(
    settings, tokens, tmp_path,
):
    """The real HTTP route must reject an ASR accepted before newer VAD."""
    from types import SimpleNamespace

    from desk_robot.attention import AttentionLedger
    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    settings.voice_transcript_memory_enabled = False
    robot = settings.robots[0].id
    ids = [entry.id for entry in settings.robots]
    hub = CameraFrameHub(ids)
    attention = AttentionLedger(ids)
    admitted = []
    actual_remember = hub.remember_heard

    def trace_remember(*args, **kwargs):
        admitted.append(args[1])
        return actual_remember(*args, **kwargs)

    hub.remember_heard = trace_remember

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=MemoryStore(tmp_path / "private", ids),
        multimodal=SimpleNamespace(hub=hub),
        attention=attention, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    url = f"/v1/pet/{robot}/omni-heard"
    now = time.monotonic()
    attention.human_started(robot, now - 0.25)
    stale = {
        "event_id": "omni_" + "a" * 12 + "_" + "b" * 20,
        "transcript": "Old question about the key",
        # A model acceptance after the newer VAD cannot retime older PCM.
        "accepted_at_us": time.monotonic_ns() // 1000,
        "audio_committed_at_us": int((now - 0.50) * 1_000_000),
    }
    with TestClient(create_app(settings, runtime=runtime)) as client:
        old = client.post(url, json=stale, headers=headers)
        assert old.status_code == 200
        assert old.json()["ephemeral_context_added"] is False
        assert admitted == []  # no transient read during a slow disk write
        assert not hub.heard_history[robot]
        assert not attention.timeline(robot, time.monotonic())

        current_stamp_us = time.monotonic_ns() // 1000
        current = {
            "event_id": "omni_" + "a" * 12 + "_" + "c" * 20,
            "transcript": "New question about the robot",
            "accepted_at_us": current_stamp_us,
            "audio_committed_at_us": current_stamp_us,
        }
        fresh = client.post(url, json=current, headers=headers)
        assert fresh.status_code == 200
        assert fresh.json()["ephemeral_context_added"] is True
        assert len(admitted) == 1
        assert len(hub.heard_history[robot]) == 1
        assert hub.heard_history[robot][0][1] == current["transcript"]
        assert any(
            "Newer uncertain ASR" in str(cue)
            for cue in attention.timeline(robot, time.monotonic())
        )
        live_url = f"/v1/pet/{robot}/interaction-context"
        allowed = client.get(live_url, headers=headers)
        assert allowed.status_code == 200
        assert "New question about the robot" in allowed.json()["model_context"]
        # Both transient hub ASR and attention copies belong to one grant.
        settings.voice_vision_tools_enabled = False
        disabled = client.get(live_url, headers=headers)
        assert disabled.status_code == 200
        assert "New question about the robot" not in str(disabled.json())
        settings.voice_vision_tools_enabled = True
        regranted = client.get(live_url, headers=headers)
        assert regranted.status_code == 200
        assert "New question about the robot" not in str(regranted.json())
        revoked = client.post(url, headers=headers, json={
            **current,
            "event_id": "omni_" + "a" * 12 + "_" + "e" * 20,
        })
        assert revoked.status_code == 200
        assert revoked.json()["ephemeral_context_added"] is False
        assert len(admitted) == 1
        for bad_stamp in (
            int((now - 120) * 1_000_000),
            int((time.monotonic() + 2) * 1_000_000),
        ):
            invalid = client.post(
                url, headers=headers,
                json={**current,
                      "event_id": "omni_" + "a" * 12 + "_" + "d" * 20,
                      "accepted_at_us": bad_stamp},
            )
            assert invalid.status_code == 409


def test_native_asr_delete_keeps_live_ordering_fence(settings, tokens, tmp_path):
    """An operator deletion cannot promote a delayed older ASR into live context."""
    from types import SimpleNamespace

    from desk_robot.attention import AttentionLedger
    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    settings.voice_transcript_memory_enabled = False
    robot = settings.robots[0].id
    ids = [entry.id for entry in settings.robots]
    hub = CameraFrameHub(ids)
    attention = AttentionLedger(ids)
    memory = MemoryStore(tmp_path / "private", ids)

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot), memory=memory,
        multimodal=SimpleNamespace(hub=hub), attention=attention,
        start=noop, close=noop,
    )
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    url = f"/v1/pet/{robot}/omni-heard"
    deleted = "omni_" + "a" * 12 + "_" + "a" * 20
    delayed = "omni_" + "a" * 12 + "_" + "b" * 20
    fresh = "omni_" + "a" * 12 + "_" + "c" * 20

    def receipt(event, transcript, audio_us):
        return {
            "event_id": event, "transcript": transcript,
            "audio_committed_at_us": audio_us,
            "accepted_at_us": time.monotonic_ns() // 1000,
        }

    with TestClient(create_app(settings, runtime=runtime)) as client:
        newest_us = time.monotonic_ns() // 1000
        old_us = newest_us - 1
        attention.human_started(robot, old_us / 1_000_000 - 0.01)
        accepted = client.post(url, headers=tool, json=receipt(
            deleted, "Newest private words", newest_us,
        ))
        assert accepted.status_code == 200
        assert accepted.json()["ephemeral_context_added"] is True
        removed = client.delete(
            f"/v1/pet/{robot}/memories/{deleted}", headers=operator,
        )
        assert removed.status_code == 200
        assert not hub.heard_history[robot]
        assert attention.timeline(robot, time.monotonic()) == []
        stale = client.post(url, headers=tool, json=receipt(
            delayed, "Older delayed words", old_us,
        ))
        assert stale.status_code == 200
        assert stale.json()["ephemeral_context_added"] is False
        assert not hub.heard_history[robot]
        assert attention.timeline(robot, time.monotonic()) == []
        live = client.get(f"/v1/pet/{robot}/interaction-context", headers=tool)
        assert live.status_code == 200
        assert "Older delayed words" not in str(live.json())
        assert "Newest private words" not in str(live.json())
        accepted = client.post(url, headers=tool, json=receipt(
            fresh, "A fresh question", time.monotonic_ns() // 1000,
        ))
        assert accepted.status_code == 200
        assert accepted.json()["ephemeral_context_added"] is True
        assert hub.heard_history[robot][-1][1] == "A fresh question"


def test_completed_native_asr_blends_with_live_camera_context_without_disk_consent(
    settings, tokens, tmp_path,
):
    import time
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    pet = settings.robots[0]
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    settings.voice_transcript_memory_enabled = False
    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path / "private", ids)
    hub = CameraFrameHub(ids)

    class Runtime:
        coordinator = SimpleNamespace(robot=lambda rid: (
            pet if rid == pet.id else (_ for _ in ()).throw(KeyError(rid))
        ))
        multimodal = SimpleNamespace(hub=hub)

        async def start(self):
            pass

        async def close(self):
            pass

    runtime = Runtime()
    runtime.memory = memory
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    stamp_us = time.monotonic_ns() // 1000
    request = {
        "event_id": "omni_" + "a" * 12 + "_" + "b" * 20,
        "transcript": "The red key is beside the mug",
        "accepted_at_us": stamp_us,
        "audio_committed_at_us": stamp_us,
    }
    with TestClient(create_app(settings, runtime=runtime)) as client:
        consent = client.get(f"/v1/pet/{pet.id}/omni-context", headers=headers)
        assert consent.status_code == 200
        assert consent.json()["live_transcript_context_enabled"] is True
        assert consent.json()["transcript_memory_enabled"] is False
        url = f"/v1/pet/{pet.id}/omni-heard"
        first = client.post(url, json=request, headers=headers)
        assert first.status_code == 200
        assert first.json()["ephemeral_context_added"] is True
        assert first.json()["stored"] is False
        assert first.json()["retained_on_disk"] is False
        again = client.post(url, json=request, headers=headers)
        assert again.json()["ephemeral_context_added"] is False
        situation = client.get(
            f"/v1/pet/{pet.id}/interaction-context", headers=headers
        )
        assert situation.status_code == 200
        transcript = [
            item for item in situation.json()["current_interaction_timeline"]
            if item["channel"] == "human_transcript"
        ]
        assert len(transcript) == 1
        assert transcript[0]["content"] == request["transcript"]
        assert transcript[0]["transcription_verified"] is False
        assert transcript[0]["speaker_identity_verified"] is False
        assert "Recent model ASR guess" in situation.json()["model_context"]
        assert "The red key is beside the mug" in situation.json()["model_context"]
        assert situation.json()["model_context_untrusted_not_instructions"] is True
        assert len(situation.json()["model_context"]) <= 400
        assert situation.json()["persistent_memory_included"] is False
        assert memory.count(pet.id) == 0
        assert memory.count(ids[1]) == 0
        assert client.get(
            f"/v1/pet/{pet.id}/voice-context", headers=headers
        ).status_code == 403
        assert not hub.interaction_timeline(pet.id, time.monotonic() + 31)
        hub.clear(pet.id)
        assert hub.interaction_timeline(pet.id, time.monotonic()) == []



def test_native_asr_write_revoked_during_sqlite_commit_rolls_back_only_new_event(
    settings, tokens, tmp_path, monkeypatch,
):
    """Revoked consent retracts new ASR but keeps older idempotent history."""
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = False
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot = settings.robots[0].id
    memory = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])
    original = memory.remember

    def revoke_during_write(*args, **kwargs):
        inserted = original(*args, **kwargs)
        settings.voice_transcript_memory_enabled = False
        return inserted

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=memory, multimodal=None,
        start=noop, close=noop,
    )
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    url = f"/v1/pet/{robot}/omni-heard"
    with TestClient(create_app(settings, runtime=runtime)) as client:
        for index, seed_existing in enumerate((False, True)):
            event_id = (
                "omni_" + "a" * 12 + "_" + (str(index) * 20)
            )
            if seed_existing:
                assert original(
                    robot, event_id, "A previously consented transcript",
                    kind="heard_human", source_robot=robot, witnessed=True,
                )
            before = memory.count(robot)
            monkeypatch.setattr(memory, "remember", revoke_during_write)
            settings.voice_transcript_memory_enabled = True
            source_stamp_us = time.monotonic_ns() // 1000
            response = client.post(
                url, headers=auth, json={
                    "event_id": event_id,
                    "transcript": "I left a key on the shelf",
                    "accepted_at_us": source_stamp_us,
                    "audio_committed_at_us": source_stamp_us,
                },
            )
            assert response.status_code == 403
            assert settings.voice_transcript_memory_enabled is False
            assert memory.count(robot) == before
            assert memory.count(settings.robots[1].id) == 0



async def test_native_asr_retention_read_offloads_and_rechecks_consent(
    settings, tmp_path, monkeypatch,
):
    """SQLite retention verification must not block VAD or outlive consent."""
    import threading
    from types import SimpleNamespace

    import pytest
    from desk_robot.api import NativeHeardRequest
    from desk_robot.memory import MemoryStore
    from fastapi import HTTPException

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = False
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot = settings.robots[0].id
    memory = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])
    original_get = memory.get_episode
    loop_thread = threading.get_ident()
    read_threads = []
    revoke = False

    def checked_get(*args, **kwargs):
        read_threads.append(threading.get_ident())
        result = original_get(*args, **kwargs)
        if revoke:
            settings.voice_transcript_memory_enabled = False
        return result

    monkeypatch.setattr(memory, "get_episode", checked_get)

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=memory, multimodal=None, start=noop, close=noop,
    )
    app = create_app(settings, runtime=runtime)
    app.state.runtime = runtime
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == "/v1/pet/{robot_id}/omni-heard"
    )

    def request_for(suffix):
        stamp_us = time.monotonic_ns() // 1000
        return NativeHeardRequest(
            event_id="omni_" + "a" * 12 + "_" + suffix * 20,
            transcript="A private transcript",
            accepted_at_us=stamp_us,
            audio_committed_at_us=stamp_us,
        )

    first = request_for("d")
    response = await endpoint(robot, first)
    assert response["retained_on_disk"] is True
    assert read_threads and all(t != loop_thread for t in read_threads)
    revoke = True
    second = request_for("e")
    with pytest.raises(HTTPException) as exc:
        await endpoint(robot, second)
    assert exc.value.status_code == 403
    assert read_threads and all(t != loop_thread for t in read_threads)
    assert original_get(robot, first.event_id) is not None
    assert original_get(robot, second.event_id) is None


async def test_cancelled_native_asr_sqlite_write_retracts_revoked_memory(
    settings, tmp_path, monkeypatch,
):
    """HTTP cancellation cannot abandon an in-flight revoked SQLite insert."""
    import asyncio
    import threading
    from types import SimpleNamespace

    import pytest
    from desk_robot.api import NativeHeardRequest
    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot = settings.robots[0].id
    ids = [r.id for r in settings.robots]
    memory = MemoryStore(tmp_path / "private", ids)
    hub = CameraFrameHub(ids)
    remember = memory.remember
    forget = memory.forget_episode
    inserted = threading.Event()
    release = threading.Event()
    retracted = threading.Event()

    def paused_insert(*args, **kwargs):
        added = remember(*args, **kwargs)
        assert added
        inserted.set()
        assert release.wait(3)
        return added

    def observed_forget(robot_id, event_id):
        result = forget(robot_id, event_id)
        retracted.set()
        return result

    monkeypatch.setattr(memory, "remember", paused_insert)
    monkeypatch.setattr(memory, "forget_episode", observed_forget)

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=memory, multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    app = create_app(settings, runtime=runtime)
    app.state.runtime = runtime
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == "/v1/pet/{robot_id}/omni-heard"
    )
    stamp_us = time.monotonic_ns() // 1000
    request = NativeHeardRequest(
        event_id="omni_" + "a" * 12 + "_" + "c" * 20,
        transcript="This private transcript should not survive opt out",
        accepted_at_us=stamp_us,
        audio_committed_at_us=stamp_us,
    )
    task = asyncio.create_task(endpoint(robot, request))
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(inserted.wait, 2), timeout=2.5,
        )
        assert len(hub.heard_history[robot]) == 1
        settings.voice_transcript_memory_enabled = False
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.wait_for(
        asyncio.to_thread(retracted.wait, 2), timeout=2.5,
    )
    assert memory.count(robot) == 0
    assert memory.count(settings.robots[1].id) == 0
    assert not hub.heard_history[robot]
    assert not hub.heard_history[ids[1]]


def test_native_asr_live_optout_during_disk_write_retracts_only_ephemeral_item(
    settings, tokens, tmp_path, monkeypatch,
):
    """Durable transcript consent does not grant continuing live ASR access."""
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot = settings.robots[0].id
    ids = [r.id for r in settings.robots]
    memory = MemoryStore(tmp_path / "private", ids)
    hub = CameraFrameHub(ids)
    original = memory.remember

    def revoke_live_during_write(*args, **kwargs):
        inserted = original(*args, **kwargs)
        settings.voice_vision_tools_enabled = False
        return inserted

    monkeypatch.setattr(memory, "remember", revoke_live_during_write)

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=memory, multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    event_id = "omni_" + "a" * 12 + "_" + "b" * 20
    with TestClient(create_app(settings, runtime=runtime)) as client:
        source_stamp_us = time.monotonic_ns() // 1000
        response = client.post(
            f"/v1/pet/{robot}/omni-heard", headers=headers,
            json={"event_id": event_id, "transcript": "My private key is here",
                  "accepted_at_us": source_stamp_us,
                  "audio_committed_at_us": source_stamp_us},
        )
        assert response.status_code == 200
        assert response.json()["stored"] is True
        assert response.json()["ephemeral_context_added"] is False
        assert settings.voice_vision_tools_enabled is False
        settings.voice_vision_tools_enabled = True
        situation = client.get(
            f"/v1/pet/{robot}/interaction-context", headers=headers,
        )
        assert situation.status_code == 200
        assert not any(
            entry["channel"] == "human_transcript"
            for entry in situation.json()["current_interaction_timeline"]
        )
    assert not hub.heard_history[robot]
    assert not hub.heard_history[ids[1]]
    assert memory.count(robot) == 1
    assert memory.count(ids[1]) == 0



@pytest.mark.parametrize(("kind", "from_peer", "provenance"), [
    ("object", False, "My camera model suggested"),
    ("object", True, "{peer} reported a camera model guess"),
    ("heard_human", False, "I may have heard (uncertain transcription)"),
    ("own_utterance", False, "I sent for speech (playback unverified)"),
    ("peer_utterance", True, "{peer} said (peer report, not my sighting)"),
    ("touch_tap", False, "I observed"),
])
def test_native_memory_tool_receipt_respects_consent_turn_and_pet_isolation(
    settings, tokens, tmp_path, monkeypatch, kind, from_peer, provenance,
):
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    pet = settings.robots[0]
    peer = settings.robots[1]
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    settings.fleet_text_sharing_enabled = True
    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path / "private", ids)
    memory.remember(
        pet.id, "old_key_sighting", "My key was beside the green mug",
        kind=kind, source_robot=peer.id if from_peer else pet.id,
        witnessed=not from_peer,
    )
    hub = CameraFrameHub(ids)

    class Runtime:
        coordinator = SimpleNamespace(robot=lambda rid: (
            settings.robot(rid)
        ))
        multimodal = SimpleNamespace(hub=hub, _turn_epoch={rid: 0 for rid in ids})
        _voice_turn_generations = {rid: 0 for rid in ids}
        voice_events = SimpleNamespace(monitor_ready=True, _event_generation=0)
        pet = SimpleNamespace(voice_monitor_ready=True)

        async def start(self):
            pass

        async def close(self):
            pass

    runtime = Runtime()
    runtime.memory = memory
    runtime.conversation = SimpleNamespace(
        _private_memory_generation={rid: 0 for rid in ids}
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{pet.id}/voice-context"
        recall = client.get(
            url, params={"query": "key green mug"},
            headers=_signed_tool_headers(
                settings, tokens, pet.id, url, 0, monkeypatch,
            ),
        )
        assert recall.status_code == 200
        assert recall.json()["matched"] is True
        assert recall.json()["memories"][0]["kind"] == kind
        expected = provenance.format(peer=peer.id)
        assert hub.tool_history[pet.id][-1][1] == (
            expected + ": My key was beside the green mug"
        )
        timeline = client.get(
            f"/v1/pet/{pet.id}/interaction-context", headers=headers
        )
        assert timeline.status_code == 200
        payload = timeline.json()
        assert payload["memory_tools_enabled"] is True
        assert payload["private_memory_generation"] == 0
        assert payload["persistent_memory_included"] is False
        cues = payload["model_context"]
        assert "green mug" not in cues
        assert "Opt-in private past memory" not in cues
        assert "green mug" not in client.get(
            f"/v1/pet/{peer.id}/interaction-context", headers=headers
        ).json()["model_context"]
        settings.voice_memory_tools_enabled = False
        # The live camera permit does not retain permission to send an
        # earlier private memory result to the model after opt-out.
        revoked = client.get(
            f"/v1/pet/{pet.id}/interaction-context", headers=headers
        )
        assert revoked.status_code == 200
        assert revoked.json()["memory_tools_enabled"] is False
        assert revoked.json()["private_memory_generation"] is None
        assert "green mug" not in revoked.json()["model_context"]
        assert client.get(url, headers=headers).status_code == 403
        assert memory.count(pet.id) == 1


def test_native_personality_uses_shared_brain_provenance_and_private_core(
    settings, tokens, tmp_path,
):
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore

    ids = [robot.id for robot in settings.robots]
    memory = MemoryStore(tmp_path / "private", ids)
    memory.set_core_fact("robot-01", "favorite_game", "hide the key")
    memory.remember(
        "robot-01", "sent_1", "Hello, my little friend",
        kind="own_utterance", source_robot="robot-01", witnessed=True,
    )
    memory.remember(
        "robot-01", "heard_1", "Maybe you asked me about a key",
        kind="heard_human", source_robot="robot-01", witnessed=True,
    )
    memory.remember(
        "robot-02", "heard_peer", "I saw a pink key",
        kind="peer_utterance", source_robot="robot-01", witnessed=False,
    )
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    settings.fleet_text_sharing_enabled = True

    class StubRuntime:
        coordinator = SimpleNamespace(robot=settings.robot)
        async def start(self):
            pass

        async def close(self):
            pass

    runtime = StubRuntime()
    runtime.memory = memory
    runtime.conversation = SimpleNamespace(
        _private_memory_generation={robot_id: 0 for robot_id in ids}
    )
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        own = client.get("/v1/pet/robot-01/omni-context", headers=auth)
        other = client.get("/v1/pet/robot-02/omni-context", headers=auth)
        assert own.status_code == other.status_code == 200
        own_payload, peer_payload = own.json(), other.json()
        text = own_payload["instructions"]
        private = own_payload["untrusted_historical_evidence"]
        # Native startup instructions remain trusted operator policy.
        # History is attributed lower-trust DATA, never appended to SYSTEM.
        assert own_payload["startup_memory_instructions_excluded"] is True
        assert private["core"] == "favorite_game: hide the key"
        assert "favorite_game: hide the key" not in text
        assert (
            "I sent for speech (playback unverified): Hello, my little friend"
            in private["recent"]
        )
        assert "I said: Hello, my little friend" not in private["recent"]
        assert "uncertain transcription" in private["recent"]
        assert "I observed: Hello" not in private["recent"]
        peer_text = peer_payload["untrusted_historical_evidence"]["recent"]
        assert "robot-01 said (peer report, not my sighting): I saw a pink key" in peer_text
        assert "I heard robot-01 say" not in peer_text
        assert "favorite_game" not in peer_payload["untrusted_historical_evidence"]["core"]
        assert "Hello, my little friend" not in peer_text
        settings.voice_memory_tools_enabled = False
        disabled = client.get("/v1/pet/robot-01/omni-context", headers=auth)
        assert disabled.status_code == 200
        assert disabled.json()["memory_enabled"] is False
        assert "hide the key" not in disabled.json()["instructions"]
        assert disabled.json()["untrusted_historical_evidence"] == {
            "core": "", "recent": "",
        }


def test_authoritative_latest_pickup_status_survives_head_reconnect_without_cross_pet_leak(
    settings, tokens,
):
    from desk_robot.config import RobotConfig
    from desk_robot.controller import Job

    # The general simulation fixture has only two pets. Include a third
    # VALID configured identity to test the important empty job response,
    # rather than incorrectly treating unknown robot-03 as a valid pet.
    settings.robots.append(RobotConfig(
        id="robot-03", name="Empty job pet",
        token_env="DESK_ROBOT_HEAD_03_TOKEN", motion_enabled=False,
    ))
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings)) as client:
        jobs = client.app.state.runtime.coordinator.jobs
        jobs["first"] = Job(
            "first", "robot-01", "pickup", state="failed",
            error="Gripper did not detect physical contact",
        )
        jobs["dock"] = Job("dock", "robot-01", "dock_approach", state="queued")
        jobs["second"] = Job(
            "second", "robot-01", "pickup", state="running"
        )
        # Robot 02 must never inherit Robot 01's physical job progress.
        jobs["peer"] = Job("peer", "robot-02", "pickup", state="queued")

        url = "/v1/robots/robot-01/jobs/latest-pickup"
        assert client.get(url).status_code == 401
        latest = client.get(url, headers=tool)
        assert latest.status_code == 200
        assert latest.json()["id"] == "second"
        assert latest.json()["kind"] == "pickup"
        assert latest.json()["state"] == "running"
        assert latest.json()["available"] is True
        peer = client.get(
            "/v1/robots/robot-02/jobs/latest-pickup", headers=tool
        )
        assert peer.json()["id"] == "peer"
        # Robot 03 is explicitly registered for this scenario, but has no
        # pickup history. Do not confuse a valid empty job with an unknown ID.
        untouched = client.get(
            "/v1/robots/robot-03/jobs/latest-pickup", headers=tool
        )
        assert untouched.status_code == 200
        assert untouched.json() == {
            "robot_id": "robot-03", "available": False,
            "physical_grasp_verified": False,
        }
        # Removing an otherwise valid peer job also cannot expose Robot 01's
        # pickup state through the Robot 02 owner.
        del jobs["peer"]
        emptied_peer = client.get(
            "/v1/robots/robot-02/jobs/latest-pickup", headers=tool
        )
        assert emptied_peer.status_code == 200
        assert emptied_peer.json() == {
            "robot_id": "robot-02", "available": False,
            "physical_grasp_verified": False,
        }
        assert client.get(
            "/v1/robots/unknown/jobs/latest-pickup", headers=tool
        ).status_code == 404
        # The old operator job-by-id API remains authoritative and intact.
        assert client.get(
            "/v1/jobs/first", headers=tool
        ).json()["state"] == "failed"


def test_sensor_tool_receipt_enters_same_mac_history_only_from_current_voice_tool(
    settings, tokens, monkeypatch,
):
    import time
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    robot = settings.robots[0].id
    hub = CameraFrameHub([r.id for r in settings.robots])
    visual = SimpleNamespace(
        hub=hub, _turn_epoch={r.id: 5 for r in settings.robots},
    )

    class CurrentHead:
        reported_id = robot

        async def aux_status(self):
            return {
                "robot_id": self.reported_id,
                "force": {"boot_id": 12345},
                "proximity": {"boot_id": 12345},
                "climate": {"valid": True, "seq": 1, "age_ms": 10,
                            "temp_centi": 2210, "rh_centi": 5400},
                "bmp280": {"present": True, "valid": True, "chip_id": 0x58,
                           "seq": 1, "age_ms": 10, "temp_centi": 2130,
                           "pressure_pa": 101312},
            }

    async def noop():
        pass

    head = CurrentHead()
    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid),
            heads={robot: head},
        ),
        multimodal=visual,
        _voice_turn_generations={robot: 5},
        voice_events=SimpleNamespace(monitor_ready=True, _event_generation=0),
        pet=SimpleNamespace(voice_monitor_ready=True),
        start=noop, close=noop,
    )
    token = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/robots/{robot}/aux"
        assert client.get(url).status_code == 401
        ordinary = client.get(url, headers=token)
        assert ordinary.status_code == 200
        assert not hub.tool_history[robot]
        tool = client.get(url, headers=_signed_tool_headers(
            settings, tokens, robot, url, 5, monkeypatch,
        ))
        assert tool.status_code == 200
        assert len(hub.tool_history[robot]) == 1
        kind, summary, when = hub.tool_history[robot][0]
        assert kind == "sensor_telemetry"
        assert "temp_centi=2210" in summary
        assert "pressure_pa=101312" in summary
        assert 0 <= time.monotonic() - when <= 2
        for other in settings.robots[1:]:
            assert not hub.tool_history[other.id]
        hub.tool_history[robot].clear()
        head.reported_id = settings.robots[1].id
        assert client.get(url, headers=_signed_tool_headers(
            settings, tokens, robot, url, 5, monkeypatch,
        )).status_code == 503
        assert not hub.tool_history[robot]  # Foreign AUX cannot become a fact.


def test_slow_readonly_tool_receipt_cannot_cross_into_new_human_turn(
    settings, tokens, tmp_path, monkeypatch,
):
    """Old async WROOM and SQLite results may not pollute the next VAD turn."""
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    robot = settings.robots[0].id
    ids = [r.id for r in settings.robots]
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    memory = MemoryStore(tmp_path / "turn_receipts", ids)
    memory.remember(
        robot, "recall_001", "A blue key on my desk",
        kind="object", source_robot=robot, witnessed=True,
    )
    hub = CameraFrameHub(ids)
    visual = SimpleNamespace(hub=hub, _turn_epoch={rid: 7 for rid in ids})

    async def noop():
        pass

    for route in ("aux", "voice-context"):
        entered, release = threading.Event(), threading.Event()

        class Head:
            def __init__(self):
                self.seq = 0

            async def aux_status(self, route=route, entered=entered, release=release):
                if route == "aux":
                    entered.set()
                    if not await asyncio.to_thread(release.wait, 3):
                        raise RuntimeError("Timed out waiting for fresh human turn")
                self.seq += 1
                return {
                    "robot_id": robot,
                    "force": {"boot_id": 23456},
                    "proximity": {"boot_id": 23456},
                    "climate": {"valid": True, "seq": self.seq, "age_ms": 10,
                                "temp_centi": 2210, "rh_centi": 5400},
                }

        original_search = MemoryStore.search

        def delayed_search(self, *args, route=route, entered=entered,
                           release=release, original_search=original_search,
                           **kwargs):
            if route == "voice-context":
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("Timed out waiting for fresh human turn")
            return original_search(self, *args, **kwargs)

        # This tests a genuine awaited SQLite search in its own worker,
        # not a pre-completed fake result.
        memory.search = delayed_search.__get__(memory, MemoryStore)
        runtime = SimpleNamespace(
            coordinator=SimpleNamespace(
                robot=lambda rid: settings.robot(rid),
                heads={robot: Head()},
            ),
            memory=memory, multimodal=visual,
            _voice_turn_generations={robot: 7},
            voice_events=SimpleNamespace(monitor_ready=True, _event_generation=0),
            pet=SimpleNamespace(voice_monitor_ready=True),
            conversation=SimpleNamespace(
                _private_memory_generation={rid: 0 for rid in ids},
            ),
            start=noop, close=noop,
        )
        url = (f"/v1/robots/{robot}/aux" if route == "aux"
               else f"/v1/pet/{robot}/voice-context?query=blue%20key")
        headers = _signed_tool_headers(
            settings, tokens, robot, url, runtime._voice_turn_generations[robot],
            monkeypatch,
        )
        with TestClient(create_app(settings, runtime=runtime)) as client:
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(client.get, url, headers=headers)
                try:
                    assert entered.wait(2), "Slow real tool read did not start"
                    visual._turn_epoch[robot] += 1  # New authenticated VAD.
                    runtime._voice_turn_generations[robot] += 1
                finally:
                    release.set()
                stale = pending.result(timeout=4)
                # Neither a private lookup nor physical AUX telemetry
                # from an old Xiaozhi tool turn may return its delayed facts
                # after a newer authenticated human VAD supersedes it.
                assert stale.status_code == 409
                assert "superseded" in stale.json()["detail"]
            assert not hub.tool_history[robot]
            # A genuinely NEW tool request in that turn is still recorded.
            assert client.get(url, headers=_signed_tool_headers(
                settings, tokens, robot, url, runtime._voice_turn_generations[robot],
                monkeypatch,
            )).status_code == 200
            expected = ("sensor_telemetry" if route == "aux"
                        else "memory_recall")
            assert [entry[0] for entry in hub.tool_history[robot]] == [expected]
            hub.tool_history[robot].clear()
            assert not any(hub.tool_history[rid] for rid in ids[1:])


def test_ollama_sensor_tool_route_requires_real_sensor_question_and_no_movement(
    settings, tokens,
):
    import json
    from types import SimpleNamespace

    robot = settings.robots[0].id
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True

    class Model:
        async def reply(self, history):
            return json.dumps({"tools": [
                {"route": "move"}, {"route": "aux-status"},
            ]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None,
        start=noop, close=noop,
    )
    headers = {
        "Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"],
    }
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        live = client.post(url, headers=headers, json={
            "transcript": "Can you read your temperature sensor?"
        })
        assert live.status_code == 200
        assert live.json()["tools"] == [
            {"route": "aux-status", "payload": {}},
        ]
        # The model is not allowed to invent a reason to inspect sensors
        # during ordinary personal conversation.
        unrelated = client.post(url, headers=headers, json={
            "transcript": "How was your day?"
        })
        assert unrelated.status_code == 200
        assert unrelated.json()["tools"] == []
        assert live.json()["motor_authorized"] is False
        assert live.json()["charging_authorized"] is False


def test_native_live_policy_respects_real_mac_pet_quiet_and_pause(
    settings, tokens,
):
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id
    state = SimpleNamespace(enabled=True, quiet=False)
    hub = CameraFrameHub([r.id for r in settings.robots])

    class Runtime:
        coordinator = SimpleNamespace(robot=settings.robot)
        pet = SimpleNamespace(states={robot: state}, voice_monitor_ready=True)
        multimodal = SimpleNamespace(hub=hub)

        async def start(self):
            pass

        async def close(self):
            pass

    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=Runtime())) as client:
        persona_url = f"/v1/pet/{robot}/omni-context"
        live_url = f"/v1/pet/{robot}/interaction-context"
        start = client.get(persona_url, headers=auth).json()
        assert start["pet_autonomy_enabled"] is True
        assert start["voice_monitor_ready"] is True
        assert start["pet_quiet"] is False
        Runtime.pet.voice_monitor_ready = False
        lost = client.get(live_url, headers=auth).json()
        assert lost["pet_autonomy_enabled"] is False
        assert lost["voice_monitor_ready"] is False
        assert lost["pet_quiet"] is False  # Monitor loss is not operator quiet.
        Runtime.pet.voice_monitor_ready = True
        restored = client.get(live_url, headers=auth).json()
        assert restored["pet_autonomy_enabled"] is True
        assert restored["voice_monitor_ready"] is True
        state.quiet = True
        quiet = client.get(live_url, headers=auth).json()
        assert quiet["pet_quiet"] is True
        state.quiet = False
        state.enabled = False
        pause = client.get(live_url, headers=auth).json()
        assert pause["pet_autonomy_enabled"] is False
        assert pause["pet_quiet"] is False

    # An unavailable runtime policy never becomes an implicit permit.
    class NoPetRuntime:
        coordinator = SimpleNamespace(robot=settings.robot)

        async def start(self):
            pass

        async def close(self):
            pass

    with TestClient(create_app(settings, runtime=NoPetRuntime())) as client:
        fail_closed = client.get(persona_url, headers=auth)
        assert fail_closed.status_code == 200
        assert fail_closed.json()["pet_autonomy_enabled"] is False
        assert fail_closed.json()["voice_monitor_ready"] is False
        assert fail_closed.json()["pet_quiet"] is True


@pytest.mark.parametrize("missing", ["device_identity", "speaker_adapter"])
@pytest.mark.parametrize("route", ["pause", "quiet"])
def test_hardware_operator_revoke_reports_missing_xiao_stop_owner(
    settings, tokens, missing, route,
):
    """A successful WROOM stop is not proof an unaddressed speaker is silent."""
    from types import SimpleNamespace

    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.device_id = None if missing == "device_identity" else "test-head-01"
    events = []

    class Coordinator:
        def robot(self, rid):
            return settings.robot(rid)

        async def stop(self, rid):
            events.append("wroom_stop")
            return {"stopped": True}

    class Pet:
        async def pause(self, rid):
            events.append("pet_pause")
            return {"enabled": False}

        async def set_quiet(self, rid, value):
            assert value is True
            events.append("pet_quiet")
            return {"quiet": True}

    class Speaker:
        async def interrupt(self, selected):
            events.append("unexpected_speaker_stop")
            raise AssertionError("Missing XIAO owner cannot confirm STOP")

    class Runtime:
        coordinator = Coordinator()
        pet = Pet()
        conversation = SimpleNamespace(
            speaker=Speaker() if missing == "device_identity" else object()
        )

        async def start(self):
            pass

        async def close(self):
            pass

    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    target = f"/v1/pet/{robot.id}/{route}"
    payload = {"quiet": True} if route == "quiet" else None
    with TestClient(
        create_app(settings, runtime=Runtime()), raise_server_exceptions=False
    ) as client:
        response = client.post(target, headers=headers, json=payload)
    assert response.status_code == 503
    assert "XIAO speech STOP unconfirmed" in response.json()["error"]
    assert events == ["wroom_stop", "pet_quiet" if route == "quiet"
                      else "pet_pause"]


def test_pet_quiet_and_pause_stop_motors_before_unavailable_voice_bridge(
    settings, tokens,
):
    from types import SimpleNamespace

    settings.mode = "hardware"
    robot = settings.robots[0]
    # Physical speaker STOP is conditional on an actual assigned Xiaozhi
    # device identity. Without one the production API correctly does not
    # transmit any native stop packet; this fixture must opt into that path.
    robot.device_id = "test-xiao-head-01"
    events = []

    class Pet:
        states = {robot.id: SimpleNamespace(enabled=True, quiet=False)}

        async def set_quiet(self, rid, quiet):
            events.append("pet_quiet")
            self.states[rid].quiet = quiet
            return {"robot_id": rid, "enabled": True, "quiet": quiet}

        async def pause(self, rid):
            events.append("pet_pause")
            self.states[rid].enabled = False
            return {"robot_id": rid, "enabled": False, "quiet": False}

    class Speaker:
        async def interrupt(self, selected):
            assert selected.id == robot.id
            events.append("voice_bridge_attempt")
            raise RuntimeError("Voice bridge unavailable")

    class Coordinator:
        def robot(self, rid):
            return settings.robot(rid)

        async def stop(self, rid):
            assert rid == robot.id
            events.append("wroom_stop")
            return {"stopped": True}

    class Runtime:
        pet = Pet()
        coordinator = Coordinator()
        conversation = SimpleNamespace(speaker=Speaker())

        async def start(self):
            pass

        async def close(self):
            pass

    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    with TestClient(
        create_app(settings, runtime=Runtime()), raise_server_exceptions=False
    ) as client:
        for path, payload, expected in (
            (f"/v1/pet/{robot.id}/quiet", {"quiet": True}, "pet_quiet"),
            (f"/v1/pet/{robot.id}/pause", None, "pet_pause"),
        ):
            events.clear()
            result = client.post(path, headers=headers, json=payload)
            assert result.status_code >= 500  # report the audio outage
            assert events == [
                "wroom_stop", expected, "voice_bridge_attempt",
            ]


def test_failed_body_stop_still_revokes_native_speech_and_pet_autonomy(
    settings, tokens,
):
    from types import SimpleNamespace

    settings.mode = "hardware"
    robot = settings.robots[0]
    # Physical speaker STOP is conditional on an actual assigned Xiaozhi
    # device identity. Without one the production API correctly does not
    # transmit any native stop packet; this fixture must opt into that path.
    robot.device_id = "test-xiao-head-01"
    events = []

    class Pet:
        states = {robot.id: SimpleNamespace(enabled=True, quiet=False)}

        async def set_quiet(self, rid, quiet):
            events.append("quiet")
            self.states[rid].quiet = quiet
            return {"quiet": quiet}

        async def pause(self, rid):
            events.append("pause")
            self.states[rid].enabled = False
            return {"enabled": False}

    class Speaker:
        async def interrupt(self, selected):
            assert selected.id == robot.id
            events.append("native_stop")

    class Coordinator:
        def robot(self, rid):
            return settings.robot(rid)

        async def stop(self, rid):
            events.append("wroom_stop_attempt")
            raise RuntimeError("Body safety channel unreachable")

    class Runtime:
        coordinator = Coordinator()
        pet = Pet()
        conversation = SimpleNamespace(speaker=Speaker())

        async def start(self):
            pass

        async def close(self):
            pass

    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    with TestClient(
        create_app(settings, runtime=Runtime()), raise_server_exceptions=False
    ) as client:
        for path, json_body, state_change in (
            (f"/v1/pet/{robot.id}/pause", None, "pause"),
            (f"/v1/pet/{robot.id}/quiet", {"quiet": True}, "quiet"),
        ):
            events.clear()
            result = client.post(path, headers=auth, json=json_body)
            assert result.status_code >= 500
            assert events == [
                "wroom_stop_attempt", state_change, "native_stop",
            ]


def test_native_model_speech_text_enters_shared_mac_context_without_disk_storage(
    settings, tokens,
):
    """Only scoped authenticated sent Opus text becomes ephemeral pet history."""
    import time
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id
    ids = [entry.id for entry in settings.robots]
    hub = CameraFrameHub(ids)

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=lambda rid: settings.robot(rid)),
        multimodal=SimpleNamespace(hub=hub), start=noop, close=noop,
    )
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    url = f"/v1/pet/{robot}/omni-spoken"
    payload = {
        "event_id": "omni_sent_" + "a" * 12 + "_" + "b" * 20,
        "model_text": "I saw something interesting on the desk",
        "sent_at_us": int(time.monotonic() * 1_000_000),
    }
    with TestClient(create_app(settings, runtime=runtime)) as client:
        assert client.post(url, json=payload).status_code == 401
        first = client.post(url, headers=auth, json=payload)
        assert first.status_code == 200
        assert first.json()["ephemeral_context_added"] is True
        assert first.json()["retained_on_disk"] is False
        assert first.json()["audio_playback_verified"] is False
        assert first.json()["motor_authorized"] is False
        again = client.post(url, headers=auth, json=payload)
        assert again.status_code == 200
        assert again.json()["ephemeral_context_added"] is False
        live = client.get(f"/v1/pet/{robot}/interaction-context", headers=auth)
        assert live.status_code == 200
        spoken = [item for item in live.json()["current_interaction_timeline"]
                  if item["channel"] == "robot_speech"]
        assert len(spoken) == 1
        assert spoken[0]["source"] == (
            "native_model_text_opus_sent_playback_unverified"
        )
        assert "native model estimated" in live.json()["model_context"]
        assert client.post(
            url, headers=auth, json={**payload, "event_id": "forged"}
        ).status_code == 422
        assert client.post(
            url, headers=auth, json={**payload, "sent_at_us": 1}
        ).status_code == 403
        assert client.post(
            url, headers=auth, json={**payload, "sent_at_us": 10 ** 20}
        ).status_code == 422
        assert client.post(
            url, headers=auth, json={**payload, "model_text": "bad\x00text"}
        ).status_code == 400
        settings.voice_vision_tools_enabled = False
        assert client.post(url, headers=auth, json=payload).status_code == 403
    assert not hub.interaction_timeline(ids[1], time.monotonic())




def test_live_interaction_includes_operator_job_without_peer_leak(
    settings, tokens,
):
    """Xiaozhi and Mac read the existing job, not a scripted sensor emotion."""
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = False
    ids = [robot.id for robot in settings.robots]
    assert len(ids) >= 2
    active = SimpleNamespace(
        robot_id=ids[0], kind="exploration", state="running",
        target="PRIVATE_UNTRUSTED_TEXT_NOT_A_COMMAND",
    )
    jobs = {"current": active}
    hub = CameraFrameHub(ids)

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            jobs=jobs, robot=lambda robot_id: settings.robot(robot_id),
        ),
        multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{ids[0]}/interaction-context"
        running = client.get(url, headers=headers)
        assert running.status_code == 200
        payload = running.json()
        activities = [
            event for event in payload["current_interaction_timeline"]
            if event["channel"] == "mac_activity"
        ]
        assert len(activities) == 1
        assert activities[0]["job_type"] == "exploration"
        assert activities[0]["status"] == "running"
        assert activities[0]["motor_authorized"] is False
        assert "Mac operator-submitted exploration job is running" in (
            payload["model_context"]
        )
        assert "PRIVATE_UNTRUSTED_TEXT_NOT_A_COMMAND" not in str(payload)
        assert len(payload["model_context"]) <= 400
        peer = client.get(
            f"/v1/pet/{ids[1]}/interaction-context", headers=headers
        )
        assert peer.status_code == 200
        assert "mac_activity" not in str(peer.json())
        active.state = "succeeded"
        finished = client.get(url, headers=headers)
        assert finished.status_code == 200
        assert "Mac operator-submitted" not in finished.json()["model_context"]
        settings.voice_vision_tools_enabled = False
        cam_off = client.get(url, headers=headers)
        assert cam_off.status_code == 200
        assert all(
            item.get("channel") != "camera"
            for item in cam_off.json()["current_interaction_timeline"]
        )


def test_readonly_planner_does_not_treat_casual_visual_words_as_camera_permission(
    settings, tokens,
):
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id

    class OvereagerModel:
        async def reply(self, history):
            return json.dumps({"tools": [{"route": "look"}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=OvereagerModel()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        for transcript in (
            "See you tomorrow",
            "I look forward to seeing you",
            "I left a photo on the desk",
            "Please look forward to tomorrow",
            "We should inspect that later",
            "I showed you a photo, and can you check your battery?",
        ):
            reply = client.post(url, headers=headers, json={"transcript": transcript})
            assert reply.status_code == 200
            assert reply.json()["tools"] == []
        for transcript in (
            "What do you see on my desk?",
            "Please look at the mug",
            "Could you inspect the photo?",
            "See if there is a key in front of you",
            "I put the mug down, can you look at it?",
            "I just moved the key and could you see it now?",
        ):
            reply = client.post(url, headers=headers, json={"transcript": transcript})
            assert reply.status_code == 200
            assert [item["route"] for item in reply.json()["tools"]] == ["look"]


def test_memory_anecdote_does_not_authorize_private_retrieval(settings, tokens):
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    robot = settings.robots[0].id

    class EagerMemoryModel:
        async def reply(self, history):
            return json.dumps({"tools": [{"route": "voice-context"}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=EagerMemoryModel()),
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        for anecdote in (
            "I remember our walk yesterday",
            "Our previous conversation was nice",
            "We talked about gardening earlier",
            "This is a memory I cherish",
            "I am recalling the movie",
        ):
            result = client.post(url, headers=headers, json={"transcript": anecdote})
            assert result.status_code == 200
            assert result.json()["tools"] == []
        for question in (
            "What did I say yesterday?",
            "Do you remember our discussion?",
            "Can you recall what we discussed?",
            "Tell me about our previous conversation",
            "What did I say earlier and can you look at the desk?",
        ):
            result = client.post(url, headers=headers, json={"transcript": question})
            assert result.status_code == 200
            assert result.json()["tools"] == [
                {"route": "voice-context", "payload": {"question": question}}
            ]


def test_battery_statement_and_memory_recall_never_trigger_unsolicited_fuel_gauge(
    settings, tokens,
):
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    robot = settings.robots[0].id

    class EagerBatteryModel:
        async def reply(self, history):
            return json.dumps({"tools": [{"route": "power-status"}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=EagerBatteryModel()),
        multimodal=None, start=noop, close=noop,
    )
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        for statement in (
            "I replaced my battery yesterday",
            "We have a battery on the desk",
            "The battery story reminds me of my childhood",
            "What did I tell you about my battery?",
            "I moved a battery, and can you look at the desk?",
        ):
            result = client.post(url, headers=auth, json={"transcript": statement})
            assert result.status_code == 200
            assert result.json()["tools"] == []
        for request in (
            "What is your battery level?",
            "Check my battery status",
            "Could you inspect the desk and battery?",
            "What is on the desk and my battery level?",
            "I put a cup down, can you check your battery?",
            "What did I say earlier and can you check your battery?",
        ):
            result = client.post(url, headers=auth, json={"transcript": request})
            assert result.status_code == 200
            assert result.json()["tools"] == [
                {"route": "power-status", "payload": {}}
            ]


def test_status_and_aux_anecdotes_do_not_trigger_extra_live_tool_reads(
    settings, tokens,
):
    import json
    from types import SimpleNamespace

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0].id

    class OvereagerModel:
        async def reply(self, history):
            return json.dumps({"tools": [
                {"route": "status"}, {"route": "aux-status"},
            ]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=OvereagerModel()),
        multimodal=None, start=noop, close=noop,
    )
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        url = f"/v1/pet/{robot}/plan-readonly"
        cases = (
            ("I fixed your sensors yesterday", []),
            ("Your safety status used to scare me", []),
            ("We discussed your temperature last week", []),
            ("I left a sensor on the desk, can you look at it?", []),
            ("What is your safety status?", ["status"]),
            ("Show your sensor readings", ["aux-status"]),
            ("How are your sensors?", ["aux-status"]),
            ("What is your status and temperature?", ["status", "aux-status"]),
            ("What is your temperature and safety status?", ["status", "aux-status"]),
            ("I moved the mug, could you check your humidity?", ["aux-status"]),
        )
        for transcript, expected in cases:
            answer = client.post(url, headers=auth, json={"transcript": transcript})
            assert answer.status_code == 200
            assert [entry["route"] for entry in answer.json()["tools"]] == expected
            assert answer.json()["motor_authorized"] is False



@pytest.mark.asyncio
async def test_native_idle_frame_subscription_observes_revocation_in_under_400ms(
    settings,
):
    """No selected camera frame is needed to end a revoked native stream."""
    import asyncio

    from desk_robot.multimodal import MultimodalOrchestrator

    settings.voice_vision_tools_enabled = True
    observer = MultimodalOrchestrator(settings, {}, None, asyncio.Lock())
    frames = observer.native_live_frames(settings.robots[0].id)
    waiting = asyncio.create_task(anext(frames))
    try:
        await asyncio.sleep(0.02)
        assert not waiting.done()
        settings.voice_vision_tools_enabled = False
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(waiting, timeout=0.4)
    finally:
        if not waiting.done():
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
        await frames.aclose()
        await observer.close()


def test_native_delayed_asr_never_gains_retroactive_storage_consent(
    settings, tokens, tmp_path,
):
    """A pre-grant queued estimate cannot become durable after consent starts."""
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = False
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot = settings.robots[0].id
    memory = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot), memory=memory,
        multimodal=None, start=noop, close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    url = f"/v1/pet/{robot}/omni-heard"
    with TestClient(create_app(settings, runtime=runtime)) as client:
        before = time.monotonic_ns() // 1000 - 1000
        settings.voice_transcript_memory_enabled = False
        settings.voice_transcript_memory_enabled = True
        stale = client.post(url, headers=headers, json={
            "event_id": "omni_" + "a" * 12 + "_" + "b" * 20,
            "transcript": "Audio from before transcript permission",
            "accepted_at_us": before,
        })
        assert stale.status_code == 200
        assert stale.json()["retention_consent_enabled"] is True
        assert stale.json()["stored"] is False
        assert stale.json()["retained_on_disk"] is False
        assert memory.recent(robot) == []

        legacy = client.post(url, headers=headers, json={
            "event_id": "omni_" + "a" * 12 + "_" + "c" * 20,
            "transcript": "Unknown source time",
        })
        assert legacy.status_code == 200
        assert legacy.json()["stored"] is False

        fresh_source_us = time.monotonic_ns() // 1000
        fresh = client.post(url, headers=headers, json={
            "event_id": "omni_" + "a" * 12 + "_" + "d" * 20,
            "transcript": "Consented current human speech",
            "accepted_at_us": fresh_source_us,
            "audio_committed_at_us": fresh_source_us,
        })
        assert fresh.status_code == 200
        assert fresh.json()["stored"] is True
        assert len(memory.recent(robot)) == 1

        before_parent_regrant = time.monotonic_ns() // 1000 - 1000
        settings.voice_memory_tools_enabled = False
        settings.voice_memory_tools_enabled = True
        old_parent = client.post(url, headers=headers, json={
            "event_id": "omni_" + "a" * 12 + "_" + "e" * 20,
            "transcript": "Audio from before parent memory regrant",
            "accepted_at_us": before_parent_regrant,
        })
        assert old_parent.status_code == 200
        assert old_parent.json()["stored"] is False
        assert len(memory.recent(robot)) == 1


def test_signed_tool_receipt_requires_current_xiaozhi_generation_not_mac_epoch(
    settings, tokens, monkeypatch,
):
    """Unused old signed N cannot arrive after N+1 with an unchanged Mac epoch."""
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    robot = settings.robots[0].id
    peer = settings.robots[1].id
    hub = CameraFrameHub([r.id for r in settings.robots])
    visual = SimpleNamespace(hub=hub, _turn_epoch={robot: 7, peer: 7})
    calls = []

    class Head:
        async def status(self):
            calls.append("status")
            return {
                "robot_id": robot, "armed": False,
                "backend": "stepper_28byj48", "safety": {"fault": "none"},
            }

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid), heads={robot: Head()},
        ),
        multimodal=visual, _voice_turn_generations={robot: 41},
        voice_events=SimpleNamespace(monitor_ready=True, _event_generation=0),
        pet=SimpleNamespace(voice_monitor_ready=True),
        start=noop, close=noop,
    )
    path = f"/v1/robots/{robot}/status"
    with TestClient(create_app(settings, runtime=runtime)) as client:
        old_signed = _signed_tool_headers(
            settings, tokens, robot, path, 41, monkeypatch,
        )
        runtime._voice_turn_generations[robot] = 42
        assert client.get(path, headers=old_signed).status_code == 409
        assert calls == []
        assert visual._turn_epoch[robot] == 7
        assert not hub.recent_tool_context(robot, time.monotonic())

        current_signed = _signed_tool_headers(
            settings, tokens, robot, path, 42, monkeypatch,
        )
        assert client.get(path, headers=current_signed).status_code == 200
        assert [entry[0] for entry in hub.tool_history[robot]] == ["robot_status"]
        assert client.get(path, headers=current_signed).status_code == 409
        assert calls == ["status"]
        assert not hub.tool_history[peer]

        foreign_signed = _signed_tool_headers(
            settings, tokens, peer, f"/v1/robots/{peer}/status", 42,
            monkeypatch,
        )
        assert client.get(path, headers=foreign_signed).status_code == 409
        assert calls == ["status"]


def test_signed_tool_receipt_fails_closed_on_monitor_loss_and_reconnect(
    settings, tokens, monkeypatch,
):
    """Missing monitor, generation map, or changed stream epoch denies the tool."""
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    robot = settings.robots[0].id
    hub = CameraFrameHub([robot])
    visual = SimpleNamespace(hub=hub, _turn_epoch={robot: 9})
    calls = []

    class Head:
        async def status(self):
            calls.append("status")
            return {"robot_id": robot, "safety": {"fault": "none"}}

    async def noop():
        pass

    listener = SimpleNamespace(monitor_ready=False, _event_generation=0)
    pet = SimpleNamespace(voice_monitor_ready=True)
    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid), heads={robot: Head()},
        ),
        multimodal=visual, _voice_turn_generations={robot: 51},
        voice_events=listener, pet=pet, start=noop, close=noop,
    )
    path = f"/v1/robots/{robot}/status"
    with TestClient(create_app(settings, runtime=runtime)) as client:
        denied = _signed_tool_headers(
            settings, tokens, robot, path, 51, monkeypatch,
        )
        assert client.get(path, headers=denied).status_code == 409
        listener.monitor_ready = True
        pet.voice_monitor_ready = False
        assert client.get(path, headers=denied).status_code == 409
        pet.voice_monitor_ready = True
        runtime._voice_turn_generations = None
        assert client.get(path, headers=denied).status_code == 409
        assert calls == []
        # Once a new authenticated source generation is published, only
        # its own newly signed request can enter conversational history.
        listener._event_generation += 1
        runtime._voice_turn_generations = {robot: 52}
        assert client.get(path, headers=denied).status_code == 409
        accepted = _signed_tool_headers(
            settings, tokens, robot, path, 52, monkeypatch,
        )
        assert client.get(path, headers=accepted).status_code == 200
        assert len(hub.tool_history[robot]) == 1


def test_signed_status_result_drops_when_source_changes_during_head_await(
    settings, tokens, monkeypatch,
):
    """N->N+1 while hardware read waits must not return old status or history."""
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    robot = settings.robots[0].id
    hub = CameraFrameHub([robot])
    visual = SimpleNamespace(hub=hub, _turn_epoch={robot: 15})
    entered, release = threading.Event(), threading.Event()

    class Head:
        async def status(self):
            entered.set()
            assert await asyncio.to_thread(release.wait, 3)
            return {"robot_id": robot, "safety": {"fault": "none"}}

    async def noop():
        pass

    listener = SimpleNamespace(monitor_ready=True, _event_generation=0)
    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid), heads={robot: Head()},
        ),
        multimodal=visual, _voice_turn_generations={robot: 61},
        voice_events=listener, pet=SimpleNamespace(voice_monitor_ready=True),
        start=noop, close=noop,
    )
    path = f"/v1/robots/{robot}/status"
    old = _signed_tool_headers(settings, tokens, robot, path, 61, monkeypatch)
    with TestClient(create_app(settings, runtime=runtime)) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.get, path, headers=old)
            try:
                assert entered.wait(2)
                runtime._voice_turn_generations[robot] = 62
                listener._event_generation += 1
                assert visual._turn_epoch[robot] == 15
            finally:
                release.set()
            result = pending.result(timeout=4)
            assert result.status_code == 409
            assert "superseded" in result.json()["detail"]
    assert not hub.tool_history[robot]


@pytest.mark.parametrize("stale_axis", ["mac", "listener", "visual"])
def test_signed_tool_status_rejects_each_single_epoch_change(
    settings, tokens, monkeypatch, stale_axis,
):
    """868AwRd: mutating any one epoch independently still fences late status."""
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from desk_robot.api import create_app
    from desk_robot.multimodal import CameraFrameHub
    from fastapi.testclient import TestClient

    robot = settings.robots[0].id
    hub = CameraFrameHub([robot])
    visual = SimpleNamespace(hub=hub, _turn_epoch={robot: 15})
    entered, release = threading.Event(), threading.Event()

    class Head:
        async def status(self):
            entered.set()
            assert await asyncio.to_thread(release.wait, 3)
            return {"robot_id": robot, "safety": {"fault": "none"}}

    async def noop():
        pass

    listener = SimpleNamespace(monitor_ready=True, _event_generation=0)
    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid), heads={robot: Head()},
        ),
        multimodal=visual, _voice_turn_generations={robot: 61},
        voice_events=listener, pet=SimpleNamespace(voice_monitor_ready=True),
        start=noop, close=noop,
    )
    path = f"/v1/robots/{robot}/status"
    old = _signed_tool_headers(settings, tokens, robot, path, 61, monkeypatch)
    with TestClient(create_app(settings, runtime=runtime)) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.get, path, headers=old)
            try:
                assert entered.wait(2)
                if stale_axis == "mac":
                    runtime._voice_turn_generations[robot] = 62
                elif stale_axis == "listener":
                    listener._event_generation += 1
                else:
                    visual._turn_epoch[robot] = 16
            finally:
                release.set()
            result = pending.result(timeout=4)
            assert result.status_code == 409
            assert "superseded" in result.json()["detail"]
    assert not hub.tool_history[robot]


def test_signed_tool_receipt_owner_cannot_be_reused_for_peer(settings, tokens, monkeypatch):
    """Equal Mac and Xiaozhi epochs do not make two robots interchangeable."""
    from types import SimpleNamespace

    from desk_robot import api
    from desk_robot.multimodal import CameraFrameHub
    from fastapi import HTTPException

    settings.mode = "hardware"
    robot, peer = (entry.id for entry in settings.robots[:2])
    hub = CameraFrameHub([robot, peer])
    visual = SimpleNamespace(hub=hub, _turn_epoch={robot: 7, peer: 7})
    captured = {}
    register = api.register_robot_status_routes

    def capture_routes(*args, **kwargs):
        captured.update(kwargs)
        return register(*args, **kwargs)

    async def noop():
        pass

    monkeypatch.setattr(api, "register_robot_status_routes", capture_routes)
    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot, heads={}),
        multimodal=visual, _voice_turn_generations={robot: 41, peer: 41},
        voice_events=SimpleNamespace(monitor_ready=True, _event_generation=2),
        pet=SimpleNamespace(voice_monitor_ready=True),
        start=noop, close=noop,
    )
    with TestClient(create_app(settings, runtime=runtime)):
        path = f"/v1/robots/{robot}/status"
        headers = _signed_tool_headers(settings, tokens, robot, path, 41, monkeypatch)
        request = SimpleNamespace(
            headers={key.lower(): value for key, value in headers.items()},
            method="GET", url=SimpleNamespace(path=path),
        )
        owner = captured["requested_tool_context"](request, robot)
        assert owner is not None
        current = captured["current_tool_context"]
        remember = captured["remember_tool_context"]
        current(owner, robot, "superseded")
        with pytest.raises(HTTPException) as foreign:
            current(owner, peer, "superseded")
        assert foreign.value.status_code == 409
        with pytest.raises(HTTPException) as foreign:
            remember(owner, peer, "robot_status", "private robot status")
        assert foreign.value.status_code == 409
        assert not hub.tool_history[peer]
        assert not hub.tool_history[robot]
        assert remember(owner, robot, "robot_status", "private robot status")
        assert len(hub.tool_history[robot]) == 1
        assert not hub.tool_history[peer]


@pytest.mark.parametrize("failure_method", ["remember", "get_episode"])
def test_native_asr_storage_error_retracts_new_live_receipt(
    settings, tokens, tmp_path, monkeypatch, failure_method,
):
    """A failed SQLite write or retention read cannot leave abandoned live ASR."""
    import sqlite3
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore
    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    ids = [r.id for r in settings.robots]
    robot = ids[0]
    memory = MemoryStore(tmp_path / "private", ids)
    hub = CameraFrameHub(ids)
    older_id = "omni_" + "a" * 12 + "_" + "b" * 20
    event_id = "omni_" + "a" * 12 + "_" + "c" * 20
    assert hub.remember_heard(robot, older_id, "Earlier receipt", time.monotonic())
    assert hub.remember_heard(ids[1], older_id, "Peer receipt", time.monotonic())

    def broken_storage(*args, **kwargs):
        raise sqlite3.OperationalError("private database diagnostic")

    monkeypatch.setattr(memory, failure_method, broken_storage)

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(robot=settings.robot),
        memory=memory, multimodal=SimpleNamespace(hub=hub),
        start=noop, close=noop,
    )
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        stamp_us = time.monotonic_ns() // 1000
        response = client.post(
            f"/v1/pet/{robot}/omni-heard", headers=auth, json={
                "event_id": event_id,
                "transcript": "Unfinished receipt",
                "accepted_at_us": stamp_us,
                "audio_committed_at_us": stamp_us,
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Native transcript storage unavailable"}
    assert [item[0] for item in hub.heard_history[robot]] == [older_id]
    assert [item[0] for item in hub.heard_history[ids[1]]] == [older_id]
    assert hub.heard_revoked(robot, event_id)
    assert not hub.heard_revoked(robot, older_id)
    assert not hub.heard_revoked(ids[1], event_id)
    # A successful, consented INSERT is not rolled back merely because its
    # retention read failed. It must not become an acknowledged live receipt.
    assert memory.count(robot) == int(failure_method == "get_episode")
    assert memory.count(ids[1]) == 0
