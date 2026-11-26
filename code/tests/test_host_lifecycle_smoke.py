"""Cross-owner host smoke; simulated IO never qualifies physical hardware."""

import httpx
from desk_robot.api import create_app
from desk_robot.vision import SceneChange


async def test_real_app_pet_context_and_coordinator_lifecycle(settings, tokens):
    app = create_app(settings)
    robot_id, peer_id = (robot.id for robot in settings.robots[:2])
    pet_path = f"/v1/pet/{robot_id}"
    robot_path = f"/v1/robots/{robot_id}"
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    marker = "Keep the violet notebook nearby"
    for robot in settings.robots:
        robot.motor_backend = "stepper_28byj48"

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        head = runtime.coordinator.heads[robot_id]
        assert runtime.pet.heads[robot_id] is head
        assert runtime.pet.memory is runtime.memory is runtime.conversation.memory
        assert runtime.pet.conversation is runtime.conversation
        assert runtime.pet.coordinator_jobs is runtime.coordinator.jobs
        assert runtime.conversation.attention is runtime.pet.attention is runtime.attention
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            health = await client.get("/v1/health", headers=operator)
            assert health.status_code == 200
            assert health.json()["runtime_ready"] is True
            assert health.json()["physical_acceptance_pass"] is False

            started = await client.post(pet_path + "/start", headers=operator)
            assert started.status_code == 200
            assert started.json()["enabled"] is True
            observer = runtime.pet.states[robot_id].task
            assert observer is not None and not observer.done()

            stored = await client.put(
                pet_path + "/core-memory/preference", headers=operator, json={"value": marker},
            )
            assert stored.status_code == 200
            assert stored.json()["changed"] is True
            change = SceneChange("object", "A violet notebook", 0.99)
            context = await runtime.pet._load_proactive_context(robot_id, change)
            peer_context = await runtime.pet._load_proactive_context(peer_id, change)
            assert context is not None and marker in context[1].core
            assert peer_context is not None and marker not in peer_context[1].core

            enabled = await client.post(robot_path + "/enable", headers=operator)
            assert enabled.status_code == 200, enabled.text
            assert robot_id in runtime.coordinator.permits
            stopped = await client.post(robot_path + "/stop", headers=tool)
            assert stopped.status_code == 200, stopped.text
            assert robot_id not in runtime.coordinator.permits
            assert head.commands[-1] == "halt"
            assert runtime.pet.states[robot_id].enabled is False
            assert observer.done()

            restarted = await client.post(pet_path + "/start", headers=operator)
            assert restarted.status_code == 200
            restarted_observer = runtime.pet.states[robot_id].task
            assert restarted_observer is not None and restarted_observer is not observer

    assert app.state.runtime_started is False
    assert runtime.client.is_closed
    assert runtime.coordinator.closed
    assert runtime.pet._closed
    assert not runtime.coordinator.permits
    assert restarted_observer.done()
    assert not runtime.pet.states[robot_id].enabled
    assert runtime.conversation.active is None
