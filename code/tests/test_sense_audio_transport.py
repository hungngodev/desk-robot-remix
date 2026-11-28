"""Sense audio status authenticates boot, live frame counters and identity.

These are I2S acceptance / PDM read diagnostics, never audible playback ACK.
"""
from __future__ import annotations

import httpx
import pytest
from desk_robot.config import RobotConfig
from desk_robot.transport import HeadError, HttpHead


def receipt() -> dict:
    return {
        "robot_id": "robot-01",
        "boot": 19,
        "reference_underflow_reads": 0,
        "reference_overwrite_reads": 0,
        "discarded_stale_writes": 0,
        "short_output_writes": 0,
        "microphone_frames_read": 32000,
        "speaker_frames_accepted": 64000,
        "microphone_privacy_muted": False,
        "microphone_privacy_epoch": 0,
        "aec_delay_config_ms": 90,
        "reference_integrity_failed": False,
        "speaker_playback_verified": False,
        "aec_physically_qualified": False,
    }


async def query(payload: dict, monkeypatch):
    monkeypatch.setenv("SENSE_AUDIO_TEST_TOKEN", "x" * 32)

    def respond(request):
        assert request.url.path == "/api/audio.reference"
        assert request.headers["authorization"] == "Bearer " + "x" * 32
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        head = HttpHead(RobotConfig(
            id="robot-01", name="Pip", head_url="http://head.example",
            token_env="SENSE_AUDIO_TEST_TOKEN",
        ), client)
        return await head.audio_reference_status()


async def test_real_sense_audio_status_is_read_only_and_not_playback_ack(monkeypatch):
    data = await query(receipt(), monkeypatch)
    assert data["microphone_frames_read"] == 32000
    assert data["speaker_frames_accepted"] == 64000
    assert data["microphone_privacy_muted"] is False
    assert data["microphone_privacy_epoch"] == 0
    assert data["aec_delay_config_ms"] == 90
    assert data["speaker_playback_verified"] is False
    assert data["aec_physically_qualified"] is False


@pytest.mark.parametrize("change", [
    {"robot_id": "robot-02"},
    {"boot": None},
    {"boot": True},
    {"boot": -1},
    {"boot": 0x100000000},
    {"microphone_frames_read": None},
    {"microphone_frames_read": False},
    {"microphone_frames_read": -1},
    {"microphone_frames_read": 0x100000000},
    {"speaker_frames_accepted": 0.5},
    {"short_output_writes": "0"},
    {"short_output_writes": True},
    {"microphone_privacy_muted": 1},
    {"microphone_privacy_muted": None},
    {"microphone_privacy_epoch": True},
    {"microphone_privacy_epoch": -1},
    {"microphone_privacy_epoch": 0x100000000},
    {"aec_delay_config_ms": None},
    {"aec_delay_config_ms": True},
    {"aec_delay_config_ms": 251},
    {"speaker_playback_verified": True},
    {"aec_physically_qualified": True},
    {"reference_integrity_failed": "false"},
])
async def test_sense_audio_status_rejects_bad_identity_or_provenance(
    monkeypatch, change,
):
    data = receipt()
    data.update(change)
    with pytest.raises(HeadError, match="Untrusted Sense AEC"):
        await query(data, monkeypatch)
