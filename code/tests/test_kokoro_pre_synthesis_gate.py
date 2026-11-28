"""A stale utterance must not begin expensive Xiaozhi Kokoro synthesis."""

from types import SimpleNamespace

import pytest
from desk_robot.conversation import KokoroHeadSpeaker


@pytest.mark.asyncio
async def test_revoked_permission_never_starts_kokoro_or_bridge(settings):
    robot = settings.robots[0]
    calls = []

    class Client:
        async def post(self, *args, **kwargs):
            calls.append(("kokoro", args, kwargs))
            raise AssertionError("Revoked speech reached Kokoro")

    speaker = KokoroHeadSpeaker(settings, Client())

    async def unexpected_bridge(*args, **kwargs):
        calls.append(("bridge", args, kwargs))
        raise AssertionError("Revoked speech reached Xiaozhi")

    speaker._bridge = unexpected_bridge
    owned = speaker._lease_context.set("owned-test-lease")
    try:
        with pytest.raises(RuntimeError, match="revoked before synthesis"):
            await speaker.say(
                robot, "A private sentence from a revoked turn",
                permission_check=lambda: False,
            )
    finally:
        speaker._lease_context.reset(owned)

    assert calls == []


@pytest.mark.asyncio
async def test_current_permission_preserves_normal_synthesis_and_send(settings):
    robot = settings.robots[0]
    robot.device_id = "device-test"
    calls = []

    class Client:
        async def post(self, *args, **kwargs):
            calls.append(("kokoro", args, kwargs))
            return SimpleNamespace(
                content=b"RIFFtest",
                raise_for_status=lambda: None,
            )

    speaker = KokoroHeadSpeaker(settings, Client())

    async def bridge(route, payload):
        calls.append(("bridge", route, payload))
        return {
            "device_id": robot.device_id,
            "transmitted": True,
            "physical_playback_verified": False,
        }

    speaker._bridge = bridge
    owned = speaker._lease_context.set("owned-test-lease")
    try:
        await speaker.say(
            robot, "A permitted sentence", permission_check=lambda: True,
        )
    finally:
        speaker._lease_context.reset(owned)

    assert [call[0] for call in calls] == ["kokoro", "bridge"]
    assert calls[1][1] == "/speak"
    assert calls[1][2]["lease_id"] == "owned-test-lease"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["synthesis", "transmission"])
async def test_permission_revoked_at_async_boundary_rejects_stale_speech(settings, phase):
    robot = settings.robots[0]
    robot.device_id = "device-test"
    allowed = True
    calls = []

    class Client:
        async def post(self, *args, **kwargs):
            nonlocal allowed
            calls.append("kokoro")
            if phase == "synthesis":
                allowed = False
            return SimpleNamespace(content=b"RIFFtest", raise_for_status=lambda: None)

    speaker = KokoroHeadSpeaker(settings, Client())

    async def bridge(route, payload):
        nonlocal allowed
        calls.append(route)
        assert phase == "transmission", "Revoked WAV reached the speech bridge"
        allowed = False
        return {
            "device_id": robot.device_id,
            "transmitted": True,
            "physical_playback_verified": False,
        }

    speaker._bridge = bridge
    owned = speaker._lease_context.set("owned-test-lease")
    try:
        with pytest.raises(RuntimeError, match=f"revoked during {phase}"):
            await speaker.say(robot, "Stale reply", permission_check=lambda: allowed)
    finally:
        speaker._lease_context.reset(owned)

    assert calls == (["kokoro"] if phase == "synthesis" else ["kokoro", "/speak"])
