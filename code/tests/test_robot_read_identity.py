"""Unknown fleet identities are rejected before runtime or private memory access."""
import pytest
from desk_robot.api import create_app
from fastapi.testclient import TestClient


class UnusedRuntime:
    async def start(self):
        pass

    async def close(self):
        pass

    def __getattr__(self, name):
        raise AssertionError(f"Unknown robot accessed runtime attribute {name}")


@pytest.mark.parametrize("robot_id", ["unknown", "ROBOT-01", "robot 01", "x" * 41, "robot-é"])
@pytest.mark.parametrize("path", [
    "/v1/pet/{}/memories",
    "/v1/pet/{}/core-memory",
    "/v1/pet/{}/voice-context",
    "/v1/pet/{}/interaction-context",
    "/v1/pet/{}/omni-context",
    "/v1/pet/{}/power-status",
    "/v1/pet/{}/vision-status",
    "/v1/pet/{}",
    "/v1/robots/{}/status",
    "/v1/robots/{}/aux",
])
def test_unknown_robot_read_never_reaches_runtime(fleet, tokens, path, robot_id):
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    with TestClient(create_app(fleet, runtime=UnusedRuntime())) as client:
        response = client.get(path.format(robot_id), headers=headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "Robot not found"}


def test_empty_robot_path_never_reaches_runtime(fleet, tokens):
    headers = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    with TestClient(create_app(fleet, runtime=UnusedRuntime())) as client:
        response = client.get("/v1/pet//memories", headers=headers, follow_redirects=False)
    assert response.status_code == 404
