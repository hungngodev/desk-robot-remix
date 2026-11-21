"""Authenticated Sense AEC integrity telemetry is read-only, not playback proof."""

import httpx
import pytest
from desk_robot.config import RobotConfig
from desk_robot.transport import HeadError, HttpHead


def _head(client):
    return HttpHead(
        RobotConfig(
            id="robot-01", name="Sense pet", token_env="SENSE_DIAG_TEST_TOKEN",
            head_url="http://sense.local",
        ),
        client,
    )


@pytest.mark.asyncio
async def test_actual_sense_reference_counters_are_authenticated_and_bounded(
    monkeypatch,
):
    monkeypatch.setenv("SENSE_DIAG_TEST_TOKEN", "s" * 32)
    calls = []

    def reply(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "reference_underflow_reads": 11,
            "reference_overwrite_reads": 2,
            "discarded_stale_writes": 3,
            "reference_integrity_failed": True,
            "speaker_playback_verified": False,
            "aec_physically_qualified": False,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        observed = await _head(client).audio_reference_status()
    assert observed["reference_underflow_reads"] == 11
    assert observed["reference_integrity_failed"] is True
    assert calls == [("GET", "/api/audio.reference", "Bearer " + "s" * 32)]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [
    {"robot_id": "robot-02"},
    {"reference_underflow_reads": -1},
    {"reference_underflow_reads": True},
    {"reference_overwrite_reads": 0x1_0000_0000},
    {"discarded_stale_writes": "3"},
    {"reference_integrity_failed": 0},
    {"speaker_playback_verified": True},
    {"aec_physically_qualified": True},
])
async def test_no_foreign_or_fabricated_reference_evidence(monkeypatch, changed):
    monkeypatch.setenv("SENSE_DIAG_TEST_TOKEN", "s" * 32)
    receipt = {
        "robot_id": "robot-01",
        "reference_underflow_reads": 0,
        "reference_overwrite_reads": 0,
        "discarded_stale_writes": 0,
        "reference_integrity_failed": False,
        "speaker_playback_verified": False,
        "aec_physically_qualified": False,
    }
    receipt.update(changed)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=receipt)
    )) as client:
        with pytest.raises(HeadError, match="Untrusted Sense AEC"):
            await _head(client).audio_reference_status()
