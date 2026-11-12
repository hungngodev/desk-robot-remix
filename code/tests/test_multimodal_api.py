"""Native Mac vision endpoints can be called by Xiaozhi, not used to mint motion."""
from fastapi.testclient import TestClient

from desk_robot.api import create_app


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
        assert body["memory_enabled"] is False
        assert body["model_can_arm_motors"] is False
        assert len(body["instructions"]) <= 2000
        assert client.get(f"/v1/pet/{pet.id}/omni-context").status_code == 401
