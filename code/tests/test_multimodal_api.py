"""Native Mac vision endpoints can be called by Xiaozhi, not used to mint motion."""
from fastapi.testclient import TestClient

from desk_robot.api import create_app


def test_tool_token_can_request_visual_evidence_but_not_enable_motors(settings, tokens):
    app = create_app(settings)
    with TestClient(app) as client:
        calls = []

        class Vision:
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
