"""Xiaozhi tools cannot create an operator permit or send raw motor commands."""

import os

import httpx
from desk_robot_bridge import robot_for_device
from plugins_func.register import Action, ActionResponse, ToolType, register_function


async def call(conn, route, payload=None):
    robot = robot_for_device(conn.device_id)
    token = os.environ.get("DESK_ROBOT_TOOL_TOKEN", "")
    if robot is None or len(token) < 24:
        return {"error": "Robot mapping or local tool credential is missing"}
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8765", timeout=5, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        if route == "status":
            response = await client.get(f"/v1/robots/{robot}/status")
        elif route == "job":
            response = await client.get(f"/v1/jobs/{conn.desk_robot_last_job}")
        else:
            response = await client.post(f"/v1/robots/{robot}/{route}", json=payload or {})
        if response.status_code >= 400:
            return {"error": response.text, "note": "No action is retried"}
        return response.json()


def description(name, text, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": text,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


@register_function(
    "desk_robot_pickup",
    description(
        "desk_robot_pickup",
        "Request one experimental camera-guided pickup. A human must first enable one job for this robot. "
        "The result is only an accepted job ID; check the job before claiming a pickup.",
        {"target": {"type": "string", "enum": ["key", "candy"]}},
        ["target"],
    ),
    ToolType.IOT_CTL,
)
async def desk_robot_pickup(conn, target):
    if target not in {"key", "candy"}:
        return ActionResponse(Action.REQLLM, result={"error": "Target must be key or candy"})
    result = await call(conn, "pickup", {"target": target})
    if "id" in result:
        conn.desk_robot_last_job = result["id"]
    return ActionResponse(Action.REQLLM, result=result)


@register_function(
    "desk_robot_stop",
    description("desk_robot_stop", "Cancel this robot's job and stop movement."),
    ToolType.IOT_CTL,
)
async def desk_robot_stop(conn):
    return ActionResponse(Action.REQLLM, result=await call(conn, "stop"))


@register_function(
    "desk_robot_job",
    description(
        "desk_robot_job", "Read the last pickup job; do not infer success from servo commands."
    ),
    ToolType.IOT_CTL,
)
async def desk_robot_job(conn):
    result = (
        await call(conn, "job")
        if getattr(conn, "desk_robot_last_job", None)
        else {"error": "No job requested"}
    )
    return ActionResponse(Action.REQLLM, result=result)
