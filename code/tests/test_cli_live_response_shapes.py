"""Malformed live doctor evidence must fail with a controlled diagnostic."""

import httpx
import pytest

from desk_robot.cli import _inspect_context, _inspect_look


@pytest.mark.asyncio
@pytest.mark.parametrize("packet", [None, [], "unavailable", 503, True])
@pytest.mark.parametrize(
    ("probe", "method", "path", "diagnostic"),
    [
        (_inspect_context, "GET", "interaction-context", "source context contract"),
        (_inspect_look, "POST", "look", "actuator boundary invalid"),
    ],
)
async def test_live_probe_rejects_non_object_json(packet, probe, method, path, diagnostic):
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=packet) if packet is not None else httpx.Response(
            200, content=b"null", headers={"content-type": "application/json"},
        )

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8765", transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(ValueError, match=diagnostic):
            await probe(client, "pet")
    assert calls == [(method, f"/v1/pet/pet/{path}")]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [None, 42, [], {}, True, "x" * 301])
async def test_live_look_requires_text_and_bounds_output(answer):
    packet = {
        "robot_id": "pet",
        "source": "authenticated_xiao_camera_and_local_vlm",
        "frames_used": 1,
        "motor_authorized": False,
        "charging_authorized": False,
        "answer": answer,
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=packet))
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8765", transport=transport) as client:
        if isinstance(answer, str):
            assert await _inspect_look(client, "pet") == {
                "live_tool_tested": True, "visual_answer": answer[:300],
            }
        else:
            with pytest.raises(ValueError, match="actuator boundary invalid"):
                await _inspect_look(client, "pet")
