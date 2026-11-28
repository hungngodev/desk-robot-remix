"""Peer relay may not borrow another consent generation for live ASR."""
from types import SimpleNamespace

import pytest
from desk_robot.conversation_consent import GroupContextConsent


@pytest.mark.parametrize("revoked", ["sharing", "camera"])
@pytest.mark.parametrize("regrant", [False, True])
def test_group_asr_cannot_borrow_replacement_grant(revoked, regrant):
    settings = SimpleNamespace(
        mode="hardware", fleet_text_sharing_enabled=True,
        fleet_sharing_consent_generation=0, voice_memory_tools_enabled=False,
        voice_vision_tools_enabled=True, camera_consent_generation=0,
        camera_consent_started_at=10.0,
    )
    fence = GroupContextConsent.capture(settings, has_multimodal=True)
    speech = {"channel": "human_transcript", "source_at": 14.0, "content": "private"}
    fault = {"channel": "sensor", "source": "wroom_event"}
    assert fence.filter_live_transcripts([speech, fault], now=15.0) == [speech, fault]
    if revoked == "sharing":
        settings.fleet_text_sharing_enabled = regrant
        settings.fleet_sharing_consent_generation += 1
    else:
        settings.voice_vision_tools_enabled = regrant
        settings.camera_consent_generation += 1
        settings.camera_consent_started_at = 13.0
    assert fence.filter_live_transcripts([speech, fault], now=15.0) == [fault]
    fresh = GroupContextConsent.capture(settings, has_multimodal=True)
    assert fresh.filter_live_transcripts([speech, fault], now=15.0) == (
        [speech, fault] if regrant else [fault]
    )
