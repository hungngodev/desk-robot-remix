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
        assert body["transcript_memory_enabled"] is False
        assert body["model_can_arm_motors"] is False
        assert len(body["instructions"]) <= 2000
        assert client.get(f"/v1/pet/{pet.id}/omni-context").status_code == 401


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
    request = {
        "event_id": "omni_" + "a" * 12 + "_" + "b" * 20,
        "transcript": "I put a key beside the robot",
    }
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        assert client.post(url, json=request).status_code == 401
        first = client.post(url, headers=tool, json=request)
        assert first.status_code == 200
        assert first.json()["stored"] is True
        assert first.json()["motor_authorized"] is False
        assert first.json()["speaker_identity_verified"] is False
        second = client.post(url, headers=tool, json=request)
        assert second.status_code == 200
        assert second.json()["stored"] is False
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

    class StubRuntime:
        coordinator = SimpleNamespace(robot=settings.robot)
        async def start(self):
            pass

        async def close(self):
            pass

    runtime = StubRuntime()
    runtime.memory = memory
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        own = client.get("/v1/pet/robot-01/omni-context", headers=auth)
        other = client.get("/v1/pet/robot-02/omni-context", headers=auth)
        assert own.status_code == other.status_code == 200
        text = own.json()["instructions"]
        assert "favorite_game: hide the key" in text
        assert "I said: Hello, my little friend" in text
        assert "uncertain transcription" in text
        assert "I observed: Hello" not in text
        peer_text = other.json()["instructions"]
        assert "I heard robot-01 say: I saw a pink key" in peer_text
        assert "favorite_game" not in peer_text
        assert "Hello, my little friend" not in peer_text
        settings.voice_memory_tools_enabled = False
        disabled = client.get("/v1/pet/robot-01/omni-context", headers=auth)
        assert disabled.status_code == 200
        assert disabled.json()["memory_enabled"] is False
        assert "hide the key" not in disabled.json()["instructions"]


def test_authoritative_latest_pickup_status_survives_head_reconnect_without_cross_pet_leak(
    settings, tokens,
):
    from desk_robot.controller import Job

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
        untouched = client.get(
            "/v1/robots/robot-03/jobs/latest-pickup", headers=tool
        )
        assert untouched.status_code == 200
        assert untouched.json() == {
            "robot_id": "robot-03", "available": False,
            "physical_grasp_verified": False,
        }
        assert client.get(
            "/v1/robots/unknown/jobs/latest-pickup", headers=tool
        ).status_code == 404
        # The old operator job-by-id API remains authoritative and intact.
        assert client.get(
            "/v1/jobs/first", headers=tool
        ).json()["state"] == "failed"
